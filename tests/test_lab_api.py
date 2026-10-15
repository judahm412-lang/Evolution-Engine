import json
import time
import numpy as np
import pytest
from fastapi.testclient import TestClient
from evolution_engine.api import create_app
from evolution_engine.runner import run_experiment
from evolution_engine.neural import Genome
from evolution_engine.lab_queries import family_graph,genetic_comparison
from evolution_engine.history_lab import chart_data
from evolution_engine.storage import encode
from test_core import small

H={'X-Evolution-Client':'dashboard'}

@pytest.fixture
def lab(tmp_path):
    client=TestClient(create_app(tmp_path));s=client.app.state.store
    eid=s.create(small(generations=8));run_experiment(tmp_path,eid)
    return client,s,eid

def wait_job(client,jid):
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        r=client.get('/api/lab/jobs/'+jid).json()
        if r['status'] not in ('queued','running'):return r
        time.sleep(.02)
    raise AssertionError('job timed out')

def test_notes_tags_search_repeat_exact_seed(lab):
    c,s,eid=lab
    assert c.put(f'/api/lab/experiments/{eid}/notes',json={'content':{'hypothesis':'x'}}).status_code==403
    r=c.put(f'/api/lab/experiments/{eid}/notes',headers=H,json={'content':{'hypothesis':'<script>search-me</script>'}});assert r.status_code==200
    assert c.put('/api/lab/tags',headers=H,json={'ids':[eid],'add':['alpha','beta'],'group':'project'}).status_code==200
    for query in ['q=search-me','tags=alpha&tags=beta','group=project','seed=42','min_fitness=-99999','sort=size','origin=native','q='+eid]:
        r=c.get('/api/lab/search?'+query);assert r.status_code==200,r.text
        assert r.json()['total']==1
    assert c.get('/api/lab/search?tags=alpha&tags=missing').json()['total']==0
    assert c.get('/api/lab/search?q=%27%20OR%201%3D1--').json()['total']==0
    raw=s.experiment(eid)['config'];raw.update(experiment_id=None,seed=str(2**63-1))
    r=c.post('/api/lab/experiments',headers=H,json={'config':raw,'preset':'compact'});assert r.status_code==200,r.text
    large=r.json()['id'];assert r.json()['seed_text']==str(2**63-1)
    again=c.post(f'/api/lab/experiments/{large}/repeat',headers=H,json={}).json()
    assert again['seed_text']==str(2**63-1)
    assert c.get('/api/lab/config-diff',params={'a':large,'b':again['id']}).status_code==200
    assert c.get(f'/api/lab/experiments/{eid}/notes/export').headers['content-disposition']

@pytest.mark.parametrize('path',['/search?limit=201','/search?sort=DROP','/search?offset=-1','/experiments/missing/notes','/experiments/../../notes','/jobs/missing','/baskets/../','/genetic-comparison?a=x&an=-1&b=x&bn=2'])
def test_invalid_and_missing(lab,path):
    c,_,_=lab;assert c.get('/api/lab'+path).status_code in (400,404,422,405)

def test_baskets_bookmarks_and_reference_validation(lab):
    c,s,eid=lab
    b={'name':'Saved set','entrants':[{'experiment_id':eid,'network_id':1}]}
    assert c.put('/api/lab/baskets/draft',headers=H,json=b).status_code==200
    assert c.get('/api/lab/baskets').json()[0]['entrants'][0]['available']
    r=c.post('/api/lab/bookmarks',headers=H,json={'experiment_id':eid,'kind':'generation','reference':{'generation':2},'name':'Interesting generation','tags':['test']});assert r.status_code==200,r.text
    bid=r.json()['id'];assert len(c.get('/api/lab/bookmarks?q=Interesting').json()['items'])==1
    assert c.post('/api/lab/bookmarks',headers=H,json={'experiment_id':eid,'kind':'network','reference':{'network_id':999999},'name':'bad'}).status_code==404
    assert c.delete(f'/api/lab/bookmarks/{bid}',headers=H).status_code==200
    assert c.delete('/api/lab/baskets/draft',headers=H).status_code==200

def test_family_actual_edges_missing_multi_parent_cycle_and_paging(lab):
    c,s,eid=lab
    with s.transaction() as db:
        db.execute('DELETE FROM parents WHERE experiment_id=?',(eid,))
        for child,parent in [(2,1),(3,1),(4,2),(4,3),(5,9999),(1,4)]:db.execute('INSERT INTO parents VALUES(?,?,?)',(eid,child,parent))
    result=family_graph(s,eid,4,depth=10,limit=20)
    assert {'parent':2,'child':4} in result['edges'] and {'parent':3,'child':4} in result['edges']
    assert len(result['nodes'])<=20
    assert family_graph(s,eid,5)['nodes'][1]['unknown']
    assert family_graph(s,eid,6)['nodes'][0]['founder']
    page=family_graph(s,eid,1,'descendants',depth=2,limit=2)
    assert page['next_cursor']
    seen=set();pages=0
    while page['next_cursor']:
        pages+=1;assert pages<30
        seen.update((e['parent'],e['child']) for e in page['edges'])
        page=family_graph(s,eid,1,'descendants',depth=2,limit=2,cursor=page['next_cursor'])
    seen.update((e['parent'],e['child']) for e in page['edges'])
    assert (1,2) in seen and (1,3) in seen
    assert c.get(f'/api/lab/experiments/{eid}/family/1?depth=31').status_code==422
    assert c.get(f'/api/lab/experiments/{eid}/family/1?cursor=bad').status_code in (400,422)

