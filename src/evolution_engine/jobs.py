"""Durable bounded jobs, one workspace executor, explicit crash recovery.

The database owns the queue; the process lock owns execution. A daemon thread
keeps HTTP handlers short. On restart an interrupted operation is marked failed,
never silently called complete, and queued operations are processed normally.
"""
from pathlib import Path
import json
import threading
import time
import uuid
import zipfile
from .storage import encode
from .runner import exclusive

class Jobs:
    def __init__(self,store):
        self.store=store;self.thread=None;self.mutex=threading.Lock()

    def submit(self,kind,request):
        now=time.time();jid=uuid.uuid4().hex
        with self.store.transaction() as db:
            if db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]>=20:raise ValueError('Background queue full (20 jobs); wait for current work to finish.')
            db.execute('INSERT INTO jobs(id,kind,status,request,created,updated) VALUES(?,?,?,?,?,?)',(jid,kind,'queued',encode(request),now,now))
        self.wake();return {'id':jid,'status':'queued'}

    def wake(self):
        with self.mutex:
            if self.thread and self.thread.is_alive():return
            self.thread=threading.Thread(target=self.run,name='evolution-lab-jobs',daemon=True);self.thread.start()

    def run(self):
        try:
            with exclusive(self.store.root/'jobs.lock'):
                with self.store.transaction() as db:
                    db.execute("UPDATE jobs SET status='interrupted',error='Executor stopped before completion; inspect outputs and retry explicitly.',updated=? WHERE status='running'",(time.time(),))
                while True:
                    rows=self.store.query("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1")
                    if not rows:return
                    job=rows[0];jid=job['id']
                    with self.store.transaction() as db:db.execute("UPDATE jobs SET status='running',updated=? WHERE id=?",(time.time(),jid))
                    last=[0.0]
                    def progress(value):
                        if time.monotonic()-last[0]<.2:return
                        last[0]=time.monotonic()
                        with self.store.transaction() as db:db.execute('UPDATE jobs SET progress=?,updated=? WHERE id=?',(min(.99,max(0,value)),time.time(),jid))
                    try:
                        result=self.execute(job['kind'],json.loads(job['request']),jid,progress)
                        with self.store.transaction() as db:db.execute("UPDATE jobs SET status='completed',progress=1,result=?,updated=? WHERE id=?",(encode(result),time.time(),jid))
                    except Exception as exc:
                        with self.store.transaction() as db:db.execute("UPDATE jobs SET status='failed',error=?,updated=? WHERE id=?",(f'{type(exc).__name__}: {exc}',time.time(),jid))
        except (RuntimeError,ValueError):
            # Another process owns jobs.lock, or maintenance temporarily owns the
            # workspace gate. API polling wakes the executor again after it clears.
            return

    def execute(self,kind,request,jid,progress):
        store=self.store
        if kind=='backup':
            from .backups import create_backup
            return create_backup(store,progress)
        if kind=='verify_backup':
            from .backups import verify_backup,file_hash
            rows=store.query('SELECT * FROM backups WHERE id=?',(request['backup_id'],))
            if not rows:raise KeyError('backup')
            row=rows[0];path=store.root/'backups'/row['filename']
            if file_hash(path)!=row['checksum']:raise ValueError('Archive checksum changed since creation')
            result=verify_backup(path,store.root)
            with store.transaction() as db:db.execute('UPDATE backups SET verified=? WHERE id=?',(time.time(),row['id']))
            return result
        if kind=='storage_measure':
            from .storage_management import refresh_estimates
            return refresh_estimates(store,progress)
        if kind=='reclaim':
            from .storage_management import reclaim
            return reclaim(store,progress)
        if kind=='delete':
            from .storage_management import delete_experiments
            return delete_experiments(store,**request)
        if kind=='tags':
            from .annotations import tag_experiments
            return tag_experiments(store,**request)
        if kind=='milestones':
            from .history_lab import detect_milestones
            return detect_milestones(store,request['experiment_id'],request['config'],progress)
        directory=store.root/'exports';directory.mkdir(exist_ok=True)
        if kind=='report':
            from .reports import report_html
            body=report_html(store,request['experiment_id'],request['include_weights'],request['include_lineage'])
            name=f'{jid}.html';(directory/name).write_text(body)
            return {'filename':name,'content_type':'text/html','description':'Offline research report; not a database backup'}
        if kind=='export':
            from .research import export_result
            from .annotations import require_ids
            with store.connect() as db:require_ids(db,request['ids'])
            name=f'{jid}.zip'
            with zipfile.ZipFile(directory/name,'w',zipfile.ZIP_DEFLATED) as out:
                out.writestr('README.txt','Selected research exports, not a restorable workspace backup. Use Backups for full preservation.\n')
                for index,eid in enumerate(request['ids']):
                    data,mime,filename=export_result(store,eid,request['kind'],request.get('generation'))
                    out.writestr(eid+'/'+Path(filename).name,data);progress((index+1)/len(request['ids'])*.95)
            return {'filename':name,'content_type':'application/zip','experiments':request['ids'],'restorable_backup':False}
        if kind=='lineage':
            from .lab_queries import family_graph
            result=family_graph(store,**request)
            name=f'{jid}.json';(directory/name).write_text(json.dumps(result,indent=2))
            return {'filename':name,'content_type':'application/json','nodes':len(result['nodes']),'bounded':True}
        raise ValueError('unknown job kind')

    def list(self):
        self.wake()
        rows=self.store.query('SELECT * FROM jobs ORDER BY created DESC LIMIT 100')
        for row in rows:
            row['request']=json.loads(row['request']);row['result']=json.loads(row['result']) if row['result'] else None
        return rows
