"""v2.0.1 upgrades and destructive operations use disposable workspaces only."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from collections import namedtuple
import gzip
import json
import shutil
import sqlite3
import time
import zipfile
import pytest
from evolution_engine.storage import Store,encode
from evolution_engine.config import Config
from evolution_engine.runner import run_experiment,exclusive
from evolution_engine.annotations import notes,save_notes,tag_experiments,repeat,save_bookmark,save_basket,baskets,config_diff
from evolution_engine.backups import create_backup,verify_backup,restore_backup,file_hash
from evolution_engine.storage_management import delete_experiments,deletion_preview,reclaim,refresh_estimates,storage_summary
from evolution_engine.coordination import gate,MaintenanceBusy
from evolution_engine.resources import disk_status,ResourceSampler
from test_core import small
from test_persistence import histories,genomes

FIXTURE=Path(__file__).parent/'fixtures/v2_0_0'

def experiment(tmp_path,generations=4):
    store=Store(tmp_path);eid=store.create(small(generations=generations));run_experiment(store.root,eid)
    return store,eid

def test_original_schema_upgrade_and_exact_resume(tmp_path):
    root=tmp_path/'old';root.mkdir()
    with gzip.open(FIXTURE/'engine.sqlite.gz','rb') as src:(root/'engine.sqlite').write_bytes(src.read())
    provenance=json.loads((FIXTURE/'provenance.json').read_text());eid=provenance['experiment']
    db=sqlite3.connect(root/'engine.sqlite')
    assert db.execute('PRAGMA user_version').fetchone()[0]==2
    before=db.execute('SELECT id,genes,metadata,fingerprint FROM genomes ORDER BY id').fetchall();db.close()
    s=Store(root);assert s.integrity()['schema']==3
    assert s.checkpoint(eid)['engine_version']=='2.0.0'
    assert [(r['id'],r['genes'],r['metadata'],r['fingerprint']) for r in genomes(s,eid)]==before
    save_notes(s,eid,{'hypothesis':'<script>alert(1)</script>'});tag_experiments(s,[eid],['exact','max seed'])
    assert Store(root).checkpoint(eid)['rng']==s.checkpoint(eid)['rng']
    run_experiment(root,eid)
    baseline=s.create(Config.model_validate(provenance['config']));run_experiment(root,baseline)
    assert histories(s,eid)==histories(s,baseline)
    assert genomes(s,eid)==genomes(s,baseline)
    assert s.checkpoint(eid)['rng']==s.checkpoint(baseline)['rng']

def test_migration_rollback_and_unknown_schema(tmp_path):
    root=tmp_path/'old';root.mkdir()
    with gzip.open(FIXTURE/'engine.sqlite.gz','rb') as src:(root/'engine.sqlite').write_bytes(src.read())
    s=Store.__new__(Store);s.root=root;s.path=root/'engine.sqlite'
    def fault(index):
        if index==6:raise OSError('injected migration failure')
    with pytest.raises(OSError):s.migrate(fault)
    assert s.query('PRAGMA user_version')[0]['user_version']==2
    assert not s.query("SELECT 1 FROM sqlite_master WHERE name='notes'")
    s.migrate();s.migrate()
    with s.transaction() as db:db.execute('PRAGMA user_version=999')
    with pytest.raises(ValueError,match='newer'):Store(root)

@pytest.mark.parametrize('stage',['fitness','parents','genomes','before_commit'])
def test_atomic_bulk_delete_failure(tmp_path,stage):
    s,a=experiment(tmp_path);b=s.create(small());c=s.create(small())
    prior=genomes(s,a)
    def fail(table,eid):
        if table==stage:raise OSError('injected delete failure')
    with pytest.raises(OSError):delete_experiments(s,[a,b],[a,b],True,fault=fail)
    assert s.experiment(a) and s.experiment(b) and s.experiment(c)
    assert genomes(s,a)==prior and s.integrity()['foreign_keys']==[]
    delete_experiments(s,[a,b],[a,b],True)
    assert s.experiment(c)
    with pytest.raises(KeyError):delete_experiments(s,[a,b],[a,b],True)
    assert s.integrity()['foreign_keys']==[]

def test_deletion_references_and_external_preservation(tmp_path):
    s,a=experiment(tmp_path);source=tmp_path/'immutable-source';source.write_bytes(b'untouched')
    with s.transaction() as db:
        db.execute('UPDATE genomes SET external=? WHERE experiment_id=? AND id=1',(encode({'path':str(source),'world':'A'}),a))
        db.execute('INSERT INTO analyses(created,kind,result) VALUES(?,?,?)',(time.time(),'tournament',encode({'entrants':[{'experiment_id':a,'network_id':1}],'net_matrix':[[0]]})))
    save_notes(s,a,{'observations':'real saved note'});tag_experiments(s,[a],['tag'])
    save_bookmark(s,{'experiment_id':a,'kind':'network','reference':{'network_id':1},'name':'founder'})
    save_basket(s,'draft','Draft',[{'experiment_id':a,'network_id':1}])
    preview=deletion_preview(s,[a]);assert preview['analyses']==[1] and preview['baskets']==['draft']
    with pytest.raises(ValueError,match='backup'):delete_experiments(s,[a],[a])
    delete_experiments(s,[a],[a],True)
    analysis=json.loads(s.query('SELECT result FROM analyses')[0]['result'])
    assert analysis['entrants'][0]['source_deleted'] and analysis['net_matrix']==[[0]]
    assert baskets(s)[0]['entrants'][0]['available'] is False
    assert source.read_bytes()==b'untouched' and not s.query('SELECT * FROM notes')

@pytest.mark.parametrize('active',['status','legacy_lock','worker_gate'])
def test_active_protection(tmp_path,active):
    s,eid=experiment(tmp_path)
    if active=='status':
        with s.transaction() as db:db.execute("UPDATE experiments SET status='running' WHERE id=?",(eid,))
        with pytest.raises(MaintenanceBusy):delete_experiments(s,[eid],[eid],True)
    elif active=='legacy_lock':
        with exclusive(s.root/f'{eid}.lock'):
            with pytest.raises(RuntimeError):delete_experiments(s,[eid],[eid],True)
    else:
        with gate(s.root):
            with ThreadPoolExecutor() as pool:
                with pytest.raises(MaintenanceBusy):pool.submit(delete_experiments,s,[eid],[eid],True).result()
    assert s.experiment(eid)

def test_queued_child_after_deletion(tmp_path):
    s=Store(tmp_path);eid=s.create(small(),'queued')
    delete_experiments(s,[eid],[eid],True)
    assert run_experiment(s.root,eid,scheduled=True) is None
    assert not s.query('SELECT * FROM experiments')

def test_workspace_gate_blocks_writes_and_new_worker(tmp_path):
    s=Store(tmp_path);eid=s.create(small(),'queued')
    with gate(s.root,exclusive=True),ThreadPoolExecutor() as pool:
        with pytest.raises(MaintenanceBusy):pool.submit(save_notes,s,eid,{'description':'racing write'}).result()
        with pytest.raises(MaintenanceBusy):pool.submit(run_experiment,s.root,eid).result()
    assert s.experiment(eid)['generation']==0

@pytest.mark.parametrize('stage',['snapshot','archive'])
def test_interrupted_backup_cleanup(tmp_path,stage):
    s,eid=experiment(tmp_path)
    def fault(at):
        if at==stage:raise OSError('interrupted backup')
    with pytest.raises(OSError):create_backup(s,fault=fault)
    assert list((s.root/'backups').iterdir())==[]
    assert not s.query('SELECT * FROM backups')
    assert s.experiment(eid)

def test_online_backup_restore_and_no_overwrite(tmp_path):
    s,eid=experiment(tmp_path/'source')
    # Keep a WAL connection open; online backup must include committed WAL pages.
    db=s.connect();db.execute('PRAGMA wal_autocheckpoint=0');db.execute('SELECT COUNT(*) FROM experiments').fetchone()
    save_notes(s,eid,{'hypothesis':'WAL data'});assert Path(str(s.path)+'-wal').stat().st_size>0
    backup=create_backup(s);path=s.root/'backups'/backup['filename'];original=file_hash(path)
    assert verify_backup(path)['verified']
    restored=restore_backup(path,tmp_path/'restored');copy=Store(restored['workspace'])
    assert notes(copy,eid)['content']['hypothesis']=='WAL data'
    assert genomes(s,eid)==genomes(copy,eid) and histories(s,eid)==histories(copy,eid)
    assert file_hash(path)==original
    with pytest.raises(ValueError,match='new'):restore_backup(path,tmp_path/'restored')
    assert copy.integrity()['foreign_keys']==[]
    delete_experiments(s,[eid],[eid])
    db.close();assert reclaim(s)['integrity']=='ok'

@pytest.mark.parametrize('problem',['checksum','traversal','duplicate','limit','new_schema'])
def test_archive_rejection(tmp_path,problem):
    s,eid=experiment(tmp_path/'source');backup=create_backup(s);path=s.root/'backups'/backup['filename']
    with zipfile.ZipFile(path) as src:raw=src.read('engine.sqlite');manifest=json.loads(src.read('manifest.json'))
    evil=tmp_path/'evil.zip'
    if problem=='checksum':manifest['files']['engine.sqlite']['sha256']='bad'
    if problem=='new_schema':manifest['schema_version']=999
    with zipfile.ZipFile(evil,'w') as out:
        out.writestr('../engine.sqlite' if problem=='traversal' else 'engine.sqlite',raw)
        out.writestr('manifest.json',json.dumps(manifest))
        if problem=='duplicate':out.writestr('manifest.json','{}')
    with pytest.raises(ValueError):verify_backup(evil,max_bytes=1 if problem=='limit' else 10**8)
    assert not (tmp_path/'engine.sqlite').exists()

def test_missing_external_dependency_reported(tmp_path):
    s,eid=experiment(tmp_path/'source')
    with s.transaction() as db:db.execute('UPDATE genomes SET external=? WHERE id=1',(encode({'path':str(tmp_path/'missing.sqlite'),'world':'A'}),))
    backup=create_backup(s);result=verify_backup(s.root/'backups'/backup['filename'])
    assert not result['self_contained']
    assert result['external_dependency_problems'][0]['status']=='missing'

def test_disk_capacity_guards_and_safe_pause(tmp_path,monkeypatch):
    s=Store(tmp_path);a=s.create(small());b=s.create(small());run_experiment(s.root,a)
    Usage=namedtuple('usage','total used free');usage=Usage(1000,999,1)
    monkeypatch.setattr(shutil,'disk_usage',lambda _:usage)
    with pytest.raises(ValueError,match='Insufficient'):create_backup(s)
    with pytest.raises(ValueError,match='Insufficient'):reclaim(s)
    policy={'enabled':True,'unit':'percent','warning':20,'critical':10,'pause':5}
    assert disk_status(s.root,policy)['pause_workers']
    assert disk_status(s.root,policy,Usage(1000,920,80))['block_scheduling']
    run_experiment(s.root,b);assert s.experiment(b)['status']=='paused' and s.experiment(b)['generation']==0
    monkeypatch.undo();run_experiment(s.root,b)
    assert histories(s,a)==histories(s,b) and genomes(s,a)==genomes(s,b)

def test_metadata_large_seed_repeats_and_estimates(tmp_path):
    s,eid=experiment(tmp_path)
    with s.transaction() as db:
        config=json.loads(db.execute('SELECT config FROM experiments WHERE id=?',(eid,)).fetchone()[0]);config['seed']=2**63-1
        # Synthetic completed config only for metadata API coverage, not resume.
        db.execute('UPDATE experiments SET config=? WHERE id=?',(encode(config),eid))
    same=repeat(s,eid);fresh=repeat(s,eid,'fresh',preset='compact')
    assert same['seed_text']==str(2**63-1) and fresh['seed_text']!=same['seed_text']
    assert next(f for f in config_diff(s,eid,same['id'])['fields'] if f['path']=='seed')['a']==str(2**63-1)
    assert s.experiment(fresh['id'])['config']['execution']['history_stride']==100
    save_notes(s,eid,{'hypothesis':'one'});save_notes(s,eid,{'observations':'two'})
    assert notes(s,eid)['content']['hypothesis']=='one'
    tag_experiments(s,[eid,same['id']],['a','b'],group='project')
    with pytest.raises(KeyError):tag_experiments(s,[eid,'missing'],['should rollback'])
    assert not s.query("SELECT 1 FROM tags WHERE name='should rollback'")
    refresh_estimates(s);summary=storage_summary(s)
    assert summary['estimate_coverage']==3 and summary['counts']['genomes']>0
    sample=ResourceSampler().sample(s);assert sample['cpu_count']>0 and sample['memory_available_bytes']>0
