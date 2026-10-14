"""Bounded SQL searches and ancestry; genome payloads stay out of list queries."""
import json
from .storage import encode

SORTS={'date':'e.created','name':'e.name COLLATE NOCASE','generation':'e.generation','size':'COALESCE(s.logical_bytes,0)','status':'e.status'}

def search(store,*,q='',status='',environment='',tags=(),group='',seed='',origin='',since=0,until=1e20,min_generation=0,max_generation=1000000,min_fitness=None,max_fitness=None,min_size=None,max_size=None,sort='date',descending=True,limit=50,offset=0):
    if sort not in SORTS or not 1<=limit<=200 or offset<0:raise ValueError('invalid pagination or sort')
    where=['e.created>=?','e.created<=?','e.generation>=?','e.generation<=?'];args=[since,until,min_generation,max_generation]
    if q:
        where.append('(e.id LIKE ? OR e.name LIKE ? OR e.config LIKE ? OR n.content LIKE ? OR e.origin LIKE ? OR EXISTS (SELECT 1 FROM experiment_tags t WHERE t.experiment_id=e.id AND t.tag LIKE ?))');args.extend([f'%{q}%']*6)
    for clause,value in [('e.status=?',status),("json_extract(e.config,'$.environment.type')=?",environment),('rg.name=?',group),("CAST(json_extract(e.config,'$.seed') AS TEXT)=?",seed)]:
        if value!='':where.append(clause);args.append(value)
    for tag in tags:
        where.append('EXISTS (SELECT 1 FROM experiment_tags t WHERE t.experiment_id=e.id AND t.tag=?)');args.append(tag)
    if origin:
        if origin not in ('native','imported'):raise ValueError('origin must be native or imported')
        where.append("e.status='imported'" if origin=='imported' else "e.status!='imported'")
    for operator,value in [('>=',min_fitness),('<=',max_fitness)]:
        if value is not None:
            where.append(f"(SELECT MAX(json_extract(g.statistics,'$.maximum')) FROM generations g WHERE g.experiment_id=e.id) {operator} ?");args.append(value)
    for operator,value in [('>=',min_size),('<=',max_size)]:
        if value is not None:where.append(f's.logical_bytes {operator} ?');args.append(value)
    base=' FROM experiments e LEFT JOIN notes n ON n.experiment_id=e.id LEFT JOIN research_groups rg ON rg.experiment_id=e.id LEFT JOIN storage_estimates s ON s.experiment_id=e.id WHERE '+' AND '.join(where)
    total=store.query('SELECT COUNT(*) n'+base,args)[0]['n']
    rows=store.query('SELECT e.*,rg.name AS research_group,s.logical_bytes,s.details AS storage,s.measured AS storage_measured,s.generation AS estimated_at_generation'+base+f' ORDER BY {SORTS[sort]} '+('DESC' if descending else 'ASC')+',e.id LIMIT ? OFFSET ?',(*args,limit,offset))
    for row in rows:
        row['config']=json.loads(row['config']);row['seed_text']=str(row['config']['seed'])
        row['storage']=json.loads(row['storage']) if row['storage'] else None
        row['tags']=[t['tag'] for t in store.query('SELECT tag FROM experiment_tags WHERE experiment_id=? ORDER BY tag',(row['id'],))]
    return {'items':rows,'total':total,'limit':limit,'offset':offset,'size_note':'Cached logical storage estimates; refresh in Storage Manager before filtering by size.'}

