"""Real-process maintenance, WAL snapshot, and executor crash boundaries."""
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from evolution_engine.storage import Store, encode
from evolution_engine.coordination import MaintenanceBusy
from evolution_engine.storage_management import delete_experiments
from evolution_engine.backups import create_backup, restore_backup
from evolution_engine.jobs import Jobs
from test_core import small


def launch(code, root, *args):
    return subprocess.Popen([sys.executable, '-c', code, str(root), *args],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})


def wait_until(predicate, process=None):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if predicate():
            return
        if process and process.poll() is not None:
            raise AssertionError(process.communicate())
        time.sleep(.01)
    raise AssertionError('process boundary timed out')


def finish(process):
    out, err = process.communicate(timeout=20)
    assert process.returncode == 0, (out, err)


def test_scheduler_launch_and_delayed_child_cannot_outlive_deleted_queue(tmp_path):
    store = Store(tmp_path)
    eid = store.create(small(), 'queued')
    other = store.create(small(name='unrelated'))
    # A real scheduler launches a real worker, paused before the worker acquires
    # its gate. First hold Popen's return inside the scheduler's shared gate;
    # then hold the scheduler outside that gate at its ordinary polling boundary.
    code = '''
import sys,time,subprocess
from pathlib import Path
import evolution_engine.manager as manager
root=Path(sys.argv[1]); original= subprocess.Popen
def spawn(*args,**kwargs):
    child="import sys,time; from pathlib import Path; from evolution_engine.runner import run_experiment; r=Path(sys.argv[1]); " + \
          "exec('while not (r/\\\"child-release\\\").exists(): time.sleep(.01)'); run_experiment(r,sys.argv[2],scheduled=True)"
    p=original([sys.executable,'-c',child,str(root),sys.argv[2]],**kwargs)
    (root/'launched').touch()
    while not (root/'scheduler-release').exists(): time.sleep(.01)
    return p
original_sleep=time.sleep
def boundary(seconds):
    (root/'outside-gate').touch()
    while not (root/'child-release').exists(): original_sleep(.01)
    original_sleep(.02)
manager.subprocess.Popen=spawn
manager.time.sleep=boundary
# spawn must use the unpatched wait while it holds the launch gate.
spawn.__globals__['time']=type('Clock',(),{'sleep':staticmethod(original_sleep)})
manager.scheduler(root,until_idle=True)
'''
    proc = launch(code, tmp_path, eid)
    try:
        wait_until(lambda: (tmp_path/'launched').exists(), proc)
        with pytest.raises(MaintenanceBusy):
            delete_experiments(store, [eid], [eid], True)
        (tmp_path/'scheduler-release').touch()
        wait_until(lambda: (tmp_path/'outside-gate').exists(), proc)
        delete_experiments(store, [eid], [eid], True)
        (tmp_path/'child-release').touch()
        finish(proc)
        assert [r['id'] for r in store.query('SELECT id FROM experiments')] == [other]
        assert not store.query('PRAGMA foreign_key_check')
    finally:
        (tmp_path/'scheduler-release').touch()
        (tmp_path/'child-release').touch()
        if proc.poll() is None:
            proc.kill(); proc.communicate()


def test_live_worker_wal_backup_and_maintenance_rejection(tmp_path):
    store = Store(tmp_path/'source')
    eid = store.create(small(generations=300))
    code = '''
import sys,time
from pathlib import Path
from evolution_engine.storage import Store
from evolution_engine.runner import run_experiment
root=Path(sys.argv[1]); store=Store(root)
# Keep the connection open so committed transactions remain in a live WAL.
connection=store.connect(); connection.execute('PRAGMA wal_autocheckpoint=0')
connection.execute('SELECT COUNT(*) FROM experiments').fetchone()
import evolution_engine.runner as runner
evaluate=runner.statistics
def slower(*args,**kwargs):
    if store.experiment(sys.argv[2])['generation']>=2:
        (root/'worker-ready').touch()
        while not (root/'worker-release').exists(): time.sleep(.01)
    return evaluate(*args,**kwargs)
runner.statistics=slower
run_experiment(root,sys.argv[2])
connection.close()
'''
    proc = launch(code, store.root, eid)
    try:
        wait_until(lambda: (store.root/'worker-ready').exists(), proc)
        assert store.experiment(eid)['status'] == 'running'
        assert Path(str(store.path)+'-wal').stat().st_size > 0
        with pytest.raises(MaintenanceBusy):
            delete_experiments(store, [eid], [eid], True)
        backup = create_backup(store)
        restored = tmp_path/'restored'
        restore_backup(store.root/'backups'/backup['filename'], restored)
        snapshot = Store(restored)
        assert snapshot.experiment(eid)['status'] == 'paused'
        assert snapshot.experiment(eid)['generation'] >= 2
        assert snapshot.checkpoint(eid)['generation'] == snapshot.experiment(eid)['generation']
        assert not snapshot.query('PRAGMA foreign_key_check')
        (store.root/'worker-release').touch()
        finish(proc)
        assert store.experiment(eid)['status'] == 'completed'
    finally:
        (store.root/'worker-release').touch()
        if proc.poll() is None:
            proc.kill(); proc.communicate()


def test_executor_hard_exit_recovers_as_interrupted(tmp_path):
    store = Store(tmp_path)
    now = time.time()
    with store.transaction() as db:
        db.execute('INSERT INTO jobs(id,kind,status,request,created,updated) VALUES(?,?,?,?,?,?)',
                   ('crash-test', 'backup', 'queued', encode({}), now, now))
    code = '''
import os,sys
from evolution_engine.storage import Store
from evolution_engine.jobs import Jobs
jobs=Jobs(Store(sys.argv[1]))
jobs.execute=lambda *args: os._exit(9)
jobs.run()
'''
    proc = launch(code, tmp_path)
    proc.communicate(timeout=15)
    assert proc.returncode == 9
    assert store.query('SELECT status FROM jobs')[0]['status'] == 'running'
    Jobs(store).run()
    row = store.query('SELECT * FROM jobs')[0]
    assert row['status'] == 'interrupted' and row['result'] is None
    assert 'retry explicitly' in row['error']
