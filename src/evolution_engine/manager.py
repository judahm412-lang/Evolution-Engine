"""Detached local scheduler with bounded retries and per-experiment process locks."""
import fcntl
import os
import subprocess
import sys
import time
import json
import uuid
import numpy as np
from .config import Config
from .storage import Store,encode
from .runner import exclusive
from .coordination import gate, MaintenanceBusy
from .resources import disk_guard

def worker_active(root,eid):
    try:
        with exclusive(root/f'{eid}.lock'):return False
    except RuntimeError:return True

def enqueue(store,config,sweep=None):
    ids=[]
    values=sweep if sweep is not None else [config.environment.bot_weight]
    # Configuration validation precedes all writes.
    planned=[]
    for value in values:
        seeds=[config.seed] if config.replicates==1 else [int(s.generate_state(1,dtype=np.uint64)[0]%(2**63)) for s in np.random.SeedSequence(config.seed).spawn(config.replicates)]
        for i,seed in enumerate(seeds):
            raw=config.model_dump();raw['seed']=seed;raw['replicates']=1;raw['environment']['bot_weight']=value
            if len(values)>1 or len(seeds)>1:
                raw['experiment_id']=None;raw['name']=f'{config.name} · w={value:g} · replicate {i+1}'
            planned.append(Config.model_validate(raw))
    batch=uuid.uuid4().hex
    for index,c in enumerate(planned):ids.append(store.create(c,'queued',encode({'batch':batch,'worker_limit':config.execution.workers,'root_seed':config.seed,'replicate_index':index%config.replicates,'seed_derivation':'NumPy SeedSequence.spawn; PCG64 substreams'})))
    return ids

def handle_failure(store,eid,reason):
    with store.transaction() as db:
        row=db.execute('SELECT * FROM experiments WHERE id=?',(eid,)).fetchone()
        if row is None:return
        if row['status'] in ('pausing','cancelling'):
            new='paused' if row['status']=='pausing' else 'cancelled'
        elif row['attempts']<Config.model_validate_json(row['config']).execution.retries:
            new='queued'
        else:new='failed'
        db.execute('UPDATE experiments SET status=?,attempts=attempts+1,pid=NULL,error=?,updated=? WHERE id=?',(new,reason,time.time(),eid))
        store.event(db,eid,'recovery',f'{reason}; next state {new}')

def scheduler(root,until_idle=False):
    store=Store(root)
    with exclusive(store.root/'manager.lock'):
        children={}
        while True:
            settings=store.settings()
            try:
                with gate(store.root):
                    for eid,proc in list(children.items()):
                        code=proc.poll()
                        if code is not None:
                            del children[eid]
                            if code!=0:handle_failure(store,eid,f'worker exited with code {code}')
                    # Lock-based liveness also discovers children of a previous scheduler.
                    active=[]
                    for r in store.query("SELECT id,status FROM experiments WHERE status IN ('running','pausing','cancelling')"):
                        if worker_active(store.root,r['id']):active.append(r['id'])
                        elif r['id'] not in children:handle_failure(store,r['id'],'worker disappeared before a safe boundary')
                    settings=store.settings();count=len(set(active)|set(children))
                    disk=disk_guard(store)
                    slots=0 if disk['block_scheduling'] else max(0,settings['max_workers']-count)
                    groups={}
                    for eid in set(active)|set(children):
                        rows=store.query('SELECT origin FROM experiments WHERE id=?',(eid,))
                        if not rows:continue
                        origin=rows[0]['origin']
                        if origin and origin.startswith('{'):
                            group=json.loads(origin).get('batch');groups[group]=groups.get(group,0)+1
                    queued=store.query("SELECT id,origin FROM experiments WHERE status='queued' ORDER BY priority DESC,created")
                    for row in queued:
                        if slots<=0:break
                        eid=row['id']
                        if eid in children or worker_active(store.root,eid):continue
                        group=None
                        if row['origin'] and row['origin'].startswith('{'):
                            origin=json.loads(row['origin']);group=origin.get('batch')
                            if group and groups.get(group,0)>=origin.get('worker_limit',settings['max_workers']):continue
                        env=os.environ.copy()
                        for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS'):env[key]='1'
                        with (store.root/f'{eid}.log').open('ab') as log:
                            children[eid]=subprocess.Popen([sys.executable,'-m','evolution_engine','--data',str(store.root),'worker',eid],stdout=log,stderr=log,env=env)
                        slots-=1
                        if group:groups[group]=groups.get(group,0)+1
                    if until_idle and not children and not active and not store.query("SELECT 1 FROM experiments WHERE status='queued' LIMIT 1"):return
            except MaintenanceBusy:
                pass
            time.sleep(min(settings['poll_seconds'],1))

def ensure_scheduler(root):
    store=Store(root)
    try:
        with exclusive(store.root/'manager.lock'):pass
    except RuntimeError:return False
    with (store.root/'manager.log').open('ab') as log:
        subprocess.Popen([sys.executable,'-m','evolution_engine','--data',str(store.root),'manager'],stdout=log,stderr=log,start_new_session=True)
    return True