def family_graph(store,eid,nid,direction='ancestors',depth=4,limit=100,cursor=None,generation_min=0,generation_max=1000000):
    """Bounded breadth-first expansion of stored edges, including unknown parents.

    Cursor contains a bounded frontier, not a serialized full traversal. Each page
    supplies independent nodes/edges; clients merge by identity and edge triple.
    Cycles never loop: per-page seen nodes and remaining depth bound traversal.
    """
    store.experiment(eid)
    if direction not in ('ancestors','descendants') or not 1<=depth<=30 or not 2<=limit<=200:raise ValueError('invalid family graph bounds')
    if not store.query('SELECT 1 FROM genomes WHERE experiment_id=? AND id=?',(eid,nid)):raise KeyError('network')
    if cursor:
        if len(cursor)>12000:raise ValueError('cursor too long')
        try:
            import base64
            payload=json.loads(base64.urlsafe_b64decode(cursor))
            if payload['eid']!=eid or payload['nid']!=nid or payload['direction']!=direction:raise ValueError('cursor query mismatch')
            frontier=payload['frontier']
            if len(frontier)>400 or any(len(x)!=3 or any(type(y) is not int or y<0 for y in x) or x[1]>30 for x in frontier):raise ValueError('invalid cursor bounds')
        except (KeyError,TypeError,json.JSONDecodeError,UnicodeDecodeError) as exc:raise ValueError('invalid graph cursor') from exc
    else:frontier=[[nid,depth,0]]
    nodes={};edges=[];seen=set();truncated_depth=False;edge_budget=limit*2
    db=store.connect()
    try:
        def node(identity):
            if identity in nodes:return
            row=db.execute('SELECT id,layers,activations,metadata,fingerprint FROM genomes WHERE experiment_id=? AND id=?',(eid,identity)).fetchone()
            if row is None:nodes[identity]={'id':identity,'unknown':True,'label':'Unknown historical ancestor'};return
            meta=json.loads(row['metadata']);fitness=db.execute('SELECT generation,total FROM fitness WHERE experiment_id=? AND network_id=? ORDER BY generation DESC LIMIT 1',(eid,identity)).fetchone()
            parent_count=db.execute('SELECT COUNT(*) FROM parents WHERE experiment_id=? AND child_id=?',(eid,identity)).fetchone()[0]
            nodes[identity]={'id':identity,'layers':json.loads(row['layers']),'activations':json.loads(row['activations']),'fingerprint':row['fingerprint'],
                'birth_generation':meta.get('birth_generation'),'mutation_count':len(meta.get('mutations',[])),'parent_count':parent_count,
                'founder':parent_count==0,'fitness':dict(fitness) if fitness else None,'unknown':False,
                'bookmarked':bool(db.execute("SELECT 1 FROM bookmarks WHERE experiment_id=? AND CAST(json_extract(reference,'$.network_id') AS INTEGER)=? LIMIT 1",(eid,identity)).fetchone())}
        while frontier and len(nodes)<limit and len(edges)<edge_budget:
            identity,remaining,after=frontier.pop(0)
            if (identity,remaining,after) in seen:continue
            seen.add((identity,remaining,after));node(identity)
            if remaining==0:truncated_depth=True;continue
            source,target=('child_id','parent_id') if direction=='ancestors' else ('parent_id','child_id')
            available=min(limit-len(nodes),edge_budget-len(edges))
            if available<=0:frontier.insert(0,[identity,remaining,after]);break
            rows=db.execute(f'SELECT child_id,parent_id,{target} AS target FROM parents WHERE experiment_id=? AND {source}=? AND {target}>? ORDER BY {target} LIMIT ?',(eid,identity,after,available+1)).fetchall()
            batch=rows[:available]
            for edge in batch:
                node(edge['target']);edges.append({'parent':edge['parent_id'],'child':edge['child_id']})
                if edge['target']!=identity:frontier.append([edge['target'],remaining-1,0])
            if len(rows)>available:frontier.insert(0,[identity,remaining,batch[-1]['target']])
        # Frontiers can grow only by the bounded edge budget. De-duplicate to keep
        # a converging graph's cursor bounded; depth remains explicit.
        frontier=list({tuple(x):x for x in frontier}.values())
        deferred_expansion=frontier[400:]
        frontier=frontier[:400]
        next_cursor=None
        if frontier:
            import base64
            next_cursor=base64.urlsafe_b64encode(encode({'eid':eid,'nid':nid,'direction':direction,'frontier':frontier}).encode()).decode()
        # Range filtering changes presentation only. Unknown nodes are retained
        # and edges always refer to returned placeholder or known nodes.
        for item in nodes.values():
            birth=item.get('birth_generation');item['outside_range']=birth is not None and not generation_min<=birth<=generation_max
        return {'nodes':list(nodes.values()),'edges':edges,'next_cursor':next_cursor,'depth_boundary':truncated_depth,'deferred_expansion':[x[0] for x in deferred_expansion],'generation_range':[generation_min,generation_max],
                'recorded_cluster_note':'Per-network cluster memberships were not retained by v2.0. Only aggregate cluster sizes were recorded; no cluster coloring is inferred.',
                'founder_note':'Founder marks a recorded node with no stored parent edge. Missing ancestors remain unknown; global founder assignments require complete ancestry.'}
    finally:db.close()

def genetic_comparison(store,a,an,b,bn,layer=0,offset=0,limit=256,kind='weights'):
    import numpy as np
    if not 0<=offset or not 1<=limit<=1024 or kind not in ('weights','biases'):raise ValueError('invalid matrix section')
    ga,gb=store.genome(a,an),store.genome(b,bn)
    def metadata(g,eid):
        fits=store.query('SELECT generation,total FROM fitness WHERE experiment_id=? AND network_id=? ORDER BY generation DESC LIMIT 1',(eid,g.id))
        return {'experiment_id':eid,'id':g.id,'layers':g.layers,'activations':g.activations,'parameter_count':len(g.parameters),'fingerprint':g.fingerprint,'parents':store.query('SELECT parent_id FROM parents WHERE experiment_id=? AND child_id=?',(eid,g.id)),'birth_generation':g.birth_generation,'fitness':fits[0] if fits else None}
    result={'a':metadata(ga,a),'b':metadata(gb,b),'compatible':ga.layers==gb.layers and ga.activations==gb.activations}
    if not result['compatible']:return {**result,'explanation':'Architectures or activations differ; elementwise parameter alignment and RMS comparison are not meaningful.'}
    if not 0<=layer<len(ga.layers)-1:raise ValueError('layer out of bounds')
    sizes=[x*y for x,y in zip(ga.layers,ga.layers[1:])];biases=list(ga.layers[1:]);sizes_used=sizes if kind=='weights' else biases
    start=sum(sizes_used[:layer])+(sum(sizes) if kind=='biases' else 0);length=sizes_used[layer]
    delta=gb.parameters-ga.parameters;absolute=np.abs(delta)
    indices=np.argsort(absolute)[-min(20,len(delta)):][::-1]
    cells=[{'index':i,'section_index':i-start,'a':float(ga.parameters[i]),'b':float(gb.parameters[i]),'difference':float(delta[i]),'absolute':float(absolute[i]),'changed':bool(delta[i]!=0)} for i in range(start+min(offset,length),start+min(offset+limit,length))]
    return {**result,'rms':float(np.sqrt(np.mean(delta**2))),'changed_parameters':int(np.count_nonzero(delta)),
            'largest_differences':[{'index':int(i),'difference':float(delta[i]),'a':float(ga.parameters[i]),'b':float(gb.parameters[i])} for i in indices],
            'layer':layer,'kind':kind,'rows':ga.layers[layer+1],'columns':ga.layers[layer] if kind=='weights' else 1,'section_length':length,'offset':offset,'cells':cells,'next_offset':offset+limit if offset+limit<length else None,
            'ordering':'All layer weight matrices first (output row, input column), then all layer bias vectors; original stored parameter order.'}
