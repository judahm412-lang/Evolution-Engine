"""Measured component and process benchmarks; no fabricated baseline timings."""
import json
import os
import platform
import resource
import subprocess
import sys
import time
from pathlib import Path
import numpy as np
from .config import Config
from .neural import initialize
from .environments import ordered_policies,evaluate_numpy,compiled_kernel,make_schedule,NEXT,RPS
from .evolution import reproduce,rank
from .randomness import streams
from .storage import Store,encode
from .runner import run_experiment

def measure(function,repeats=10):
    timings=[]
    for _ in range(repeats):
        t=time.perf_counter();function();timings.append(time.perf_counter()-t)
    return {'median_seconds':float(np.median(timings)),'minimum_seconds':min(timings),'repeats':repeats}

def benchmark(store,generations=40,workers=(1,2,4)):
    if not 1<=generations<=10000 or any(not 1<=w<=16 for w in workers):raise ValueError('invalid benchmark bounds')
    config=Config(generations=generations);rngs=streams(91);pop=initialize(config,rngs['initialization'])
    genes=np.stack([g.parameters for g in pop]);policies,_=ordered_policies(genes)
    orders,bots=make_schedule(100,config.environment,rngs['evaluation'])
    reference=lambda:evaluate_numpy(policies,orders,bots,23,20,.25)
    components={'inference_100x40':measure(lambda:ordered_policies(genes)),
                'numpy_tournament':measure(reference,5),
                'single_observation':measure(lambda:pop[0].forward(np.zeros(9),True),100)}
    if compiled_kernel:
        optimized=lambda:compiled_kernel(policies,orders,bots,23,20,.25,NEXT)
        t=time.perf_counter();compiled=optimized();compile_time=time.perf_counter()-t
        for a,b in zip(reference(),compiled):np.testing.assert_array_equal(a,b)
        components['compiled_first_call_seconds']=compile_time
        components['numba_tournament']=measure(optimized,20)
    evaluation=RPS().evaluate(pop,config,rngs['evaluation'],(orders,bots))
    components['selection']=measure(lambda:rank(evaluation),100)
    components['reproduction_80_children']=measure(lambda:reproduce(pop,evaluation,config,rngs['reproduction'],0,101),10)
    # Instrument durable writes externally, including SQLite commit, without changing generation histories.
    eid=store.create(Config(name='Benchmark single worker',generations=generations,seed=91))
    writes=[];checkpoints=[];original=Store.commit_generation;original_cp=Store.save_checkpoint
    def timed_commit(self,*args,**kwargs):
        start=time.perf_counter();result=original(self,*args,**kwargs);writes.append(time.perf_counter()-start);return result
    def timed_checkpoint(self,*args,**kwargs):
        start=time.perf_counter();result=original_cp(self,*args,**kwargs);checkpoints.append(time.perf_counter()-start);return result
    Store.commit_generation=timed_commit;Store.save_checkpoint=timed_checkpoint
    cpu=time.process_time();start=time.perf_counter()
    try:run_experiment(store.root,eid)
    finally:Store.commit_generation=original;Store.save_checkpoint=original_cp
    elapsed=time.perf_counter()-start;cpu=time.process_time()-cpu;stats=store.stats(eid,limit=generations)
    single={'experiment_id':eid,'generations':generations,'elapsed_seconds':elapsed,'seconds_per_generation':elapsed/generations,
            'generations_per_second':generations/elapsed,'evaluation_seconds':sum(r['evaluation_seconds'] for r in stats),
            'database_transaction_seconds':sum(writes),'checkpoint_prepare_seconds':sum(checkpoints),
            'checkpoint_note':'Serialization/checksum/INSERT including initial checkpoint; overlaps DB transaction timing; do not add.',
            'cpu_seconds':cpu,'cpu_percent_one_core':100*cpu/elapsed,'peak_rss_mib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024}
    parallel=[]
    for workers_count in workers:
        root=store.root/f'benchmark_{time.time_ns()}_{workers_count}';parallel_store=Store(root)
        ids=[parallel_store.create(Config(name=f'Worker comparison {i}',generations=generations,seed=700+i),'queued') for i in range(4)]
        t=time.perf_counter()
        proc=subprocess.run([sys.executable,'-m','evolution_engine','--data',str(root),'manager','--until-idle','--workers',str(workers_count)],capture_output=True,text=True,timeout=max(60,generations*3))
        elapsed=time.perf_counter()-t
        if proc.returncode:raise RuntimeError(proc.stderr)
        entries=[parallel_store.experiment(i) for i in ids]
        if any(e['status']!='completed' for e in entries):raise RuntimeError('benchmark worker failed')
        parallel.append({'workers':workers_count,'experiments':4,'generations_per_experiment':generations,'elapsed_seconds':elapsed,
                         'aggregate_generations_per_second':4*generations/elapsed,
                         'per_experiment_latency_seconds':[e['updated']-e['created'] for e in entries],
                         'note':'Includes process startup, queue waiting, database writes, and scheduler polling.'})
    cpu_model=next((l.split(':',1)[1].strip() for l in Path('/proc/cpuinfo').read_text().splitlines() if l.startswith('model name')),platform.processor())
    result={'time':time.time(),'hardware':{'cpu':cpu_model,'logical_cpus':os.cpu_count(),'platform':platform.platform(),'python':sys.version,'numpy':np.__version__,
                                        'memory_total':next(l for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemTotal'))},
            'configuration':config.model_dump(),'measurement_seeds':{'components':91,'single_process':91,'parallel_experiments':[700,701,702,703]},'components':components,'single_process':single,'parallel':parallel,
            'turbowarp_baseline':{'seconds_per_generation':.416,'source':'User-provided optimized 200-generation baseline; not independently rerun',
                                 'scope':'Tournament computation only; excludes some reproduction/archive overhead'},
            'comparison_caveat':'Python evaluation includes policy construction and schedule generation; the source baseline timing boundary is not fully controlled. No end-to-end TurboWarp speedup claim.'}
    with store.transaction() as db:db.execute('INSERT INTO benchmarks(created,result) VALUES(?,?)',(time.time(),encode(result)))
    return result
