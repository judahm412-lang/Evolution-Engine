import gzip
import json
import numpy as np
import pytest
from evolution_engine.storage import Store
from evolution_engine.importers import import_archive
from evolution_engine.neural import Genome

def source(nid,parameters,fit=0,metadata=None):
    r=[nid,json.dumps(parameters[:144].tolist()),json.dumps(parameters[144:].tolist()),fit]
    if metadata is not None:r+=metadata
    return json.dumps(r)

def test_raw_elite_metadata_and_mutation_validation(tmp_path):
    p=np.zeros(159);q=p.copy();q[1]=.1;r=q.copy();r[2]=.2
    content=[json.dumps([0,0]),source(1,p,1,[0,0,0]),source(2,q,2,[0,1,1]),source(2,q,3),source(3,r,4,[0,5,2])]
    path=tmp_path/'archive.txt';path.write_text(json.dumps(content));before=path.read_bytes()
    s=Store(tmp_path/'runtime');result=import_archive(s,path,'archive',population_size=2)
    assert result['issues']==['3: recorded mutations 5, observed 1']
    assert s.genome(result['experiment_id'],2).parent_id==1
    assert len(s.genome(result['experiment_id'],3).mutations)==1
    assert path.read_bytes()==before

def test_conflicting_archive_rolls_back(tmp_path):
    p=np.zeros(159);q=p.copy();q[0]=1
    path=tmp_path/'bad.txt';path.write_text(json.dumps([source(1,p,0,[0,0,0]),source(1,q,0,[0,0,0])]))
    s=Store(tmp_path/'runtime')
    with pytest.raises(ValueError):import_archive(s,path,'bad',2)
    assert s.list()[0]['status']=='failed'
    assert not s.query('SELECT * FROM genomes')

def test_gzip_network_import(tmp_path):
    g=Genome(1,(2,1),('linear',),np.zeros(3));p=tmp_path/'networks.json.gz'
    p.write_bytes(gzip.compress(json.dumps({'networks':[g.record()]}).encode()))
    s=Store(tmp_path/'runtime');eid=import_archive(s,p,'compressed')['experiment_id']
    assert s.genome(eid,1).fingerprint==g.fingerprint
