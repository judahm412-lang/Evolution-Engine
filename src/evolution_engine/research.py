"""Independent saved-genome analyses; these never feed rewards into evolution."""
import csv
import gzip
import io
import json
import time
import zipfile
import numpy as np
from .environments import PolicyCache, trace_match
from .evolution import cluster_labels
from .rps_core import batch_matches,HISTORIES,FULL,original_bot_score
from .storage import encode

def tournament(genomes,rounds=23,repeats=1,full_starts=False):
    if not 1<=len(genomes)<=200 or not 1<=rounds<=10000 or not 1<=repeats<=100:raise ValueError('invalid tournament bounds')
    if any(g.layers[0]!=9 or g.layers[-1]!=3 for g in genomes):raise ValueError('RPS tournaments require 9 inputs and 3 outputs')
    compatibility=all(g.layers==(9,12,3) and g.activations==('sigmoid','linear') for g in genomes)
    p=PolicyCache().get(genomes,compatibility)
    starts=[(0,0,0)]+[h for h in HISTORIES if all(h)] if full_starts else [(0,0,0)]
    begin=time.perf_counter()
    matrix=sum(batch_matches(p,p,rounds,h)[0] for h in starts)*repeats
    # Diagonal self-matches are excluded from reported competitive match counts.
    totals=matrix.sum(axis=1);order=np.argsort(-totals,kind='stable')
    return {'ids':[g.id for g in genomes],'net_matrix':matrix.tolist(),
            'ranking':[{'index':int(i),'id':genomes[int(i)].id,'net':int(totals[i])} for i in order],
            'rounds':rounds,'repeats':repeats,'starts':starts,'matches':len(genomes)*(len(genomes)-1)*len(starts)*repeats,
            'original_bots':[{'id':g.id,'scores':[[original_bot_score(policy,k,o) for o in range(3)] for k in (1,2,3)]} for g,policy in zip(genomes,p)],
            'elapsed_seconds':time.perf_counter()-begin}

def inspect(store,eid,nid,observations=None):
    g=store.genome(eid,nid);result=g.record();result['fingerprint']=g.fingerprint
    result['fitness']=store.query('SELECT generation,total,self_play,bot FROM fitness WHERE experiment_id=? AND network_id=? ORDER BY generation LIMIT 1000',(eid,nid))
    result['descendants']=store.query('SELECT child_id FROM parents WHERE experiment_id=? AND parent_id=? LIMIT 200',(eid,nid))
    if observations is not None:result['outputs']=g.forward(observations,store.experiment(eid)['config']['mode']=='compatibility').tolist()
    if g.layers[0]==9 and g.layers[-1]==3:
        p=PolicyCache().get([g],g.layers==(9,12,3) and g.activations==('sigmoid','linear'))[0]
        result['policy']=[{'history':h,'move':int(m)} for h,m in zip(HISTORIES,p)]
    layers=[];wi=0;bi=g.weight_count
    for a,b,activation in zip(g.layers,g.layers[1:],g.activations):
        layers.append({'activation':activation,'weights':g.parameters[wi:wi+a*b].reshape(b,a).tolist(),'biases':g.parameters[bi:bi+b].tolist()});wi+=a*b;bi+=b
    result['layer_parameters']=layers
    return result

def lineage(store,eid,nid,depth=30):
    nodes=[];seen=set();current=nid
    for _ in range(min(depth,200)):
        if current in seen:raise ValueError('cyclic ancestry in stored data')
        seen.add(current)
        try:g=store.genome(eid,current)
        except KeyError:
            nodes.append({'id':current,'missing':True});break
        nodes.append({'id':g.id,'parent_id':g.parent_id,'birth_generation':g.birth_generation,'mutations':len(g.mutations)})
        if not g.parent_id:break
        current=g.parent_id
    return {'nodes':nodes,'truncated':bool(nodes and nodes[-1].get('parent_id'))}

