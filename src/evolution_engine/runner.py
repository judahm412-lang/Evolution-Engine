"""CLI/programmatic runner; generation boundaries are transaction boundaries."""
from contextlib import contextmanager
import fcntl
import os
import time
import traceback
from . import __version__
from .config import Config
from .neural import initialize
from .randomness import streams,states,restore
from .environments import create_environment
from .evolution import reproduce,statistics
from .storage import Store

@contextmanager
def exclusive(path):
    with open(path,'a+') as f:
        try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError(f'already running: {path.name}') from None
        yield

def state_record(eid,generation,population,next_id,rngs,config,env):
    return {'format':1,'engine_version':__version__,'environment_version':env.version,'experiment_id':eid,
            'generation':generation,'population':[g.id for g in population],'next_id':next_id,
            'rng':states(rngs),'config':config.model_dump(),'environment_state':{},'pending':'evaluate_population'}

def run_experiment(root,eid,stop_after=None,fault=None):
    store=Store(root)
    # Resolve from DB before constructing any filesystem name.
    exp=store.experiment(eid);config=Config.model_validate(exp['config'])
    with exclusive(store.root/f'{eid}.lock'):
        try:
            with store.transaction() as db:
                current=db.execute('SELECT status FROM experiments WHERE id=?',(eid,)).fetchone()[0]
                if current not in ('created','queued','running','paused','failed'):raise ValueError(f'cannot execute {current}')
                db.execute("UPDATE experiments SET status='running',pid=?,error=NULL,updated=? WHERE id=?",(os.getpid(),time.time(),eid))
                store.event(db,eid,'running',f'worker pid {os.getpid()}')
            env=create_environment(config);saved=store.checkpoint(eid)
            if saved:
                if saved['environment_version']!=env.version:raise ValueError('environment version mismatch')
                prior=Config.model_validate(saved['config']).model_dump();now=config.model_dump()
                prior.pop('generations');now.pop('generations')
                if prior!=now:raise ValueError('checkpoint configuration mismatch')
                generation=saved['generation'];population=[store.genome(eid,i) for i in saved['population']]
                next_id=saved['next_id'];rngs=restore(saved['rng'])
                if generation!=exp['generation'] or len(population)!=config.population.size or next_id<=max(g.id for g in population):raise ValueError('checkpoint state mismatch')
            else:
                rngs=streams(config.seed);population=initialize(config,rngs['initialization']);generation=0;next_id=len(population)+1
                store.initialize_checkpoint(eid,population,state_record(eid,0,population,next_id,rngs,config,env))
            iterations=0
            while generation<config.generations:
                status=store.experiment(eid)['status']
                if status in ('pausing','cancelling') or (stop_after is not None and iterations>=stop_after):
                    status='cancelled' if status=='cancelling' else 'paused';break
                start=time.perf_counter();cpu=time.process_time()
                evaluation=env.evaluate(population,config,rngs['evaluation']);evaluated=time.perf_counter()
                stats=statistics(population,evaluation);analyzed=time.perf_counter()
                next_population,next_id=reproduce(population,evaluation,config,rngs['reproduction'],generation,next_id)
                reproduced=time.perf_counter()
                state=state_record(eid,generation+1,next_population,next_id,rngs,config,env)
                stats.update({'evaluation_seconds':evaluated-start,'analysis_seconds':analyzed-evaluated,
                              'reproduction_seconds':reproduced-analyzed,'compute_seconds':reproduced-start,
                              'cpu_seconds':time.process_time()-cpu})
                store.commit_generation(eid,generation,population,evaluation,stats,next_population,state,config,fault)
                population=next_population;generation+=1;iterations+=1
            else:status='completed'
            with store.transaction() as db:
                db.execute('UPDATE experiments SET status=?,pid=NULL,updated=? WHERE id=?',(status,time.time(),eid))
                store.event(db,eid,status,f'{generation} generations committed')
            return store.experiment(eid)
        except BaseException as exc:
            with store.transaction() as db:
                db.execute("UPDATE experiments SET status='failed',pid=NULL,error=?,updated=? WHERE id=?",(f'{type(exc).__name__}: {exc}',time.time(),eid))
                store.event(db,eid,'failed',traceback.format_exc())
            raise
