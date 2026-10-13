"""Research annotations live outside scientific configuration and RNG state."""
import json
import secrets
import time
import uuid
from .config import Config
from . import __version__
from .storage import encode

NOTE_FIELDS = ('description','hypothesis','expected_outcome','observations','conclusions','follow_up','freeform')
RETENTION_PRESETS = {
    'detailed': {'history_stride':1,'checkpoint_frequency':10,'checkpoint_retention':100},
    'balanced': {'history_stride':10,'checkpoint_frequency':50,'checkpoint_retention':20},
    'compact': {'history_stride':100,'checkpoint_frequency':100,'checkpoint_retention':5},
}

def notes(store, eid):
    store.experiment(eid)
    rows=store.query('SELECT * FROM notes WHERE experiment_id=?',(eid,))
    if not rows:return {'content':dict.fromkeys(NOTE_FIELDS,''),'created':None,'updated':None}
    return {**rows[0],'content':json.loads(rows[0]['content'])}

def save_notes(store,eid,content):
    if set(content)-set(NOTE_FIELDS) or any(not isinstance(v,str) or len(v)>16000 for v in content.values()):
        raise ValueError('invalid note field or content length')
    with store.transaction() as db:
        if not db.execute('SELECT 1 FROM experiments WHERE id=?',(eid,)).fetchone():raise KeyError(eid)
        current=db.execute('SELECT content FROM notes WHERE experiment_id=?',(eid,)).fetchone()
        merged={**dict.fromkeys(NOTE_FIELDS,''),**(json.loads(current[0]) if current else {}),**content}
        now=time.time()
        db.execute('INSERT INTO notes VALUES(?,?,?,?) ON CONFLICT(experiment_id) DO UPDATE SET content=excluded.content,updated=excluded.updated',(eid,encode(merged),now,now))
    return notes(store,eid)

def validate_tags(tags):
    if len(tags)>30:raise ValueError('at most 30 tags')
    if any(not isinstance(t,str) or not t.strip() or len(t)>60 for t in tags):raise ValueError('tags must contain 1–60 characters')
    return sorted(set(t.strip() for t in tags))

def require_ids(db,ids):
    if not ids or len(ids)>200 or len(set(ids))!=len(ids):raise ValueError('select 1–200 distinct experiments')
    for eid in ids:
        if not db.execute('SELECT 1 FROM experiments WHERE id=?',(eid,)).fetchone():raise KeyError(eid)

def tag_experiments(store,ids,add=(),remove=(),group=None):
    add,remove=validate_tags(add),validate_tags(remove)
    if group is not None and (not isinstance(group,str) or len(group)>120):raise ValueError('invalid research project')
    with store.transaction() as db:
        require_ids(db,ids)
        for tag in add:db.execute('INSERT OR IGNORE INTO tags VALUES(?)',(tag,))
        for eid in ids:
            for tag in add:db.execute('INSERT OR IGNORE INTO experiment_tags VALUES(?,?)',(eid,tag))
            for tag in remove:db.execute('DELETE FROM experiment_tags WHERE experiment_id=? AND tag=?',(eid,tag))
            if group is not None:db.execute('INSERT OR REPLACE INTO research_groups VALUES(?,?)',(eid,group))
    return {'updated':ids,'atomic':True}

def repeat(store,eid,seed_mode='same',start=False,preset=None):
    if seed_mode not in ('same','fresh'):raise ValueError('unknown seed mode')
    original=store.experiment(eid);raw=original['config'];raw['experiment_id']=None;raw['replicates']=1
    raw['name']=(raw['name'][:100]+' · repeat')
    if seed_mode=='fresh':
        old=raw['seed'];raw['seed']=secrets.randbelow(2**63)
        while raw['seed']==old:raw['seed']=secrets.randbelow(2**63)
    if preset:
        if preset not in RETENTION_PRESETS:raise ValueError('unknown retention preset')
        raw['execution'].update(RETENTION_PRESETS[preset])
    # Outer transaction is not used around Store.create: each operation below must
    # be atomic with provenance, so insert the validated row explicitly here.
    config=Config.model_validate(raw);new=uuid.uuid4().hex[:12];config.experiment_id=new;now=time.time()
    with store.transaction() as db:
        db.execute('INSERT INTO experiments(id,name,config,status,created,updated,priority,engine_version,origin) VALUES(?,?,?,?,?,?,?,?,?)',
                   (new,config.name,encode(config.model_dump()),'queued' if start else 'created',now,now,config.execution.priority,__version__,encode({'repeated_from':eid,'seed_mode':seed_mode})))
        db.execute('INSERT INTO repetitions VALUES(?,?,?,?)',(new,eid,seed_mode,now))
        store.event(db,new,'created',f'Repeated {eid}; {seed_mode} seed {config.seed}')
    return {'id':new,'seed_text':str(config.seed),'source_id':eid}

