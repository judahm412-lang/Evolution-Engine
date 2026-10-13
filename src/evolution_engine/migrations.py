"""Metadata-only, transactional migrations; no scientific rows are rewritten."""
SCHEMA_VERSION = 3
STATEMENTS_V3 = [
    '''CREATE TABLE IF NOT EXISTS notes(experiment_id TEXT PRIMARY KEY REFERENCES experiments(id), content TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS tags(name TEXT PRIMARY KEY)''',
    '''CREATE TABLE IF NOT EXISTS experiment_tags(experiment_id TEXT REFERENCES experiments(id),tag TEXT REFERENCES tags(name),PRIMARY KEY(experiment_id,tag))''',
    '''CREATE TABLE IF NOT EXISTS bookmarks(id INTEGER PRIMARY KEY,experiment_id TEXT REFERENCES experiments(id),kind TEXT NOT NULL,reference TEXT NOT NULL,name TEXT NOT NULL,notes TEXT NOT NULL,tags TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS baskets(id TEXT PRIMARY KEY,name TEXT NOT NULL,entrants TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS milestones(id INTEGER PRIMARY KEY,experiment_id TEXT NOT NULL REFERENCES experiments(id),generation INTEGER NOT NULL,kind TEXT NOT NULL,value REAL,provenance TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'candidate',notes TEXT NOT NULL DEFAULT '',created REAL NOT NULL,UNIQUE(experiment_id,generation,kind))''',
    '''CREATE TABLE IF NOT EXISTS repetitions(experiment_id TEXT PRIMARY KEY REFERENCES experiments(id),source_id TEXT NOT NULL,seed_mode TEXT NOT NULL,created REAL NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS research_groups(experiment_id TEXT PRIMARY KEY REFERENCES experiments(id),name TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS storage_estimates(experiment_id TEXT PRIMARY KEY REFERENCES experiments(id),generation INTEGER NOT NULL,measured REAL NOT NULL,details TEXT NOT NULL,logical_bytes INTEGER NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS storage_measurements(id INTEGER PRIMARY KEY,time REAL NOT NULL,physical_bytes INTEGER NOT NULL,workspace_bytes INTEGER NOT NULL,free_bytes INTEGER NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS backups(id TEXT PRIMARY KEY,created REAL NOT NULL,filename TEXT NOT NULL,manifest TEXT NOT NULL,size INTEGER NOT NULL,checksum TEXT NOT NULL,verified REAL)''',
    '''CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,kind TEXT NOT NULL,status TEXT NOT NULL,progress REAL NOT NULL DEFAULT 0,request TEXT NOT NULL,result TEXT,error TEXT,created REAL NOT NULL,updated REAL NOT NULL)''',
    '''CREATE INDEX IF NOT EXISTS experiment_order ON experiments(created,id)''',
    '''CREATE INDEX IF NOT EXISTS experiment_status ON experiments(status,created)''',
    '''CREATE INDEX IF NOT EXISTS events_lookup ON events(experiment_id,time,id)''',
    '''CREATE INDEX IF NOT EXISTS tag_lookup ON experiment_tags(tag,experiment_id)''',
    '''CREATE INDEX IF NOT EXISTS bookmarks_lookup ON bookmarks(experiment_id,created)''',
    '''CREATE INDEX IF NOT EXISTS milestone_lookup ON milestones(experiment_id,generation)''',
    '''CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status,created)''',
]

def migrate_metadata(db, fault=None):
    for index, statement in enumerate(STATEMENTS_V3):
        db.execute(statement)
        if fault:
            fault(index)
    db.execute('PRAGMA user_version=3')
