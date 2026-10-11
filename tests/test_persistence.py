import json
import sqlite3
import numpy as np
import pytest
from evolution_engine.config import Config
from evolution_engine.storage import Store
from evolution_engine.runner import run_experiment
from evolution_engine.research import export_result,inspect,tournament,lineage
from evolution_engine.importers import import_archive,import_experiment8
from test_core import small,ROOT

def histories(store,eid):
    return store.query('SELECT generation,network_id,total,self_play,bot,matches,wins,losses,draws FROM fitness WHERE experiment_id=? ORDER BY generation,network_id',(eid,))

def genomes(store,eid):
    return store.query('SELECT id,genes,metadata,fingerprint FROM genomes WHERE experiment_id=? ORDER BY id',(eid,))

def test_resume_exact_equivalence(tmp_path):
    s=Store(tmp_path);c=small(generations=8);a=s.create(c);b=s.create(c)
    run_experiment(tmp_path,a);run_experiment(tmp_path,b,stop_after=3)
    assert s.experiment(b)['status']=='paused' and s.experiment(b)['generation']==3
    run_experiment(tmp_path,b)
    assert histories(s,a)==histories(s,b)
    assert genomes(s,a)==genomes(s,b)
    assert s.checkpoint(a)['rng']==s.checkpoint(b)['rng']
    assert s.integrity()['foreign_keys']==[]
    assert s.integrity()['integrity'][0]['integrity_check']=='ok'

@pytest.mark.parametrize('stage',['before_checkpoint','before_commit'])
def test_transaction_failure(tmp_path,stage):
    s=Store(tmp_path);a=s.create(small());b=s.create(small());run_experiment(tmp_path,a)
    def fault(at):
        if at==stage:raise OSError('simulated disk error')
    with pytest.raises(OSError):run_experiment(tmp_path,b,fault=fault)
    assert s.experiment(b)['generation']==0 and not histories(s,b)
    assert s.experiment(b)['status']=='failed'
    run_experiment(tmp_path,b)
    assert histories(s,a)==histories(s,b) and genomes(s,a)==genomes(s,b)

def test_corrupt_checkpoint(tmp_path):
    s=Store(tmp_path);eid=s.create(small());run_experiment(tmp_path,eid,stop_after=1)
    with s.transaction() as db:db.execute("UPDATE checkpoints SET checksum='bad' WHERE experiment_id=?",(eid,))
    with pytest.raises(ValueError,match='corrupt'):run_experiment(tmp_path,eid)

def test_extend_and_exports(tmp_path):
    s=Store(tmp_path);eid=s.create(small(generations=2));run_experiment(tmp_path,eid)
    s.command(eid,'resume',4);run_experiment(tmp_path,eid)
    assert s.experiment(eid)['generation']==4
    for kind in ('summary','statistics','config','population','champion','analysis'):
        data,mime,name=export_result(s,eid,kind);assert data and name
    g=s.population(eid,3)[0];detail=inspect(s,eid,g.id,[0]*9);assert len(detail['policy'])==40
    assert lineage(s,eid,g.id)['nodes'][0]['id']==g.id
    result=tournament(s.population(eid,3));m=np.array(result['net_matrix']);assert np.array_equal(m,-m.T)

def test_import_export_json(tmp_path):
    s=Store(tmp_path);eid=s.create(small());run_experiment(tmp_path,eid)
    content,_,_=export_result(s,eid,'population');p=tmp_path/'population.json';p.write_bytes(content)
    imported=import_archive(s,p,'round trip')['experiment_id']
    assert [g.fingerprint for g in s.population(eid,3)]==[g.fingerprint for g in s.population(imported,3)]

def test_e8_readonly_references(tmp_path):
    source=ROOT/'experiment_08/results/networks.sqlite';s=Store(tmp_path)
    eid=import_experiment8(s,source,'A',[0])
    rows=s.query('SELECT genes,external FROM genomes WHERE experiment_id=?',(eid,))
    assert len(rows)==100 and all(r['genes'] is None and r['external'] for r in rows)
    p=s.population(eid,0);assert len(p)==100
    assert len(tournament(p[:8])['ranking'])==8

def test_migrations(tmp_path):
    s=Store(tmp_path)
    with s.transaction() as db:db.execute('DROP TABLE analyses');db.execute('PRAGMA user_version=1')
    Store(tmp_path);assert s.query('SELECT * FROM analyses')==[]
    with s.transaction() as db:db.execute('PRAGMA user_version=999')
    with pytest.raises(ValueError,match='newer'):Store(tmp_path)

def test_40_generation_compatibility(tmp_path):
    s=Store(tmp_path);eid=s.create(Config(generations=40))
    result=run_experiment(tmp_path,eid)
    assert result['status']=='completed' and result['generation']==40
    assert len(histories(s,eid))==4000
    assert len(genomes(s,eid))==3300
