"""Consistent SQLite snapshots with bounded, verified, new-workspace restores."""
from hashlib import sha256
from pathlib import Path
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import time
import uuid
import zipfile
from . import __version__
from .compatibility import validate_checkpoint
from .coordination import gate
from .migrations import SCHEMA_VERSION
from .storage import encode

MAX_ARCHIVE_BYTES=64*1024**3
MAX_MANIFEST_BYTES=4*1024**2

def file_hash(path):
    digest=sha256()
    with open(path,'rb') as file:
        for block in iter(lambda:file.read(1024**2),b''):digest.update(block)
    return digest.hexdigest()

def readonly(path):
    db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro&immutable=1',uri=True)
    db.row_factory=sqlite3.Row
    return db

def dependencies(db):
    refs={}
    for row in db.execute('SELECT DISTINCT external FROM genomes WHERE external IS NOT NULL'):
        value=json.loads(row[0]);path=Path(value['path']).resolve()
        if str(path) in refs:continue
        item={'path':str(path),'included':False,'available':path.is_file()}
        wal=Path(str(path)+'-wal')
        if item['available'] and not (wal.exists() and wal.stat().st_size):
            item.update({'size':path.stat().st_size,'sha256':file_hash(path)})
        else:item['warning']='Missing source or pending WAL; immutable dependency not verified'
        refs[str(path)]=item
    return list(refs.values())

def validate_database(path,expected_schema=None):
    db=readonly(path)
    try:
        version=db.execute('PRAGMA user_version').fetchone()[0]
        if version<2 or version>SCHEMA_VERSION or (expected_schema is not None and version!=expected_schema):raise ValueError('unsupported backup schema')
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('database integrity check failed')
        if db.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('database foreign-key check failed')
        configs={r['id']:r for r in db.execute('SELECT id,config,generation,status FROM experiments')}
        latest={}
        for row in db.execute('SELECT * FROM checkpoints ORDER BY generation'):
            if sha256(row['state'].encode()).hexdigest()!=row['checksum']:raise ValueError('corrupt checkpoint checksum')
            state=json.loads(row['state']);validate_checkpoint(state);eid=row['experiment_id'];exp=configs[eid]
            if state['experiment_id']!=eid or state['generation']!=row['generation'] or row['generation']>exp['generation']:raise ValueError('checkpoint identity/progress mismatch')
            ids=state['population']
            if not ids or len(set(ids))!=len(ids):raise ValueError('invalid checkpoint population')
            if state['next_id']<=max(ids):raise ValueError('invalid checkpoint next identity')
            before=state['config'].copy();after=json.loads(exp['config']);before.pop('generations');after.pop('generations')
            if before!=after:raise ValueError('checkpoint configuration mismatch')
            if len(ids)!=before['population']['size']:raise ValueError('checkpoint population size mismatch')
            for nid in ids:
                if not db.execute('SELECT 1 FROM genomes WHERE experiment_id=? AND id=?',(eid,nid)).fetchone():raise ValueError('missing checkpoint genome')
            from .randomness import restore
            restore(state['rng'])
            latest[eid]=row['generation']
        for eid,exp in configs.items():
            if exp['status']!='imported' and exp['generation']>0 and latest.get(eid)!=exp['generation']:raise ValueError('missing latest checkpoint')
        return {'schema':version,'experiments':len(configs),'checkpoints_validated':db.execute('SELECT COUNT(*) FROM checkpoints').fetchone()[0]}
    finally:db.close()

def create_backup(store,progress=lambda p:None,fault=None):
    directory=store.root/'backups';directory.mkdir(exist_ok=True)
    bid=uuid.uuid4().hex;filename=f'{bid}.zip';final=directory/filename
    with gate(store.root),tempfile.TemporaryDirectory(prefix='.backup-',dir=directory) as temporary:
        temporary=Path(temporary);snapshot=temporary/'engine.sqlite'
        estimated=store.path.stat().st_size
        if shutil.disk_usage(directory).free<estimated*2+16*1024**2:raise ValueError('Insufficient disk space for backup snapshot and archive')
        source=store.connect();target=sqlite3.connect(snapshot)
        try:
            source.backup(target,pages=1024,progress=lambda status,remaining,total:progress(.6*(1-remaining/max(total,1))),sleep=.01)
        finally:target.close();source.close()
        if fault:fault('snapshot')
        validation=validate_database(snapshot)
        db=readonly(snapshot)
        try:deps=dependencies(db)
        finally:db.close()
        manifest={'format':'evolution-workspace-backup','format_version':1,'id':bid,'created':time.time(),'application_version':__version__,
                  'schema_version':validation['schema'],'files':{'engine.sqlite':{'size':snapshot.stat().st_size,'sha256':file_hash(snapshot)}},
                  'external_dependencies':deps,'self_contained':not deps,'contents':'All persisted scientific and research metadata in SQLite. Logs, lock files, caches and previous backups are excluded. External immutable sources are referenced, never copied.'}
        archive=temporary/'archive.zip'
        with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=3,allowZip64=True) as out:
            out.write(snapshot,'engine.sqlite');out.writestr('manifest.json',encode(manifest))
        progress(.85)
        if fault:fault('archive')
        checksum=file_hash(archive);size=archive.stat().st_size
        # Validation uses the actual compressed archive before it becomes visible.
        verify_backup(archive,temporary)
        os.replace(archive,final)
        try:
            with store.transaction() as db:db.execute('INSERT INTO backups VALUES(?,?,?,?,?,?,?)',(bid,manifest['created'],filename,encode(manifest),size,checksum,time.time()))
        except BaseException:
            final.unlink(missing_ok=True);raise
    return {'id':bid,'filename':filename,'size':size,'sha256':checksum,'manifest':manifest,'verified':True}

