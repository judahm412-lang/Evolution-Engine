"""Stable module and console entry points; paths are independent of launch CWD."""
import argparse
import json
import logging
import os
from pathlib import Path
from .config import Config,load_config
from .storage import Store

def main():
    parser=argparse.ArgumentParser(prog='evolution-engine')
    parser.add_argument('--data',default=os.environ.get('EVOLUTION_DATA',str(Path.home()/'.local/share/evolution-engine')))
    sub=parser.add_subparsers(dest='command',required=True)
    run=sub.add_parser('run');run.add_argument('config');run.add_argument('--enqueue',action='store_true');run.add_argument('--sweep',type=float,nargs='+')
    sub.add_parser('list')
    sub.add_parser('backup')
    p=sub.add_parser('verify-backup');p.add_argument('archive')
    p=sub.add_parser('restore');p.add_argument('archive');p.add_argument('--destination',required=True)
    for name in ('start','pause','resume','cancel','stop'):
        p=sub.add_parser(name);p.add_argument('id');p.add_argument('--generations',type=int)
    p=sub.add_parser('worker');p.add_argument('id')
    p=sub.add_parser('manager');p.add_argument('--until-idle',action='store_true');p.add_argument('--workers',type=int,choices=range(1,17))
    p=sub.add_parser('serve');p.add_argument('--host',default='127.0.0.1',choices=['127.0.0.1','localhost','::1']);p.add_argument('--port',default=8765,type=int)
    p=sub.add_parser('export');p.add_argument('id');p.add_argument('--kind',default='summary',choices=['summary','statistics','config','population','champion','analysis']);p.add_argument('--generation',type=int);p.add_argument('--output',required=True);p.add_argument('--compress',action='store_true')
    p=sub.add_parser('inspect');p.add_argument('id');p.add_argument('network',type=int)
    p=sub.add_parser('tournament');p.add_argument('id');p.add_argument('--generation',type=int);p.add_argument('--rounds',default=23,type=int);p.add_argument('--full-starts',action='store_true');p.add_argument('--opponents',nargs='+',default=['cycle','reverse','rrp']);p.add_argument('--seed',type=int,default=8)
    p=sub.add_parser('import-e8');p.add_argument('path');p.add_argument('--world',required=True);p.add_argument('--generations',nargs='+',type=int)
    p=sub.add_parser('import-archive');p.add_argument('path');p.add_argument('--name',required=True);p.add_argument('--population-size',type=int,default=100);p.add_argument('--prefix');p.add_argument('--start-generation',type=int,default=0)
    p=sub.add_parser('benchmark');p.add_argument('--generations',type=int,default=40);p.add_argument('--workers',type=int,nargs='+',default=[1,2,4]);p.add_argument('--output')
    p=sub.add_parser('check');p.add_argument('id',nargs='?')
    args=parser.parse_args()
    if args.command in ('verify-backup','restore'):
        from .backups import verify_backup,restore_backup
        result=verify_backup(args.archive) if args.command=='verify-backup' else restore_backup(args.archive,args.destination)
        print(json.dumps(result,indent=2,allow_nan=False));return
    store=Store(args.data);result=None
    logging.basicConfig(level=store.settings()['logging'],format='%(asctime)s %(levelname)s %(message)s')
    if args.command=='backup':
        from .backups import create_backup
        result=create_backup(store)
    elif args.command=='run':
        from .manager import enqueue,ensure_scheduler
        from .runner import run_experiment
        c=load_config(args.config)
        if args.enqueue or c.replicates>1 or args.sweep:
            result=enqueue(store,c,args.sweep);ensure_scheduler(store.root)
        else:
            eid=store.create(c);result=run_experiment(store.root,eid)
    elif args.command=='list':result=store.list()
    elif args.command in ('start','resume','pause','cancel','stop'):
        result=store.command(args.id,args.command,args.generations)
        if args.command in ('start','resume'):
            from .manager import ensure_scheduler
            ensure_scheduler(store.root)
    elif args.command=='worker':
        from .runner import run_experiment
        result=run_experiment(store.root,args.id,scheduled=True)
    elif args.command=='manager':
        from .manager import scheduler
        if args.workers:store.save_settings({'max_workers':args.workers})
        scheduler(store.root,args.until_idle)
    elif args.command=='serve':
        import uvicorn
        from .api import create_app
        from .manager import ensure_scheduler
        ensure_scheduler(store.root)
        uvicorn.run(create_app(store.root),host=args.host,port=args.port,log_level=store.settings()['logging'].lower())
    elif args.command=='export':
        from .research import export_result
        content,mime,name=export_result(store,args.id,args.kind,args.generation)
        if args.compress or (store.experiment(args.id)['config']['storage']['export_compression'] and args.output.endswith('.gz')):
            from .research import compress_export
            content,_,_=compress_export(content,mime,name)
        Path(args.output).write_bytes(content)
        result={'output':str(Path(args.output).resolve())}
    elif args.command=='inspect':
        from .research import inspect
        result=inspect(store,args.id,args.network)
    elif args.command=='tournament':
        from .research import tournament,save_tournament
        gen=store.experiment(args.id)['generation']-1 if args.generation is None else args.generation
        result=tournament(store.population(args.id,gen),args.rounds,full_starts=args.full_starts,opponents=args.opponents,seed=args.seed);save_tournament(store,result)
    elif args.command=='import-e8':
        from .importers import import_experiment8
        result=import_experiment8(store,args.path,args.world,args.generations)
    elif args.command=='import-archive':
        from .importers import import_archive
        result=import_archive(store,args.path,args.name,args.population_size,args.prefix,args.start_generation)
    elif args.command=='benchmark':
        from .benchmark import benchmark
        result=benchmark(store,args.generations,args.workers)
        if args.output:Path(args.output).write_text(json.dumps(result,indent=2)+'\n')
    elif args.command=='check':
        result=store.integrity()
        if args.id:result['checkpoint']=store.checkpoint(args.id)
    if result is not None:print(json.dumps(result,indent=2,allow_nan=False))
