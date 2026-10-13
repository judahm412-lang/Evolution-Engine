"""Short WAL transactions commit generations and recovery state atomically."""
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import json
import sqlite3
import time
import uuid
import numpy as np
from . import __version__
from .config import Config
from .neural import Genome

from .migrations import SCHEMA_VERSION, migrate_metadata
from .coordination import gate
from .compatibility import validate_checkpoint
def encode(value): return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)

def historical_connection(path):
    """Frozen inputs must not create sidecars or omit uncheckpointed writes."""
    path=Path(path).resolve(strict=True)
    wal=Path(str(path)+'-wal')
    if wal.exists() and wal.stat().st_size:
        raise ValueError('historical source has pending WAL data; close and checkpoint it before import')
    return sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True)

class Store:
    def __init__(self,root):
        self.root=Path(root).expanduser().resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/'engine.sqlite'
        self.migrate()

    def connect(self):
        db=sqlite3.connect(self.path,timeout=30)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA busy_timeout=30000')
        return db

    @contextmanager
    def transaction(self):
        with gate(self.root):
            with self._transaction() as db:
                yield db

    @contextmanager
    def _transaction(self):
        db=self.connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback();raise
        finally:db.close()

    def query(self,sql,args=()):
        db=self.connect()
        try:return [dict(r) for r in db.execute(sql,args)]
        finally:db.close()

    def migrate(self, fault=None):
        # Current schemas need no write lock or migration transaction.
        with self.connect() as probe:
            version=probe.execute("PRAGMA user_version").fetchone()[0]
        probe.close()
        if version>SCHEMA_VERSION: raise ValueError("database schema is newer than this engine")
        if version==SCHEMA_VERSION:return
        with gate(self.root):
            self._migrate(fault)

    def _migrate(self, fault=None):
        db=self.connect()
        try:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('BEGIN IMMEDIATE')
            version=db.execute('PRAGMA user_version').fetchone()[0]
            if version>SCHEMA_VERSION: raise ValueError('database schema is newer than this engine')
            if version<1:
                statements=[
                  '''CREATE TABLE experiments(id TEXT PRIMARY KEY,name TEXT NOT NULL,config TEXT NOT NULL,status TEXT NOT NULL, generation INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL,updated REAL NOT NULL,pid INTEGER,error TEXT,attempts INTEGER NOT NULL DEFAULT 0,priority INTEGER NOT NULL DEFAULT 0,engine_version TEXT NOT NULL,origin TEXT)''',
                  '''CREATE TABLE genomes(experiment_id TEXT NOT NULL REFERENCES experiments(id),id INTEGER NOT NULL,layers TEXT NOT NULL,activations TEXT NOT NULL,genes BLOB,metadata TEXT NOT NULL,fingerprint TEXT NOT NULL,external TEXT,PRIMARY KEY(experiment_id,id))''',
                  '''CREATE TABLE parents(experiment_id TEXT NOT NULL,child_id INTEGER NOT NULL,parent_id INTEGER NOT NULL,PRIMARY KEY(experiment_id,child_id,parent_id),FOREIGN KEY(experiment_id,child_id) REFERENCES genomes(experiment_id,id))''',
                  '''CREATE TABLE populations(experiment_id TEXT NOT NULL,generation INTEGER NOT NULL,slot INTEGER NOT NULL,network_id INTEGER NOT NULL,PRIMARY KEY(experiment_id,generation,slot),UNIQUE(experiment_id,generation,network_id),FOREIGN KEY(experiment_id,network_id) REFERENCES genomes(experiment_id,id))''',
                  '''CREATE TABLE fitness(experiment_id TEXT NOT NULL,generation INTEGER NOT NULL,network_id INTEGER NOT NULL,total REAL NOT NULL,self_play REAL,bot REAL,matches INTEGER,wins INTEGER,losses INTEGER,draws INTEGER,components TEXT NOT NULL,PRIMARY KEY(experiment_id,generation,network_id),FOREIGN KEY(experiment_id,network_id) REFERENCES genomes(experiment_id,id))''',
                  '''CREATE TABLE generations(experiment_id TEXT NOT NULL REFERENCES experiments(id),generation INTEGER NOT NULL,statistics TEXT NOT NULL,PRIMARY KEY(experiment_id,generation))''',
                  '''CREATE TABLE checkpoints(experiment_id TEXT NOT NULL REFERENCES experiments(id),generation INTEGER NOT NULL,state TEXT NOT NULL,checksum TEXT NOT NULL,created REAL NOT NULL,archived INTEGER NOT NULL,PRIMARY KEY(experiment_id,generation))''',
                  '''CREATE TABLE events(id INTEGER PRIMARY KEY,experiment_id TEXT REFERENCES experiments(id),time REAL NOT NULL,kind TEXT NOT NULL,message TEXT NOT NULL)''',
                  '''CREATE TABLE benchmarks(id INTEGER PRIMARY KEY,created REAL NOT NULL,result TEXT NOT NULL)''',
                  '''CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)''',
                  '''CREATE INDEX parent_lookup ON parents(experiment_id,parent_id)''',
                  '''CREATE INDEX fitness_lookup ON fitness(experiment_id,network_id,generation)''']
                for statement in statements:db.execute(statement)
                db.execute('PRAGMA user_version=1')
            if version<2:
                db.execute('CREATE TABLE IF NOT EXISTS analyses(id INTEGER PRIMARY KEY,created REAL NOT NULL,kind TEXT NOT NULL,result TEXT NOT NULL)')
                db.execute('PRAGMA user_version=2')
            if version<3:migrate_metadata(db, fault)
            db.commit()
        except BaseException:db.rollback();raise
        finally:db.close()

    def event(self,db,eid,kind,message):
        db.execute('INSERT INTO events(experiment_id,time,kind,message) VALUES(?,?,?,?)',(eid,time.time(),kind,message))

    def create(self,config,status='created',origin=None):
        config=Config.model_validate(config.model_dump() if isinstance(config,Config) else config)
        eid=config.experiment_id or uuid.uuid4().hex[:12]
        config=config.model_copy(update={'experiment_id':eid})
        with self.transaction() as db:
            db.execute('INSERT INTO experiments(id,name,config,status,created,updated,priority,engine_version,origin) VALUES(?,?,?,?,?,?,?,?,?)',
                       (eid,config.name,encode(config.model_dump()),status,time.time(),time.time(),config.execution.priority,__version__,origin))
            self.event(db,eid,'created',f'PCG64 root seed {config.seed}; environment {config.environment.type}')
        return eid

    def experiment(self,eid):
        rows=self.query('SELECT * FROM experiments WHERE id=?',(eid,))
        if not rows:raise KeyError(f'unknown experiment {eid}')
        result=rows[0];result['config']=json.loads(result['config']);return result

    def list(self,limit=100,offset=0):
        rows=self.query('SELECT * FROM experiments ORDER BY created DESC LIMIT ? OFFSET ?',(limit,offset))
        for r in rows:r['config']=json.loads(r['config'])
        return rows

    def command(self,eid,action,generations=None):
        with self.transaction() as db:
            r=db.execute('SELECT * FROM experiments WHERE id=?',(eid,)).fetchone()
            if r is None:raise KeyError(eid)
            status=r['status'];c=Config.model_validate_json(r['config'])
            if status=='imported':raise ValueError('historical imports are read-only; create a new experiment')
            if generations is not None:
                if generations<=r['generation']:raise ValueError('new limit must exceed completed generations')
                c=Config.model_validate({**c.model_dump(),'generations':generations})
            if action in ('start','resume'):
                if status not in ('created','paused','failed','cancelled','completed'): raise ValueError(f'cannot {action} from {status}')
                if r['generation']>=c.generations:raise ValueError('increase generation limit to continue this completed experiment')
                new='queued'
                db.execute('UPDATE experiments SET attempts=0,error=NULL WHERE id=?',(eid,))
            elif action=='pause':
                if status not in ('running','queued'):raise ValueError(f'cannot pause from {status}')
                new='pausing' if status=='running' else 'paused'
            elif action in ('cancel','stop'):
                if status in ('completed','cancelled'):raise ValueError(f'cannot cancel from {status}')
                new='cancelling' if status in ('running','pausing') else 'cancelled'
            else:raise ValueError('unknown action')
            db.execute('UPDATE experiments SET status=?,config=?,updated=? WHERE id=?',(new,encode(c.model_dump()),time.time(),eid))
            self.event(db,eid,action,f'{status} -> {new}')
        return self.experiment(eid)

    def put_genome(self,db,eid,g,external=None):
        old=db.execute('SELECT fingerprint FROM genomes WHERE experiment_id=? AND id=?',(eid,g.id)).fetchone()
        if old:
            if old[0]!=g.fingerprint:raise ValueError('genome identity conflict')
            return
        meta=g.record();meta.pop('parameters');meta.pop('layers');meta.pop('activations')
        db.execute('INSERT INTO genomes VALUES(?,?,?,?,?,?,?,?)',(eid,g.id,encode(g.layers),encode(g.activations),None if external else g.parameters.tobytes(),encode(meta),g.fingerprint,encode(external) if external else None))
        if g.parent_id:
            db.execute('INSERT INTO parents VALUES(?,?,?)',(eid,g.id,g.parent_id))

    def genome(self,eid,nid):
        rows=self.query('SELECT * FROM genomes WHERE experiment_id=? AND id=?',(eid,nid))
        if not rows:raise KeyError(f'unknown genome {eid}/{nid}')
        row=rows[0];blob=row['genes']
        if blob is None:
            ext=json.loads(row['external']);path=Path(ext['path'])
            db=historical_connection(path)
            try:
                source=db.execute('SELECT genes FROM networks WHERE world=? AND id=?',(ext['world'],nid)).fetchone()
                if source is None:raise ValueError('referenced historical genome is missing')
                blob=source[0]
            finally:db.close()
        g=Genome(layers=json.loads(row['layers']),activations=json.loads(row['activations']),parameters=np.frombuffer(blob,dtype='<f8'),**json.loads(row['metadata']))
        if g.fingerprint!=row['fingerprint']:raise ValueError('genome checksum mismatch')
        return g

    def population(self,eid,generation):
        rows=self.query('SELECT network_id FROM populations WHERE experiment_id=? AND generation=? ORDER BY slot',(eid,generation))
        return [self.genome(eid,r['network_id']) for r in rows]

    def save_checkpoint(self,db,eid,generation,state,archived):
        raw=encode(state);digest=sha256(raw.encode()).hexdigest()
        db.execute('INSERT INTO checkpoints VALUES(?,?,?,?,?,?)',(eid,generation,raw,digest,time.time(),int(archived)))
        saved=db.execute('SELECT state,checksum FROM checkpoints WHERE experiment_id=? AND generation=?',(eid,generation)).fetchone()
        if sha256(saved[0].encode()).hexdigest()!=saved[1]:raise ValueError('checkpoint write verification failed')

    def checkpoint(self,eid):
        rows=self.query('SELECT * FROM checkpoints WHERE experiment_id=? ORDER BY generation DESC LIMIT 1',(eid,))
        if not rows:return None
        r=rows[0]
        if sha256(r['state'].encode()).hexdigest()!=r['checksum']:raise ValueError('corrupt checkpoint checksum')
        state=json.loads(r['state'])
        validate_checkpoint(state)
        if state['experiment_id']!=eid or state['generation']!=r['generation']:raise ValueError('checkpoint identity mismatch')
        if len(set(state['population']))!=len(state['population']):raise ValueError('duplicate checkpoint identities')
        return state

    def initialize_checkpoint(self,eid,population,state):
        with self.transaction() as db:
            for g in population:self.put_genome(db,eid,g)
            self.save_checkpoint(db,eid,0,state,True)

    def commit_generation(self,eid,generation,population,evaluation,stats,next_population,state,config,fault=None):
        with self.transaction() as db:
            if db.execute('SELECT generation FROM experiments WHERE id=?',(eid,)).fetchone()[0]!=generation:
                raise ValueError('generation conflict: another worker or stale checkpoint')
            for g in next_population:self.put_genome(db,eid,g)
            if generation%config.execution.history_stride==0 or generation==config.generations-1:
                db.executemany('INSERT INTO populations VALUES(?,?,?,?)',[(eid,generation,k,population[int(i)].id) for k,i in enumerate(evaluation.order)])
                db.executemany('INSERT INTO fitness VALUES(?,?,?,?,?,?,?,?,?,?,?)',[(eid,generation,g.id,float(evaluation.total[i]),float(evaluation.self_play[i]),float(evaluation.bots[i]),*map(int,evaluation.counts[i]),encode({k:v[i] for k,v in evaluation.components.items()})) for i,g in enumerate(population)])
            db.execute('INSERT INTO generations VALUES(?,?,?)',(eid,generation,encode(stats)))
            if fault:fault('before_checkpoint')
            self.save_checkpoint(db,eid,generation+1,state,(generation+1)%config.execution.checkpoint_frequency==0)
            db.execute('DELETE FROM checkpoints WHERE experiment_id=? AND generation<? AND archived=0',(eid,generation+1))
            db.execute('DELETE FROM checkpoints WHERE experiment_id=? AND archived=1 AND generation NOT IN (SELECT generation FROM checkpoints WHERE experiment_id=? AND archived=1 ORDER BY generation DESC LIMIT ?)',(eid,eid,config.execution.checkpoint_retention))
            db.execute('UPDATE experiments SET generation=?,updated=? WHERE id=?',(generation+1,time.time(),eid))
            if fault:fault('before_commit')

    def stats(self,eid,start=0,limit=1000):
        return [{'generation':r['generation'],**json.loads(r['statistics'])} for r in self.query('SELECT * FROM generations WHERE experiment_id=? AND generation>=? ORDER BY generation LIMIT ?',(eid,start,limit))]

    def settings(self):
        default={'max_workers':2,'poll_seconds':1.0,'logging':'INFO','default_config':Config().model_dump(),'dashboard_refresh':1,'disk_policy':{'enabled':True,'unit':'gib','warning':5.0,'critical':2.0,'pause':1.0}}
        default.update({r['key']:json.loads(r['value']) for r in self.query('SELECT * FROM settings')});return default

    def save_settings(self,settings):
        with self.transaction() as db:
            for k,v in settings.items():db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(k,encode(v)))

    def integrity(self):
        return {'integrity':self.query('PRAGMA integrity_check'), 'foreign_keys':self.query('PRAGMA foreign_key_check'),'schema':SCHEMA_VERSION}