def extract_verified(archive,destination,max_bytes=MAX_ARCHIVE_BYTES):
    with zipfile.ZipFile(archive) as source:
        infos=source.infolist()
        if len(infos)!=2 or {i.filename for i in infos}!={'engine.sqlite','manifest.json'}:raise ValueError('archive must contain exactly engine.sqlite and manifest.json; paths and extra entries are forbidden')
        for info in infos:
            if info.flag_bits&1 or stat.S_ISLNK(info.external_attr>>16):raise ValueError('encrypted or symlink archive entries are forbidden')
            if info.file_size<0 or info.file_size>max_bytes:raise ValueError('archive exceeds extraction limit')
        manifest_info=source.getinfo('manifest.json')
        if manifest_info.file_size>MAX_MANIFEST_BYTES:raise ValueError('manifest exceeds extraction limit')
        manifest=json.loads(source.read('manifest.json'))
        if manifest.get('format')!='evolution-workspace-backup' or manifest.get('format_version')!=1:raise ValueError('unsupported archive format')
        if set(manifest.get('files',{}))!={'engine.sqlite'}:raise ValueError('invalid manifest files')
        size=source.getinfo('engine.sqlite').file_size
        if size!=manifest['files']['engine.sqlite'].get('size'):raise ValueError('manifest size mismatch')
        if shutil.disk_usage(destination).free<size+16*1024**2:raise ValueError('Insufficient disk space for extraction')
        target=Path(destination)/'engine.sqlite';written=0;digest=sha256()
        with source.open('engine.sqlite') as inp,target.open('xb') as out:
            while block:=inp.read(1024**2):
                written+=len(block)
                if written>size or written>max_bytes:raise ValueError('archive exceeds extraction limit')
                digest.update(block);out.write(block)
            out.flush();os.fsync(out.fileno())
        if written!=size or digest.hexdigest()!=manifest['files']['engine.sqlite'].get('sha256'):raise ValueError('backup checksum mismatch')
    checks=validate_database(target,manifest.get('schema_version'))
    db=readonly(target)
    try:actual_paths={json.loads(r[0])['path'] for r in db.execute('SELECT DISTINCT external FROM genomes WHERE external IS NOT NULL')}
    finally:db.close()
    declared=manifest.get('external_dependencies',[])
    if {d.get('path') for d in declared}!={str(Path(p).resolve()) for p in actual_paths}:raise ValueError('external dependency manifest mismatch')
    if bool(manifest.get('self_contained'))!=(not bool(declared)):raise ValueError('invalid self-contained claim')
    problems=[]
    for dep in declared:
        path=Path(dep['path']);wal=Path(str(path)+'-wal')
        if not path.is_file():problems.append({'path':str(path),'status':'missing'})
        elif wal.exists() and wal.stat().st_size:problems.append({'path':str(path),'status':'pending_wal'})
        elif not dep.get('sha256') or file_hash(path)!=dep['sha256']:problems.append({'path':str(path),'status':'changed_or_unverified'})
    return {'manifest':manifest,'validation':checks,'external_dependency_problems':problems,'self_contained':not declared}

def verify_backup(archive,scratch=None,max_bytes=MAX_ARCHIVE_BYTES):
    try:
        with tempfile.TemporaryDirectory(prefix='.verify-',dir=scratch) as directory:
            result=extract_verified(archive,Path(directory),max_bytes)
        return {**result,'verified':True,'sha256':file_hash(archive)}
    except (zipfile.BadZipFile,KeyError,TypeError,json.JSONDecodeError,sqlite3.DatabaseError) as exc:
        raise ValueError(f'Invalid backup: {exc}') from exc

def restore_backup(archive,destination,max_bytes=MAX_ARCHIVE_BYTES):
    destination=Path(destination).expanduser().absolute()
    if destination.exists() or destination.is_symlink():raise ValueError('Restore requires a new, nonexistent workspace directory; nothing was overwritten.')
    if not destination.parent.is_dir():raise ValueError('Restore parent directory must already exist')
    with tempfile.TemporaryDirectory(prefix='.restore-',dir=destination.parent) as temporary:
        result=extract_verified(archive,Path(temporary),max_bytes)
        # Never modify checkpoint/config rows. An active snapshot becomes paused;
        # queued work becomes paused too, so opening the restore never auto-runs it.
        db=sqlite3.connect(Path(temporary)/'engine.sqlite')
        try:
            db.execute("UPDATE experiments SET status='paused',pid=NULL WHERE status IN ('running','pausing','cancelling','queued')")
            if result['validation']['schema']>=3:db.execute("UPDATE jobs SET status='interrupted',error='Restored workspace: operation was not resumed' WHERE status IN ('running','queued')")
            db.commit();db.execute('PRAGMA wal_checkpoint(TRUNCATE)');db.execute('PRAGMA journal_mode=DELETE')
        finally:db.close()
        # Atomic no-overwrite publication. mkdir reserves the destination; only the
        # fully validated database is renamed into it, on the same filesystem.
        destination.mkdir()
        try:
            os.replace(Path(temporary)/'engine.sqlite',destination/'engine.sqlite')
            (destination/'RESTORE_PROVENANCE.json').write_text(json.dumps(result,indent=2)+'\n')
        except BaseException:
            # Keep any published DB for recovery; never remove unexpected files.
            if not any(destination.iterdir()):destination.rmdir()
            raise
    return {**result,'workspace':str(destination),'restored':True,'execution_state':'Active and queued experiments paused; scientific checkpoint content unchanged.'}
