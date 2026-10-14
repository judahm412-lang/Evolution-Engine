"""Read-only history views and explicitly derived descriptive milestones."""
import json
import math
import time
from .storage import encode

METRICS=('mean','maximum','minimum','self_mean','bot_mean','genetic_rms','behavioral_hamming','mutation_mean','unique_policies')

def chart_data(store,eid,start=0,end=None,metrics=('mean','maximum'),points=800):
    exp=store.experiment(eid);end=max(0,exp['generation']-1) if end is None else end
    if start<0 or end<start or not 50<=points<=2000 or not metrics or len(metrics)>9 or any(m not in METRICS for m in metrics):raise ValueError('invalid chart range, metric or point limit')
    db=store.connect()
    try:
        count=db.execute('SELECT COUNT(*) FROM generations WHERE experiment_id=? AND generation BETWEEN ? AND ?',(eid,start,end)).fetchone()[0]
        buckets=max(1,points//(2*len(metrics)+2));width=max(1,math.ceil((end-start+1)/buckets))
        chosen={};bucket=None;extremes={};first=last=None
        def emit():
            for row in [first,last,*extremes.values()]:
                if row:chosen[row['generation']]=row
        for raw in db.execute('SELECT generation,statistics FROM generations WHERE experiment_id=? AND generation BETWEEN ? AND ? ORDER BY generation',(eid,start,end)):
            values=json.loads(raw['statistics']);row={'generation':raw['generation'],**{m:values.get(m) for m in metrics}}
            if count<=points:chosen[row['generation']]=row;continue
            index=(row['generation']-start)//width
            if index!=bucket:
                emit();bucket=index;first=row;extremes={}
            last=row
            for metric in metrics:
                val=row.get(metric)
                if val is None:continue
                for direction in ('min','max'):
                    key=(metric,direction);old=extremes.get(key)
                    if old is None or (val<old[metric] if direction=='min' else val>old[metric]):extremes[key]=row
        if count>points:emit()
    finally:db.close()
    marks=store.query('SELECT id,generation,kind,status,notes FROM milestones WHERE experiment_id=? AND generation BETWEEN ? AND ? AND status!=? ORDER BY generation LIMIT 200',(eid,start,end,'dismissed'))
    bookmarks=store.query("SELECT id,name,reference FROM bookmarks WHERE experiment_id=? AND CAST(json_extract(reference,'$.generation') AS INTEGER) BETWEEN ? AND ? ORDER BY id LIMIT 200",(eid,start,end))
    for b in bookmarks:b['reference']=json.loads(b['reference'])
    return {'experiment_id':eid,'range':[start,end],'metrics':metrics,'raw_count':count,'plotted_count':len(chosen),'downsampled':count>points,
            'method':'First, last and per-metric min/max within generation buckets; actual observations, no interpolation or smoothing.',
            'rows':[chosen[g] for g in sorted(chosen)],'milestones':marks,'bookmarks':bookmarks,'annotation_limit':200}

def replay_frame(store,eid,generation):
    store.experiment(eid)
    rows=store.stats(eid,generation,1)
    if not rows or rows[0]['generation']!=generation:raise KeyError('No recorded aggregate statistics at this generation')
    stats=rows[0]
    count=store.query('SELECT COUNT(*) n FROM populations WHERE experiment_id=? AND generation=?',(eid,generation))[0]['n']
    sample=store.query('SELECT p.network_id,p.slot,f.total FROM populations p LEFT JOIN fitness f ON f.experiment_id=p.experiment_id AND f.generation=p.generation AND f.network_id=p.network_id WHERE p.experiment_id=? AND p.generation=? ORDER BY f.total DESC,p.slot LIMIT 100',(eid,generation))
    champion=stats.get('champion_id');graph=None
    if champion:
        from .lab_queries import family_graph
        graph=family_graph(store,eid,champion,depth=6,limit=50,generation_max=generation)
    return {'generation':generation,'statistics':stats,'snapshot_retained':bool(count),'population_count':count,'population':sample,'population_limit':100,'family':graph,
            'notice':'Playback of saved observations. No new simulation, interpolation or reconstructed population. Ancestor colors and founder labels reflect only stored edges.'}

def timeline(store,eid,offset=0,limit=50,kind=''):
    store.experiment(eid)
    if offset<0 or not 1<=limit<=200:raise ValueError('invalid timeline bounds')
    # Checkpoint timestamps are stored facts; older pruned checkpoints have no
    # invented event here. Bookmark and milestone timestamps are annotation dates.
    sql="""WITH timeline AS (
      SELECT 'event:'||id AS key,time,kind,message AS description,NULL AS generation,NULL AS network_id,'recorded event' AS provenance FROM events WHERE experiment_id=?
      UNION ALL SELECT 'checkpoint:'||generation,created,'checkpoint','Retained checkpoint',generation,NULL,'recorded checkpoint' FROM checkpoints WHERE experiment_id=?
      UNION ALL SELECT 'bookmark:'||id,created,'bookmark',name,CAST(json_extract(reference,'$.generation') AS INTEGER),CAST(json_extract(reference,'$.network_id') AS INTEGER),'user annotation' FROM bookmarks WHERE experiment_id=?
      UNION ALL SELECT 'milestone:'||id,created,'milestone',kind||' ('||status||')',generation,NULL,'derived descriptive observation' FROM milestones WHERE experiment_id=?
    ) SELECT * FROM timeline WHERE (?='' OR kind=?) ORDER BY time,key LIMIT ? OFFSET ?"""
    rows=store.query(sql,(eid,eid,eid,eid,kind,kind,limit+1,offset))
    return {'items':rows[:limit],'next_offset':offset+limit if len(rows)>limit else None,'ordering':'Chronological by recorded timestamp; detection dates do not pretend to be historical event times.'}

def detect_milestones(store,eid,config,progress=lambda p:None):
    exp=store.experiment(eid);best=None;prior=None;champion=None;streak=0;created=0;offset=0
    while rows:=store.stats(eid,offset,1000):
        candidates=[]
        for row in rows:
            gen=row['generation'];maximum=row.get('maximum');diversity=row.get('genetic_rms');mutation=row.get('mutation_mean')
            criteria=[]
            if maximum is not None:
                if best is None or maximum>best:
                    if config.get('record_high',True):criteria.append(('record_high',maximum))
                    best=maximum
                threshold=config.get('fitness_threshold')
                if threshold is not None and maximum>=threshold and (prior is None or prior.get('maximum',-math.inf)<threshold):criteria.append(('fitness_threshold',maximum))
                jump=config.get('fitness_increase')
                if jump is not None and prior and maximum-prior.get('maximum',maximum)>=jump:criteria.append(('fitness_increase',maximum-prior['maximum']))
            threshold=config.get('diversity_threshold')
            if threshold is not None and diversity is not None and diversity<=threshold and (prior is None or prior.get('genetic_rms',math.inf)>threshold):criteria.append(('low_diversity',diversity))
            change=config.get('mutation_change')
            if change is not None and prior and mutation is not None and prior.get('mutation_mean') is not None and abs(mutation-prior['mutation_mean'])>=change:criteria.append(('mutation_change',mutation-prior['mutation_mean']))
            if row.get('champion_id')==champion:streak+=1
            else:champion=row.get('champion_id');streak=1
            duration=config.get('champion_duration',20)
            if champion and streak==duration:criteria.append(('repeated_recorded_champion',float(streak)))
            for kind,value in criteria:
                provenance={'detector':'descriptive-v1','configuration':config,'observed_generation':gen,'source':'stored generation statistics','champion_id':champion,'limitation':'Descriptive association only; no causal interpretation. Consecutive observations may have gaps in imported history.'}
                candidates.append((eid,gen,kind,value,encode(provenance),time.time()))
            prior=row
        with store.transaction() as db:
            for values in candidates:
                cursor=db.execute('INSERT OR IGNORE INTO milestones(experiment_id,generation,kind,value,provenance,created) VALUES(?,?,?,?,?,?)',values);created+=cursor.rowcount
        offset=rows[-1]['generation']+1;progress(min(.95,offset/max(1,exp['generation'])))
    if exp['status']=='completed':
        with store.transaction() as db:
            db.execute('INSERT OR IGNORE INTO milestones(experiment_id,generation,kind,value,provenance,created) VALUES(?,?,?,?,?,?)',(eid,max(0,exp['generation']-1),'completion',exp['generation'],encode({'detector':'descriptive-v1','configuration':config,'source':'persisted experiment completion state'}),time.time()))
    return {'experiment_id':eid,'new_candidates':created,'configuration':config,'interpretation':'Descriptive candidates for review, not causal discoveries.'}