def save_bookmark(store,body,bid=None):
    kind=body['kind'];ref=body.get('reference',{});eid=body.get('experiment_id')
    allowed={'experiment','generation','network','champion','branch','tournament','event'}
    if kind not in allowed:raise ValueError('unknown bookmark kind')
    if not body.get('name') or len(body['name'])>200 or len(body.get('notes',''))>16000:raise ValueError('invalid bookmark text')
    tags=validate_tags(body.get('tags',[]))
    with store.transaction() as db:
        if eid and not db.execute('SELECT 1 FROM experiments WHERE id=?',(eid,)).fetchone():raise KeyError(eid)
        if kind in ('network','champion','branch'):
            if not db.execute('SELECT 1 FROM genomes WHERE experiment_id=? AND id=?',(eid,ref.get('network_id'))).fetchone():raise KeyError('network')
        elif kind=='generation':
            if not db.execute('SELECT 1 FROM generations WHERE experiment_id=? AND generation=?',(eid,ref.get('generation'))).fetchone():raise KeyError('recorded generation')
        elif kind=='tournament':
            if not db.execute('SELECT 1 FROM analyses WHERE id=?',(ref.get('analysis_id'),)).fetchone():raise KeyError('tournament')
        elif kind=='event':
            if not db.execute('SELECT 1 FROM events WHERE experiment_id=? AND id=?',(eid,ref.get('event_id'))).fetchone():raise KeyError('event')
        elif not eid:raise ValueError('experiment reference required')
        now=time.time()
        values=(eid,kind,encode(ref),body['name'],body.get('notes',''),encode(tags),now)
        if bid is None:
            bid=db.execute('INSERT INTO bookmarks(experiment_id,kind,reference,name,notes,tags,updated,created) VALUES(?,?,?,?,?,?,?,?)',(*values,now)).lastrowid
        else:
            if not db.execute('UPDATE bookmarks SET experiment_id=?,kind=?,reference=?,name=?,notes=?,tags=?,updated=? WHERE id=?',(*values,bid)).rowcount:raise KeyError(bid)
    return {'id':bid}

def baskets(store):
    rows=store.query('SELECT * FROM baskets ORDER BY updated DESC LIMIT 200')
    for row in rows:
        row['entrants']=json.loads(row['entrants'])
        for entrant in row['entrants']:
            entrant['available']=bool(store.query('SELECT 1 FROM genomes WHERE experiment_id=? AND id=?',(entrant['experiment_id'],entrant['network_id'])))
    return rows

def save_basket(store,bid,name,entrants):
    if not name or len(name)>120 or len(entrants)>100:raise ValueError('invalid basket size or name')
    refs=[(e['experiment_id'],e['network_id']) for e in entrants]
    if len(set(refs))!=len(refs):raise ValueError('duplicate basket entrants')
    now=time.time()
    with store.transaction() as db:
        db.execute('INSERT INTO baskets VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,entrants=excluded.entrants,updated=excluded.updated',(bid,name,encode(entrants),now,now))
    return {'id':bid}

def config_diff(store,a,b):
    def flatten(value,prefix=''):
        result={}
        for key,val in value.items():
            path=f'{prefix}.{key}' if prefix else key
            if isinstance(val,dict):result.update(flatten(val,path))
            else:result[path]=str(val) if path=='seed' else val
        return result
    left,right=flatten(store.experiment(a)['config']),flatten(store.experiment(b)['config'])
    operational=('execution.','storage.','name','description','experiment_id','replicates','generations')
    return {'a':a,'b':b,'fields':[{'path':key,'a':left.get(key),'b':right.get(key),'different':left.get(key)!=right.get(key),'category':'operational' if key.startswith(operational) else 'scientific'} for key in sorted(left.keys()|right.keys())]}
