import ast
import gzip
import hashlib
import json
import random
import sqlite3
import pytest
from pathlib import Path
import numpy as np
from fastapi.testclient import TestClient
from evolution_engine import generalization
from evolution_engine.api import create_app
from evolution_engine.neural import Genome
from evolution_engine.research import tournament
from evolution_engine.runner import run_experiment
from evolution_engine.rps_core import HINDEX, NEXT, score
from evolution_engine.manager import enqueue, handle_failure
from evolution_engine.storage import Store, historical_connection
from test_core import ROOT, small


def test_frozen_source_fixtures():
    fixture=json.loads((Path(__file__).parent/'fixtures/sb3_inference.json').read_text())
    assert hashlib.sha256((ROOT/'engineV1.sb3').read_bytes()).hexdigest()==fixture['source_sha256']
    for record in fixture['networks']:
        g=Genome(**record['genome'])
        hidden=Genome(1,(9,12),('sigmoid',),np.concatenate([g.parameters[:108],g.parameters[144:156]]))
        for case in record['cases']:
            np.testing.assert_allclose(hidden.forward(case['input'],True),case['hidden'],rtol=1e-12,atol=1e-12)
            out=g.forward(case['input'],True)
            np.testing.assert_allclose(out,case['output'],rtol=1e-12,atol=1e-12)
            assert np.argmax(out)+1==case['move']


def test_unfamiliar_opponents_against_frozen_e8():
    tree=ast.parse((ROOT/'experiment_08/src/generalization.py').read_text())
    functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('counter','bot_move','play')]
    reference={'random':random,'HINDEX':HINDEX,'NEXT':NEXT,'score':score}
    exec(compile(ast.Module(body=functions,type_ignores=[]),'frozen_e8','exec'),reference)
    policy=np.random.default_rng(42).integers(1,4,40)
    for opponent in generalization.OPPONENTS:
        for seed in (4,5):
            for start in ((0,0,0),(1,2,3)):
                actual=generalization.play(policy,opponent,seed,start,75)
                assert actual==reference['play'](policy,opponent,seed,start,75)
                assert sum(actual[1:])==75 and actual[0]==actual[1]-actual[2]


def test_research_settings_filters_exports(tmp_path):
    client=TestClient(create_app(tmp_path));s=client.app.state.store
    eid=s.create(small());run_experiment(tmp_path,eid)
    headers={'X-Evolution-Client':'dashboard'}
    settings=client.get('/api/settings').json();settings.pop('storage_root')
    settings.update(max_workers=3,dashboard_refresh=2)
    assert client.put('/api/settings',headers=headers,json=settings).status_code==200
    assert s.settings()['max_workers']==3
    assert client.get('/api/experiments?status=completed&environment=rps&min_generation=4').json()['total']==1
    assert client.get('/api/experiments?min_generation=5').json()['total']==0
    info=client.get('/api/experiments/'+eid).json()
    assert info['metrics']['elapsed_active_seconds']>0
    pop=s.population(eid,3)
    entrants=[{'experiment_id':eid,'network_id':g.id} for g in pop[:3]]
    request={'entrants':entrants,'rounds':37,'repeats':3,'opponents':['uniform','reactive','cycle'],'seed':73}
    result=client.post('/api/tournaments',headers=headers,json=request).json()
    assert len(result['independent_trials'])==6
    again=client.post('/api/tournaments',headers=headers,json=request).json()
    assert result['independent_trials']==again['independent_trials']
    assert result['net_matrix']==again['net_matrix']
    assert client.get('/api/tournaments/'+str(result['analysis_id'])).json()['entrants']==entrants
    downloaded=client.get('/api/tournaments/'+str(result['analysis_id'])+'/export')
    assert 'attachment' in downloaded.headers['content-disposition']
    assert downloaded.json()['net_matrix']==result['net_matrix']
    export=client.get(f'/api/experiments/{eid}/export/population?compressed=true')
    assert len(json.loads(gzip.decompress(export.content))['fitness'])==10
    assert client.post('/api/tournaments',headers=headers,json={**request,'opponents':['unknown']}).status_code==422


def test_bounded_failure_and_batch_provenance(tmp_path):
    s=Store(tmp_path);ids=enqueue(s,small(replicates=3,execution={'workers':1,'retries':1}))
    origins=[json.loads(s.experiment(eid)['origin']) for eid in ids]
    assert len({o['batch'] for o in origins})==1
    assert all(o['worker_limit']==1 for o in origins)
    handle_failure(s,ids[0],'injected interruption')
    assert s.experiment(ids[0])['status']=='queued'
    handle_failure(s,ids[0],'injected interruption')
    assert s.experiment(ids[0])['status']=='failed'
    assert s.experiment(ids[0])['attempts']==2


def test_historical_access_never_creates_sidecars(tmp_path):
    path=tmp_path/'frozen.sqlite'
    db=sqlite3.connect(path);db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE sample(value INTEGER)');db.commit()
    with pytest.raises(ValueError,match='pending WAL'):historical_connection(path)
    db.close()
    with historical_connection(path) as reader:
        assert reader.execute('SELECT COUNT(*) FROM sample').fetchone()[0]==0
    assert not Path(str(path)+'-wal').exists()
    assert not Path(str(path)+'-shm').exists()
