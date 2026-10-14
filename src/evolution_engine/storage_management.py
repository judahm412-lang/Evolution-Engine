"""Logical storage estimates, atomic deletion, and coordinated VACUUM."""
from contextlib import ExitStack
import json
import os
import shutil
import time
from .annotations import require_ids
from .coordination import gate,MaintenanceBusy
from .storage import encode

TABLES=('fitness','populations','parents','checkpoints','generations','events','notes','experiment_tags','bookmarks','milestones','repetitions','research_groups','storage_estimates','genomes')

def estimate(db,eid):
    # LENGTH(blob) is evaluated in SQLite, never materialized as Python bytes.
    row=db.execute('SELECT COUNT(*),COALESCE(SUM(LENGTH(genes)),0),COALESCE(SUM(LENGTH(layers)+LENGTH(activations)+LENGTH(metadata)+LENGTH(fingerprint)+COALESCE(LENGTH(external),0)+80),0) FROM genomes WHERE experiment_id=?',(eid,)).fetchone()
    counts={table:db.execute(f'SELECT COUNT(*) FROM {table} WHERE experiment_id=?',(eid,)).fetchone()[0] for table in TABLES}
    history=db.execute('SELECT COALESCE(SUM(LENGTH(components)+100),0) FROM fitness WHERE experiment_id=?',(eid,)).fetchone()[0]
    history+=db.execute('SELECT COALESCE(SUM(LENGTH(statistics)+48),0) FROM generations WHERE experiment_id=?',(eid,)).fetchone()[0]+counts['populations']*56+counts['parents']*48
    checkpoints=db.execute('SELECT COALESCE(SUM(LENGTH(state)+LENGTH(checksum)+64),0) FROM checkpoints WHERE experiment_id=?',(eid,)).fetchone()[0]
    result={'counts':counts,'genomes':row[0],'parameter_bytes':row[1],'genome_metadata_bytes':row[2],'history_bytes':history,'checkpoint_bytes':checkpoints,
            'retained_generations':db.execute('SELECT COUNT(DISTINCT generation) FROM populations WHERE experiment_id=?',(eid,)).fetchone()[0]}
    result['logical_bytes']=row[1]+row[2]+history+checkpoints
    result['method']='SQL payload lengths plus approximate row overhead. Excludes indexes, page fragmentation, user annotation payloads, and shared metadata. Not a physical file size.'
    return result

def refresh_estimates(store,progress=lambda p:None):
    ids=store.query('SELECT id,generation FROM experiments ORDER BY id')
    for i,row in enumerate(ids):
        with store.transaction() as db:
            current=db.execute('SELECT generation FROM experiments WHERE id=?',(row['id'],)).fetchone()
            if current is None:continue
            result=estimate(db,row['id'])
            db.execute('INSERT OR REPLACE INTO storage_estimates VALUES(?,?,?,?,?)',(row['id'],current[0],time.time(),encode(result),result['logical_bytes']))
        progress((i+1)/max(1,len(ids))*.95)
    return measure_workspace(store)

def physical(store):
    def size(path):
        try:return path.stat().st_size
        except FileNotFoundError:return 0
    return {'database_bytes':size(store.path),'wal_bytes':size(store.path.with_name('engine.sqlite-wal')),'shm_bytes':size(store.path.with_name('engine.sqlite-shm'))}

def measure_workspace(store):
    count=0
    for root,dirs,files in os.walk(store.root,followlinks=False):
        dirs[:]=[d for d in dirs if not (store.root.__class__(root)/d).is_symlink()]
        for name in files:
            path=store.root.__class__(root)/name
            try:
                if not path.is_symlink():count+=path.stat().st_size
            except FileNotFoundError:pass
    p=physical(store);free=shutil.disk_usage(store.root).free
    with store.transaction() as db:
        db.execute('INSERT INTO storage_measurements(time,physical_bytes,workspace_bytes,free_bytes) VALUES(?,?,?,?)',(time.time(),sum(p.values()),count,free))
        db.execute('DELETE FROM storage_measurements WHERE id NOT IN (SELECT id FROM storage_measurements ORDER BY id DESC LIMIT 1000)')
    return {**p,'workspace_bytes':count,'free_bytes':free}

def storage_summary(store):
    p=physical(store)
    pages=store.query('PRAGMA page_size')[0]['page_size'];freepages=store.query('PRAGMA freelist_count')[0]['freelist_count']
    counts={table:store.query(f'SELECT COUNT(*) n FROM {table}')[0]['n'] for table in ('experiments','genomes','checkpoints')}
    counts['retained_population_snapshots']=store.query('SELECT COUNT(*) n FROM (SELECT experiment_id,generation FROM populations GROUP BY experiment_id,generation)')[0]['n']
    sizes=store.query('SELECT COALESCE(SUM(logical_bytes),0) n,COUNT(*) coverage FROM storage_estimates')[0]
    return {**p,'physical_bytes':sum(p.values()),'free_disk_bytes':shutil.disk_usage(store.root).free,'counts':counts,
            'states':store.query('SELECT status,COUNT(*) n FROM experiments GROUP BY status'),'estimated_reusable_bytes':pages*freepages,
            'cached_logical_bytes':sizes['n'],'estimate_coverage':sizes['coverage'],'physical_minus_estimate_bytes':sum(p.values())-sizes['n'],
            'overhead_note':'Physical minus cached logical estimates is an accounting remainder, not an exact overhead measurement. It includes indexes, free pages, WAL, annotations, stale estimates, and other shared data.',
            'measurements':store.query('SELECT * FROM storage_measurements ORDER BY id DESC LIMIT 100'),
            'last_backup':recent_backup(store)}