def test_genetic_sections_and_incompatible(lab):
    c,s,eid=lab
    result=genetic_comparison(s,eid,1,eid,2,limit=5)
    assert len(result['cells'])==5 and result['next_offset']==5
    a,b=s.genome(eid,1),s.genome(eid,2)
    assert result['cells'][0]['difference']==b.parameters[0]-a.parameters[0]
    bias=genetic_comparison(s,eid,1,eid,2,kind='biases')
    assert bias['cells'][0]['index']==a.weight_count
    with s.transaction() as db:s.put_genome(db,eid,Genome(99999,(2,2),('linear',),np.zeros(6)))
    mismatch=genetic_comparison(s,eid,1,eid,99999);assert not mismatch['compatible'] and 'rms' not in mismatch
    assert c.get('/api/lab/genetic-comparison',params={'a':eid,'an':1,'b':eid,'bn':2}).status_code==200


def test_chart_extremes_replay_sparse_timeline(lab):
    c,s,eid=lab
    with s.transaction() as db:
        for generation in range(8,10008):
            maximum=10000 if generation==5001 else generation%40
            db.execute('INSERT INTO generations VALUES(?,?,?)',(eid,generation,encode({'mean':generation%11,'maximum':maximum,'minimum':-maximum})))
        db.execute('UPDATE experiments SET generation=10008 WHERE id=?',(eid,))
    result=chart_data(s,eid,end=10007,points=100,metrics=['mean','maximum','minimum'])
    assert len(result['rows'])<=100 and result['downsampled']
    assert any(row['generation']==5001 for row in result['rows'])
    assert result['rows'][0]['generation']==0 and result['rows'][-1]['generation']==10007
    r=c.get(f'/api/lab/experiments/{eid}/replay/9').json();assert not r['snapshot_retained'] and not r['population']
    assert c.get(f'/api/lab/experiments/{eid}/replay/99999').status_code==404
    assert c.get(f'/api/lab/experiments/{eid}/chart?metrics=madeup').status_code==400
    assert c.get(f'/api/lab/experiments/{eid}/timeline?limit=2').json()['next_offset']==2

def test_background_backup_report_milestone_export_and_delete(lab):
    c,s,eid=lab
    c.put(f'/api/lab/experiments/{eid}/notes',headers=H,json={'content':{'hypothesis':'<script>bad()</script>'}})
    for kind,parameters in [('storage_measure',{}),('milestones',{'experiment_id':eid,'config':{'champion_duration':2}}),('report',{'experiment_id':eid,'include_lineage':True}),('export',{'ids':[eid],'kind':'statistics'}),('backup',{})]:
        r=c.post('/api/lab/jobs',headers=H,json={'kind':kind,'parameters':parameters});assert r.status_code==200,r.text
        job=wait_job(c,r.json()['id']);assert job['status']=='completed',job
        if kind in ('report','export'):
            download=c.get(f'/api/lab/jobs/{job["id"]}/download');assert download.status_code==200
            if kind=='report':assert '<script>bad' not in download.text and '&lt;script&gt;bad' in download.text
    marks=c.get(f'/api/lab/experiments/{eid}/milestones').json()['items'];assert marks
    assert c.put('/api/lab/milestones/'+str(marks[0]['id']),headers=H,json={'status':'confirmed','notes':'Observation only'}).status_code==200
    backups=c.get('/api/lab/backups').json()['items'];assert len(backups)==1
    bid=backups[0]['id'];assert c.get('/api/lab/backups/'+bid+'/download').status_code==200
    jid=c.post('/api/lab/jobs',headers=H,json={'kind':'verify_backup','parameters':{'backup_id':bid}}).json()['id']
    assert wait_job(c,jid)['status']=='completed'
    assert c.post('/api/lab/delete-preview',headers=H,json={'ids':[eid]}).json()['backup']['recent']
    jid=c.post('/api/lab/jobs',headers=H,json={'kind':'delete','parameters':{'ids':[eid],'confirm':[eid]}}).json()['id']
    assert wait_job(c,jid)['status']=='completed'
    assert not s.query('SELECT * FROM experiments')
    jid=c.post('/api/lab/jobs',headers=H,json={'kind':'reclaim'}).json()['id']
    assert wait_job(c,jid)['status']=='completed'


def test_jobs_failure_recovery_and_security(lab):
    c,s,eid=lab
    assert c.post('/api/lab/jobs',headers=H,json={'kind':'delete','parameters':{'ids':[eid]}}).status_code==422
    jid=c.post('/api/lab/jobs',headers=H,json={'kind':'report','parameters':{'experiment_id':'missing'}}).json()['id']
    assert wait_job(c,jid)['status']=='failed'
    for path in ['/api/lab/storage','/api/lab/resources','/api/lab/search','/api/lab/jobs']:
        assert c.get(path,headers={'Host':'evil.com'}).status_code==403
    assert c.post('/api/lab/jobs',headers={**H,'Origin':'https://evil.com'},json={'kind':'backup'}).status_code==403
    assert c.put(f'/api/lab/experiments/{eid}/notes',headers=H,json={'content':{'hypothesis':'x'*210000}}).status_code==413
    assert c.get('/api/lab/resources').status_code==200
    assert c.get('/api/lab/retention-presets').status_code==200


def test_streamed_request_size_and_revalidated_assets(lab):
    c, _, eid = lab
    def chunks():
        yield b'{"content":{"freeform":"'
        for _ in range(21):
            yield b'x'*10000
        yield b'"}}'
    # A misleading Content-Length cannot bypass the actual streamed byte limit.
    response = c.put(f'/api/lab/experiments/{eid}/notes',
                     headers={**H, 'Content-Length':'0', 'Content-Type':'application/json'},
                     content=chunks())
    assert response.status_code == 413
    for path in ('/', '/assets/lab.js'):
        assert c.get(path).headers['cache-control'] == 'no-cache'
