"""Detached local scheduler with bounded retries and per-experiment process locks."""
import fcntl
import os
import subprocess
import sys
import time
import numpy as np
from .config import Config
from .storage import Store
from .runner import exclusive

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
    for c in planned:ids.append(store.create(c,'queued'))
    return ids

def handle_failure(store,eid,reason):
    with store.transaction() as db:
        row=db.execute('SELECT * FROM experiments WHERE id=?',(eid,)).fetchone()
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
            slots=max(0,settings['max_workers']-count)
            queued=store.query("SELECT id FROM experiments WHERE status='queued' ORDER BY priority DESC,created LIMIT ?",(slots,))
            for row in queued:
                eid=row['id']
                if eid in children or worker_active(store.root,eid):continue
                env=os.environ.copy()
                for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS'):env[key]='1'
                with (store.root/f'{eid}.log').open('ab') as log:
                    children[eid]=subprocess.Popen([sys.executable,'-m','evolution_engine','--data',str(store.root),'worker',eid],stdout=log,stderr=log,env=env)
            if until_idle and not children and not active and not store.query("SELECT 1 FROM experiments WHERE status='queued' LIMIT 1"):return
            time.sleep(min(settings['poll_seconds'],1))

def ensure_scheduler(root):
    store=Store(root)
    try:
        with exclusive(store.root/'manager.lock'):pass
    except RuntimeError:return False
    with (store.root/'manager.log').open('ab') as log:
        subprocess.Popen([sys.executable,'-m','evolution_engine','--data',str(store.root),'manager'],stdout=log,stderr=log,start_new_session=True)
    return True
