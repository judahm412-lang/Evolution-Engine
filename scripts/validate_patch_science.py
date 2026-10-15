"""Run the actual stable wheel then upgrade and compare 1,000 generations."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import resource
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT=Path(__file__).resolve().parents[1]
def digest(root,table,columns,order):
    db=sqlite3.connect(Path(root)/'engine.sqlite');h=hashlib.sha256()
    for row in db.execute(f'SELECT {columns} FROM {table} ORDER BY {order}'):
        for value in row:
            data=value if isinstance(value,bytes) else json.dumps(value,separators=(',',':')).encode()
            h.update(len(data).to_bytes(8,'little'));h.update(data)
    db.close();return h.hexdigest()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--destination',type=Path,default=ROOT/'runtime/v201-science')
    parser.add_argument('--output',type=Path,default=ROOT/'v2_0_1_scientific_validation.json')
    args=parser.parse_args()
    destination=args.destination;destination.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='stable-engine-') as td:
        package=Path(td)
        with zipfile.ZipFile(ROOT/'dist/evolution_engine-2.0.0-py3-none-any.whl') as source:source.extractall(package)
        code='''
import json,sys,time
from evolution_engine import __version__
from evolution_engine.storage import Store
from evolution_engine.config import Config
from evolution_engine.runner import run_experiment
assert __version__=='2.0.0'
s=Store(sys.argv[1]);c=Config(generations=1000,seed=20261011)
eid=s.create(c);start=time.perf_counter();run_experiment(s.root,eid,stop_after=int(sys.argv[2]) or None)
print(json.dumps({'experiment':eid,'seconds':time.perf_counter()-start,'version':__version__}))
'''
        env={**os.environ,'PYTHONPATH':str(package),'PYTHONDONTWRITEBYTECODE':'1','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1'}
        results={}
        for name,stop in [('stable-uninterrupted',0),('stable-paused',364)]:
            root=destination/name
            if root.exists():raise RuntimeError(f'Use a fresh destination; {root} already exists')
            results[name]=json.loads(subprocess.check_output([sys.executable,'-c',code,str(root),str(stop)],cwd=td,env=env,text=True))
        from evolution_engine.storage import Store
        from evolution_engine.runner import run_experiment
        from evolution_engine.config import Config
        from evolution_engine.annotations import save_notes,tag_experiments
        root=destination/'stable-paused';s=Store(root);eid=results['stable-paused']['experiment'];checkpoint=s.checkpoint(eid)
        assert checkpoint['engine_version']=='2.0.0' and 'scientific_engine' not in checkpoint
        save_notes(s,eid,{'hypothesis':'Annotations between versions must not alter any scientific trajectory.'});tag_experiments(s,[eid],['upgraded','determinism'])
        start=time.perf_counter();run_experiment(root,eid);results['upgraded-resume']={'seconds':time.perf_counter()-start,'starting_generation':364}
        fresh=destination/'patch-uninterrupted';s=Store(fresh);eid=s.create(Config(generations=1000,seed=20261011));start=time.perf_counter();run_experiment(fresh,eid)
        results['patch-uninterrupted']={'seconds':time.perf_counter()-start,'experiment':eid}
        cols={'genomes':('id,genes,metadata,fingerprint','id'),'fitness':('generation,network_id,total,self_play,bot,matches,wins,losses,draws','generation,network_id')}
        hashes={name:{table:digest(destination/name,table,*spec) for table,spec in cols.items()} for name in ('stable-uninterrupted','stable-paused','patch-uninterrupted')}
        assert hashes['stable-uninterrupted']==hashes['stable-paused']==hashes['patch-uninterrupted']
        rng=[]
        for name in hashes:
            db=sqlite3.connect(destination/name/'engine.sqlite');rng.append(json.loads(db.execute('SELECT state FROM checkpoints ORDER BY generation DESC LIMIT 1').fetchone()[0])['rng']);db.close()
        assert rng[0]==rng[1]==rng[2]
        result={'comparison':'Actual v2.0.0 wheel uninterrupted vs actual v2.0.0 pause at 364 upgraded with notes/tags vs v2.0.1 development uninterrupted','generations':1000,'seed_text':'20261011','matches':True,'hash_encoding':'length-prefixed JSON scalars / raw BLOB bytes','boundaries':['all genome identities, parameter bytes, mutation metadata, fingerprints','all retained per-network fitness/counts for every generation','final three PCG64 states'],'excluded':['elapsed timing and memory statistics','timestamps and experiment IDs','application metadata'],'hashes':hashes,'timings':results,'peak_rss_mib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024}
        args.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
