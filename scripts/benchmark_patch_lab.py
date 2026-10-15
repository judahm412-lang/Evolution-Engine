"""Reproducible local laboratory benchmarks; synthetic history is labeled."""
import argparse
import json
import resource
import sqlite3
import statistics
import time
from pathlib import Path
from evolution_engine.storage import Store, encode
from evolution_engine.config import Config
from evolution_engine.lab_queries import search, family_graph
from evolution_engine.history_lab import chart_data
from evolution_engine.storage_management import storage_summary, refresh_estimates
from evolution_engine.annotations import tag_experiments
from evolution_engine.backups import create_backup
from evolution_engine.resources import ResourceSampler


def timed(fn, repeat=5):
    samples=[]
    for _ in range(repeat):
        start=time.perf_counter(); result=fn(); samples.append(time.perf_counter()-start)
    return {'median_seconds':statistics.median(samples),'samples_seconds':samples},result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--destination',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.destination.exists():raise SystemExit('Use a new benchmark destination; nothing is overwritten.')
    args.destination.mkdir(parents=True)
    source=sqlite3.connect(args.source/'engine.sqlite');target=sqlite3.connect(args.destination/'engine.sqlite')
    source.backup(target);source.close();target.close()
    store=Store(args.destination)
    real=store.query('SELECT id FROM experiments ORDER BY created LIMIT 1')[0]['id']
    champion=store.stats(real,999,1)[0]['champion_id']
    synthetic=store.create(Config(name='SYNTHETIC 100000-row chart load',generations=100000),'imported')
    with store.transaction() as db:
        db.executemany('INSERT INTO generations VALUES(?,?,?)',((synthetic,g,encode({'mean':g%97,'maximum':1000000 if g==50001 else g%113,'minimum':-(g%71),'genetic_rms':(g%79)/100,'mutation_mean':g%3})) for g in range(100000)))
        db.execute('UPDATE experiments SET generation=100000 WHERE id=?',(synthetic,))
    ids=[store.create(Config(name=f'SYNTHETIC searchable metadata {i}',seed=i)) for i in range(300)]
    out={'date':'2026-10-14','workload':{'original_run_generations':1000,'real_genomes':store.query('SELECT COUNT(*) n FROM genomes')[0]['n'],'synthetic_history_rows':100000,'synthetic_metadata_experiments':300},'limitations':'Local sequential warm-cache observations, not controlled hardware benchmarks. Synthetic aggregate rows are not evolutionary results.'}
    out['storage_measure'],_=timed(lambda:refresh_estimates(store),1)
    out['storage_summary'],_=timed(lambda:storage_summary(store))
    out['family_30_generations'],graph=timed(lambda:family_graph(store,real,champion,depth=30,limit=200))
    out['family_30_generations']['nodes']=len(graph['nodes'])
    out['search_302_experiments'],_=timed(lambda:search(store,q='searchable',limit=50))
    out['chart_100000_rows'],chart=timed(lambda:chart_data(store,synthetic,points=800,metrics=['mean','maximum','minimum']))
    assert any(r['generation']==50001 and r['maximum']==1000000 for r in chart['rows'])
    out['chart_100000_rows'].update(plotted_count=chart['plotted_count'],peak_preserved=True,experiment_id=synthetic)
    out['bulk_tag_200'],_=timed(lambda:tag_experiments(store,ids[:200],add=['benchmark']),1)
    out['bulk_tag_200']['experiments_per_second']=200/out['bulk_tag_200']['median_seconds']
    sampler=ResourceSampler()
    out['resource_uncached'],_=timed(lambda:ResourceSampler().sample(store))
    sampler.sample(store)
    out['resource_cached'],_=timed(lambda:sampler.sample(store),100)
    # Peak RSS below is the complete fresh benchmark process, an honest upper
    # bound for backup memory; it includes preceding query allocations.
    out['backup'],backup=timed(lambda:create_backup(store),1)
    out['backup'].update(database_bytes=backup['manifest']['files']['engine.sqlite']['size'],archive_bytes=backup['size'],process_peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024)
    out['backup']['database_mib_per_second']=out['backup']['database_bytes']/2**20/out['backup']['median_seconds']
    out['workspace']=str(args.destination.resolve())
    args.output.write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))

if __name__=='__main__':main()
