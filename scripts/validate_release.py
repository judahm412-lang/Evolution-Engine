"""Durable endurance and deterministic recovery evidence; never touches research inputs."""
import argparse
import hashlib
import json
import resource
import time
from pathlib import Path
from evolution_engine.config import Config
from evolution_engine.storage import Store
from evolution_engine.runner import run_experiment
from evolution_engine.research import tournament
from evolution_engine.importers import import_experiment8

def digest_rows(store,eid,query):
    digest=hashlib.sha256()
    db=store.connect()
    try:
        for row in db.execute(query,(eid,)):
            for value in row:
                digest.update(value if isinstance(value,bytes) else repr(value).encode());digest.update(b'\0')
    finally:db.close()
    return digest.hexdigest()

def run(root,output):
    store=Store(root);results={}
    for name,gens,seed,stops in [('stability_200',200,818,[]),('uninterrupted_1000',1000,20261011,[]),('recovery_1000',1000,20261011,[37,63,101,199])]:
        config=Config(name=name,generations=gens,seed=seed)
        eid=store.create(config);start=time.perf_counter();segments=[]
        for stop in stops:
            r=run_experiment(root,eid,stop_after=stop);assert r['status']=='paused';segments.append(r['generation'])
        r=run_experiment(root,eid);elapsed=time.perf_counter()-start
        assert r['status']=='completed' and r['generation']==gens
        assert store.query('SELECT COUNT(*) AS n FROM populations WHERE experiment_id=?',(eid,))[0]['n']==gens*100
        assert store.query('SELECT COUNT(*) AS n FROM genomes WHERE experiment_id=?',(eid,))[0]['n']==100+80*gens
        stats=store.stats(eid,limit=gens)
        results[name]={'id':eid,'generations':gens,'elapsed_seconds':elapsed,'pause_boundaries':segments,
            'genomes_sha256':digest_rows(store,eid,'SELECT id,genes,metadata FROM genomes WHERE experiment_id=? ORDER BY id'),
            'fitness_sha256':digest_rows(store,eid,'SELECT generation,network_id,total,self_play,bot,matches,wins,losses,draws FROM fitness WHERE experiment_id=? ORDER BY generation,network_id'),
            'peak_rss_first_mib':stats[0]['peak_rss_mib'],'peak_rss_last_mib':stats[-1]['peak_rss_mib'],
            'first_50_compute_mean':sum(x['compute_seconds'] for x in stats[:50])/min(50,gens),
            'last_50_compute_mean':sum(x['compute_seconds'] for x in stats[-50:])/min(50,gens)}
        print(name,results[name],flush=True)
    for key in ('genomes_sha256','fitness_sha256'):
        assert results['uninterrupted_1000'][key]==results['recovery_1000'][key]
    project=Path(__file__).resolve().parents[2]
    imported=import_experiment8(store,project/'experiment_08/results/networks.sqlite','A',[999])
    championship=tournament(store.population(imported,999)[:10],full_starts=True)
    results['experiment8_integration']={'id':imported,'generation':999,'entrants':10,'matches':championship['matches'],'status':'passed'}
    results['database_integrity']=store.integrity()
    assert results['database_integrity']['foreign_keys']==[]
    assert results['database_integrity']['integrity'][0]['integrity_check']=='ok'
    Path(output).write_text(json.dumps(results,indent=2)+'\n')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--data',default='runtime/endurance');parser.add_argument('--output',default='acceptance_results.json');args=parser.parse_args();run(args.data,args.output)