def population_analysis(store,eid,generation):
    pop=store.population(eid,generation)
    if not pop:raise ValueError('snapshot not retained or generation not evaluated')
    genes=np.stack([g.parameters for g in pop]);labels=cluster_labels(genes)
    parents={r['child_id']:r['parent_id'] for r in store.query('SELECT child_id,parent_id FROM parents WHERE experiment_id=?',(eid,))}
    known={r['id'] for r in store.query('SELECT id FROM genomes WHERE experiment_id=?',(eid,))};resolved={}
    families={}
    for g in pop:
        chain=[];seen=set();cur=g.id
        while cur in parents and cur not in resolved:
            if cur in seen:raise ValueError('cyclic ancestry')
            seen.add(cur);chain.append(cur);cur=parents[cur]
        founder=resolved.get(cur,cur if cur in known else None)
        for child in chain:resolved[child]=founder
        families[str(g.id)]=founder
    return {'ids':[g.id for g in pop],'clusters':labels.tolist(),'founders':families,
            'cluster_note':'Descriptive genetic partitions, not confirmed biological species',
            'genetic_distances':[[float(np.sqrt(np.mean((a-b)**2))) for b in genes] for a in genes]}

def run_metrics(store,eid):
    exp=store.experiment(eid);events=store.query('SELECT time,kind FROM events WHERE experiment_id=? ORDER BY id',(eid,))
    seconds=0;start=None
    for event in events:
        if event['kind']=='running':start=event['time']
        elif event['kind'] in ('paused','completed','cancelled','failed','recovery') and start is not None:
            seconds+=event['time']-start;start=None
    if start is not None and exp['status'] in ('running','pausing','cancelling'):seconds+=time.time()-start
    checkpoint=store.query('SELECT generation,created FROM checkpoints WHERE experiment_id=? ORDER BY generation DESC LIMIT 1',(eid,))
    return {'elapsed_active_seconds':seconds,'generations_per_second':exp['generation']/seconds if seconds else None,
            'eta_seconds':seconds/exp['generation']*(exp['config']['generations']-exp['generation']) if exp['generation'] else None,
            'unique_genomes':store.query('SELECT COUNT(DISTINCT fingerprint) AS n FROM genomes WHERE experiment_id=?',(eid,))[0]['n'],
            'identities':store.query('SELECT COUNT(*) AS n FROM genomes WHERE experiment_id=?',(eid,))[0]['n'],
            'checkpoint':checkpoint[0] if checkpoint else None}

def export_result(store,eid,kind='summary',generation=None):
    exp=store.experiment(eid)
    if kind=='statistics':
        rows=store.stats(eid,limit=1000000);out=io.StringIO()
        if rows:
            writer=csv.DictWriter(out,fieldnames=rows[0].keys());writer.writeheader();writer.writerows(rows)
        return out.getvalue().encode(),'text/csv','statistics.csv'
    if kind=='config':value=exp['config']
    elif kind=='summary':value={'experiment':exp,'statistics':store.stats(eid,limit=1000000),'events':store.query('SELECT time,kind,message FROM events WHERE experiment_id=? ORDER BY id',(eid,))}
    elif kind in ('population','champion'):
        generation=exp['generation']-1 if generation is None else generation
        pop=store.population(eid,generation)
        if not pop:raise ValueError('snapshot not retained')
        if kind=='champion':
            stats=store.stats(eid,generation,1);pop=[store.genome(eid,stats[0]['champion_id'])]
        value={'experiment_id':eid,'generation':generation,'networks':[g.record() for g in pop],
               'fitness':store.query('SELECT network_id,total,self_play,bot,matches,wins,losses,draws,components FROM fitness WHERE experiment_id=? AND generation=?',(eid,generation))}
    elif kind=='analysis':
        value=population_analysis(store,eid,exp['generation']-1 if generation is None else generation)
    else:raise ValueError('unknown export kind')
    return json.dumps(value,indent=2,allow_nan=False).encode(),'application/json',kind+'.json'

def save_tournament(store,result):
    with store.transaction() as db:
        cursor=db.execute('INSERT INTO analyses(created,kind,result) VALUES(?,?,?)',(time.time(),'tournament',encode(result)))
        return cursor.lastrowid

def compress_export(data,mime,name):
    return gzip.compress(data,mtime=0),'application/gzip',name+'.gz'