def recent_backup(store):
    rows=store.query('SELECT id,created,verified,filename,size,checksum FROM backups WHERE verified IS NOT NULL ORDER BY verified DESC LIMIT 1')
    if not rows:return None
    row=rows[0];path=store.root/'backups'/row['filename']
    row['recent']=bool(time.time()-row['verified']<86400 and path.is_file() and path.stat().st_size==row['size'])
    row['verification_note']='Verified within 24 hours; deletion rechecks the archive checksum.'
    return row

def deletion_preview(store,ids):
    db=store.connect()
    try:
        require_ids(db,ids);items=[]
        for eid in ids:
            row=dict(db.execute('SELECT id,name,status,generation FROM experiments WHERE id=?',(eid,)).fetchone())
            row['storage']=estimate(db,eid)
            from .manager import worker_active
            row['protected']=row['status'] in ('running','pausing','cancelling') or worker_active(store.root,eid)
            items.append(row)
        analyses=[]
        for row in db.execute('SELECT id,result FROM analyses'):
            refs=json.loads(row['result']).get('entrants',[])
            if any(ref.get('experiment_id') in ids for ref in refs):analyses.append(row['id'])
        baskets=[]
        for row in db.execute('SELECT id,entrants FROM baskets'):
            if any(ref.get('experiment_id') in ids for ref in json.loads(row['entrants'])):baskets.append(row['id'])
        return {'items':items,'analyses':analyses,'baskets':baskets,'estimated_bytes':sum(i['storage']['logical_bytes'] for i in items),'backup':recent_backup(store),
                'policy':'Atomic deletion. Self-contained results survive with deleted source markers. Basket entries become unavailable. External historical files are never removed. All workers must be paused for maintenance.'}
    finally:db.close()

def maintenance(store):
    """Return a stack owning the global gate and every legacy worker lock."""
    from .runner import exclusive
    stack=ExitStack()
    try:
        stack.enter_context(gate(store.root,exclusive=True))
        for row in store.query('SELECT id,status FROM experiments'):
            if row['status'] in ('running','pausing','cancelling'):raise MaintenanceBusy('Pause all workers and wait for safe boundaries before maintenance.')
            stack.enter_context(exclusive(store.root/f'{row["id"]}.lock'))
        return stack
    except BaseException:
        stack.close();raise

def delete_experiments(store,ids,confirm,acknowledge_no_backup=False,remove_analyses=False,fault=None):
    if sorted(ids)!=sorted(confirm):raise ValueError('confirmation must contain every selected experiment ID')
    with maintenance(store):
        backup=recent_backup(store);valid=False
        if backup and backup['recent']:
            from .backups import file_hash
            valid=file_hash(store.root/'backups'/backup['filename'])==backup['checksum']
        if not valid and not acknowledge_no_backup:raise ValueError('No verified recent backup. Create one or explicitly acknowledge deletion without it.')
        with store.transaction() as db:
            require_ids(db,ids)
            for row in db.execute('SELECT id,result FROM analyses').fetchall():
                result=json.loads(row['result']);refs=result.get('entrants',[])
                if any(ref.get('experiment_id') in ids for ref in refs):
                    if remove_analyses:
                        db.execute("DELETE FROM bookmarks WHERE kind='tournament' AND json_extract(reference,'$.analysis_id')=?",(row['id'],))
                        db.execute('DELETE FROM analyses WHERE id=?',(row['id'],))
                    else:
                        for ref in refs:
                            if ref.get('experiment_id') in ids:ref['source_deleted']=True
                        result['source_reference_notice']='Some source experiments were deleted; saved analytical observations are preserved.'
                        db.execute('UPDATE analyses SET result=? WHERE id=?',(encode(result),row['id']))
            for eid in ids:
                for table in TABLES:
                    db.execute(f'DELETE FROM {table} WHERE experiment_id=?',(eid,))
                    if fault:fault(table,eid)
                db.execute('DELETE FROM experiments WHERE id=?',(eid,))
            if fault:fault('before_commit',None)
    return {'deleted':ids,'atomic':True,'external_files_deleted':False,'physical_space_reclaimed':False}

def reclaim(store,progress=lambda p:None):
    with maintenance(store):
        before=sum(physical(store).values())
        if shutil.disk_usage(store.root).free<store.path.stat().st_size*2+16*1024**2:raise ValueError('Insufficient disk space for VACUUM; allow twice the database size plus 16 MiB.')
        db=store.connect()
        try:
            result=db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
            if result[0]:raise MaintenanceBusy('A database reader prevents WAL checkpointing; close it and retry.')
            progress(.2);db.execute('VACUUM');progress(.8)
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('Post-maintenance integrity check failed')
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        finally:db.close()
        after=sum(physical(store).values())
    return {'before_bytes':before,'after_bytes':after,'reclaimed_bytes':max(0,before-after),'integrity':'ok'}
