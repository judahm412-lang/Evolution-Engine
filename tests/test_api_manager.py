import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import numpy as np
import pytest
from fastapi.testclient import TestClient
from evolution_engine.api import create_app
from evolution_engine.config import Config
from evolution_engine.storage import Store
from evolution_engine.manager import enqueue
from evolution_engine.runner import run_experiment
from test_core import small
from test_persistence import genomes,histories

HEAD={'X-Evolution-Client':'dashboard'}
def wait_for(fn,timeout=20):
    start=time.monotonic()
    while time.monotonic()-start<timeout:
        result=fn()
        if result:return result
        time.sleep(.03)
    raise AssertionError('timed out waiting for condition')

def manager(root,workers=2):
    return subprocess.Popen([sys.executable,'-m','evolution_engine','--data',str(root),'manager','--until-idle','--workers',str(workers)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)

def test_api_end_to_end(tmp_path):
    app=create_app(tmp_path);client=TestClient(app);s=app.state.store
    assert client.get('/').status_code==200
    assert client.post('/api/experiments',json=small().model_dump()).status_code==403
    assert client.post('/api/experiments',headers={**HEAD,'Origin':'https://evil.example'},json=small().model_dump()).status_code==403
    assert client.get('/api/system',headers={'Host':'evil.example'}).status_code==403
    assert client.post('/api/experiments',headers=HEAD,json={'population':{'size':99}}).status_code==422
    r=client.post('/api/experiments',headers=HEAD,json=small(generations=20).model_dump());assert r.status_code==200
    eid=r.json()['id'];client.post(f'/api/experiments/{eid}/control',headers=HEAD,json={'action':'start'})
    proc=manager(tmp_path);out,err=proc.communicate(timeout=30);assert proc.returncode==0,err.decode()
    e=client.get(f'/api/experiments/{eid}').json();assert e['status']=='completed'
    assert len(client.get(f'/api/experiments/{eid}/stats').json())==20
    pop=client.get(f'/api/experiments/{eid}/population/19').json();nid=pop[0]['network_id']
    for path in (f'/genomes/{nid}',f'/genomes/{nid}/lineage','/analysis/19','/checkpoints','/events','/export/statistics','/export/population'):
        assert client.get(f'/api/experiments/{eid}'+path).status_code==200
    r=client.post('/api/tournaments',headers=HEAD,json={'entrants':[{'experiment_id':eid,'network_id':p['network_id']} for p in pop[:4]]})
    assert r.status_code==200
    matrix=np.array(r.json()['net_matrix']);assert np.array_equal(matrix,-matrix.T)
    restarted=TestClient(create_app(tmp_path));assert restarted.get(f'/api/experiments/{eid}').json()['generation']==20
    assert restarted.get('/api/tournaments').json()

def test_parallel_reproducibility(tmp_path):
    s=Store(tmp_path);c=small(generations=12);a=s.create(c);run_experiment(tmp_path,a)
    ids=[s.create(c,'queued') for _ in range(4)]
    p=manager(tmp_path,2);out,err=p.communicate(timeout=30);assert p.returncode==0,err.decode()
    for eid in ids:
        assert s.experiment(eid)['status']=='completed'
        assert genomes(s,a)==genomes(s,eid) and histories(s,a)==histories(s,eid)

def test_worker_crash_pause_and_recover(tmp_path):
    s=Store(tmp_path);c=Config(generations=200,execution={'acceleration':'numpy','retries':1});eid=s.create(c,'queued')
    p=manager(tmp_path,1)
    try:
        e=wait_for(lambda:(r if (r:=s.experiment(eid))['generation']>=1 and r['pid'] else None))
        os.kill(e['pid'],signal.SIGKILL)
        wait_for(lambda:s.experiment(eid)['attempts']==1)
        wait_for(lambda:s.experiment(eid)['status']=='running')
        s.command(eid,'pause');wait_for(lambda:s.experiment(eid)['status']=='paused')
        before=s.experiment(eid)['generation'];assert before>=1
        p.communicate(timeout=10)
        s.command(eid,'resume');p=manager(tmp_path,1)
        wait_for(lambda:s.experiment(eid)['generation']>before)
        s.command(eid,'cancel');wait_for(lambda:s.experiment(eid)['status']=='cancelled')
        p.communicate(timeout=10)
        assert s.integrity()['foreign_keys']==[]
    finally:
        if p.poll() is None:p.terminate();p.communicate(timeout=5)

def test_replicates_and_priority(tmp_path):
    s=Store(tmp_path);c=small(replicates=3)
    ids=enqueue(s,c,[0,.25]);assert len(ids)==6
    for weight in (0,.25):
        seeds=[s.experiment(eid)['config']['seed'] for eid in ids if s.experiment(eid)['config']['environment']['bot_weight']==weight]
        assert len(set(seeds))==3
    s.command(ids[0],'pause');s.command(ids[1],'cancel')
    assert s.experiment(ids[0])['status']=='paused' and s.experiment(ids[1])['status']=='cancelled'

def test_batch_worker_cap(tmp_path):
    s=Store(tmp_path)
    ids=enqueue(s,small(generations=8,replicates=3,execution={'workers':1}))
    p=manager(tmp_path,3);out,err=p.communicate(timeout=30)
    assert p.returncode==0,err.decode()
    intervals=[]
    for eid in ids:
        assert s.experiment(eid)['status']=='completed'
        events=s.query("SELECT time,kind FROM events WHERE experiment_id=? AND kind IN ('running','completed') ORDER BY id",(eid,))
        intervals.append((events[0]['time'],events[-1]['time']))
    intervals.sort()
    assert all(a[1]<=b[0] for a,b in zip(intervals,intervals[1:]))
