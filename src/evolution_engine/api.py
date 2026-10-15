"""Loopback-only research API, same-origin mutations, bounded queries."""
import asyncio
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit
from typing import Literal
from fastapi import FastAPI,HTTPException,Request,Query
from fastapi.responses import FileResponse,JSONResponse,Response,StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from .config import Config,Model
from .storage import Store,encode
from . import __version__
from .research import inspect,lineage,tournament,save_tournament,export_result,population_analysis,run_metrics
from .manager import enqueue
from .resources import DiskPolicy

class Action(Model):
    action: Literal['start','pause','resume','cancel','stop']
    generations: int | None=Field(None,ge=1,le=1000000)

class Entrant(Model):
    experiment_id: str=Field(pattern=r'^[A-Za-z0-9_-]{1,80}$')
    network_id: int=Field(ge=1)

class TournamentRequest(Model):
    entrants: list[Entrant]=Field(min_length=2,max_length=100)
    rounds: int=Field(23,ge=1,le=1000)
    repeats: int=Field(1,ge=1,le=100)
    full_starts: bool=False
    opponents: list[Literal['cycle','reverse','rrp','uniform','copycat','anti_copycat','frequency','transition','noisy_cycle','reactive']]=Field(default_factory=lambda:['cycle','reverse','rrp'],max_length=10)
    seed: int=Field(8,ge=0,le=2**53-1)

class InspectorRequest(Model):
    observations: list[float]=Field(min_length=1,max_length=1024)

class Settings(Model):
    max_workers: int=Field(2,ge=1,le=16)
    poll_seconds: float=Field(.5,ge=.05,le=1)
    logging: Literal['DEBUG','INFO','WARNING']='INFO'
    default_config: Config=Field(default_factory=Config)
    dashboard_refresh: int=Field(1,ge=1,le=30)
    disk_policy: DiskPolicy=Field(default_factory=DiskPolicy)

class Sweep(Model):
    config: Config
    bot_weights: list[float]=Field(min_length=1,max_length=20)

def create_app(root):
    store=Store(root);app=FastAPI(title='Evolution Engine',version=__version__,docs_url=None,redoc_url=None)
    web=Path(__file__).parent/'web';app.state.store=store

    @app.middleware('http')
    async def local_only(request,call_next):
        host=request.headers.get('host','').split(':')[0]
        # IPv6 literal contains colons; normalize with urlsplit.
        hostname=urlsplit('http://'+request.headers.get('host','')).hostname
        if hostname not in ('127.0.0.1','localhost','::1','testserver'):
            return JSONResponse({'detail':'loopback Host required'},status_code=403)
        if request.client and request.client.host not in ('127.0.0.1','::1','testclient'):
            return JSONResponse({'detail':'loopback clients only'},status_code=403)
        origin=request.headers.get('origin')
        if origin and urlsplit(origin).netloc!=request.headers.get('host'):
            return JSONResponse({'detail':'same-origin requests required'},status_code=403)
        if request.method in ('POST','PUT','PATCH','DELETE'):
            if request.headers.get('x-evolution-client')!='dashboard':
                return JSONResponse({'detail':'X-Evolution-Client: dashboard required'},status_code=403)
            try:size=int(request.headers.get('content-length','0'))
            except ValueError:return JSONResponse({'detail':'invalid content length'},status_code=400)
            if size<0 or size>200000:
                return JSONResponse({'detail':'request too large'},status_code=413)
            chunks=[];actual=0
            async for chunk in request.stream():
                actual+=len(chunk)
                if actual>200000:return JSONResponse({'detail':'request too large'},status_code=413)
                chunks.append(chunk)
            request._body=b''.join(chunks)
        response=await call_next(request)
        # Revalidate local assets after upgrades; nested ES modules can otherwise
        # retain a previous patch's cached behavior across ordinary reloads.
        if request.url.path=='/' or request.url.path.startswith('/assets/'):
            response.headers['Cache-Control']='no-cache'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'"
        return response

    @app.exception_handler(ValueError)
    async def bad_value(request,exc):return JSONResponse({'detail':str(exc)},status_code=400)
    @app.exception_handler(KeyError)
    async def missing(request,exc):return JSONResponse({'detail':str(exc)},status_code=404)

    @app.get('/')
    def home():return FileResponse(web/'index.html')

    @app.get('/api/system')
    def system():
        import shutil
        from .manager import worker_active
        rows=store.query('SELECT status,COUNT(*) AS count FROM experiments GROUP BY status')
        active=store.query("SELECT id,generation FROM experiments WHERE status='running'")
        rates=[run_metrics(store,r['id'])['generations_per_second'] or 0 for r in active]
        return {'version':__version__,'states':{r['status']:r['count'] for r in rows},'cpu_count':os.cpu_count(),
                'aggregate_generations_per_second':sum(rates),'completed_generations':store.query('SELECT SUM(generation) AS n FROM experiments')[0]['n'] or 0,
                'failures':store.query("SELECT id,name,status,error FROM experiments WHERE error IS NOT NULL ORDER BY updated DESC LIMIT 5"),
                'load_average':list(os.getloadavg()),'disk_free_bytes':shutil.disk_usage(store.root).free,
                'database_bytes':store.path.stat().st_size,'storage_root':str(store.root),'settings':store.settings()}

    @app.get('/api/experiments')
    def experiments(limit:int=Query(100,ge=1,le=200),offset:int=Query(0,ge=0),search:str='',status:str='',environment:str='',since:float=0,min_generation:int=0,min_fitness:float|None=None):
        clause=' WHERE (name LIKE ? OR config LIKE ?) AND status LIKE ? AND config LIKE ? AND created>=? AND generation>=?'
        args=[f'%{search}%',f'%{search}%',status or '%',f'%"type":"{environment}"%' if environment else '%',since,min_generation]
        if min_fitness is not None:
            clause+=' AND id IN (SELECT experiment_id FROM fitness GROUP BY experiment_id HAVING MAX(total)>=?)';args.append(min_fitness)
        rows=store.query('SELECT * FROM experiments'+clause+' ORDER BY created DESC LIMIT ? OFFSET ?',(*args,limit,offset))
        for r in rows:
            r['config']=json.loads(r['config']);r['seed_text']=str(r['config']['seed'])
        return {'items':rows,'total':store.query('SELECT COUNT(*) AS n FROM experiments'+clause,args)[0]['n']}

    @app.post('/api/experiments')
    def create(config:Config):
        if config.replicates>1:
            ids=enqueue(store,config);return {'id':ids[0],'ids':ids}
        return {'id':store.create(config)}

    @app.post('/api/sweeps')
    def sweep(body:Sweep):return {'ids':enqueue(store,body.config,body.bot_weights)}

    @app.get('/api/templates')
    def templates():return {'compatibility':Config().model_dump(),'four_worlds':{'config':Config().model_dump(),'bot_weights':[0,.1,.25,1]}}

    @app.get('/api/experiments/{eid}')
    def experiment(eid:str):
        e=store.experiment(eid)
        return {**e,'seed_text':str(e['config']['seed']),'metrics':run_metrics(store,eid)}

    @app.post('/api/experiments/{eid}/control')
    def control(eid:str,action:Action):return store.command(eid,action.action,action.generations)

    @app.get('/api/experiments/{eid}/stats')
    def stats(eid:str,start:int=Query(0,ge=0),limit:int=Query(1000,ge=1,le=2000)):
        store.experiment(eid);return store.stats(eid,start,limit)

    @app.get('/api/experiments/{eid}/population/{generation}')
    def population(eid:str,generation:int,limit:int=Query(100,ge=1,le=200),offset:int=Query(0,ge=0)):
        return store.query('SELECT p.slot,p.network_id,f.total,f.self_play,f.bot,g.metadata FROM populations p JOIN fitness f ON p.experiment_id=f.experiment_id AND p.generation=f.generation AND p.network_id=f.network_id JOIN genomes g ON g.experiment_id=p.experiment_id AND g.id=p.network_id WHERE p.experiment_id=? AND p.generation=? ORDER BY f.total DESC,p.slot LIMIT ? OFFSET ?',(eid,generation,limit,offset))

    @app.get('/api/experiments/{eid}/genomes/{nid}')
    def genome(eid:str,nid:int):return inspect(store,eid,nid)

    @app.post('/api/experiments/{eid}/genomes/{nid}/evaluate')
    def evaluate(eid:str,nid:int,body:InspectorRequest):return inspect(store,eid,nid,body.observations)

    @app.get('/api/experiments/{eid}/genomes/{nid}/lineage')
    def ancestry(eid:str,nid:int,depth:int=Query(30,ge=1,le=200)):return lineage(store,eid,nid,depth)

    @app.get('/api/experiments/{eid}/analysis/{generation}')
    def analysis(eid:str,generation:int):return population_analysis(store,eid,generation)

    @app.get('/api/experiments/{eid}/distance')
    def distance(eid:str,a:int,b:int):
        from .neural import genetic_distance
        ga,gb=store.genome(eid,a),store.genome(eid,b)
        rms=genetic_distance(ga,gb)
        return {'rms':rms,'changed_parameters':int((ga.parameters!=gb.parameters).sum())}

    @app.get('/api/experiments/{eid}/checkpoints')
    def checkpoints(eid:str):return store.query('SELECT generation,checksum,created,archived FROM checkpoints WHERE experiment_id=? ORDER BY generation DESC LIMIT 200',(eid,))

    @app.get('/api/experiments/{eid}/events')
    def events(eid:str,after:int=Query(0,ge=0)):return store.query('SELECT * FROM events WHERE experiment_id=? AND id>? ORDER BY id LIMIT 200',(eid,after))

    @app.get('/api/experiments/{eid}/export/{kind}')
    def export(eid:str,kind:str,generation:int|None=None,compressed:bool=False):
        data,mime,name=export_result(store,eid,kind,generation)
        if compressed:
            from .research import compress_export
            data,mime,name=compress_export(data,mime,name)
        return Response(data,media_type=mime,headers={'Content-Disposition':f'attachment; filename="{name}"'})

    @app.post('/api/tournaments')
    def championship(body:TournamentRequest):
        refs=[(e.experiment_id,e.network_id) for e in body.entrants]
        if len(set(refs))!=len(refs):raise ValueError('duplicate tournament entrants')
        result=tournament([store.genome(*ref) for ref in refs],body.rounds,body.repeats,body.full_starts,body.opponents,body.seed)
        result['entrants']=[e.model_dump() for e in body.entrants];result['analysis_id']=save_tournament(store,result);return result

    @app.get('/api/tournaments')
    def tournaments():return store.query("SELECT id,created,kind FROM analyses ORDER BY id DESC LIMIT 100")

    @app.get('/api/tournaments/{tid}')
    def saved_tournament(tid:int):
        rows=store.query('SELECT result FROM analyses WHERE id=?',(tid,))
        if not rows:raise KeyError(tid)
        return {**json.loads(rows[0]['result']),'analysis_id':tid}

    @app.get('/api/tournaments/{tid}/export')
    def export_tournament(tid:int):
        data=json.dumps(saved_tournament(tid),indent=2,allow_nan=False)
        return Response(data,media_type='application/json',headers={'Content-Disposition':f'attachment; filename="tournament-{tid}.json"'})

    @app.get('/api/benchmarks')
    def benchmarks():return [{'id':r['id'],'created':r['created'],'result':json.loads(r['result'])} for r in store.query('SELECT * FROM benchmarks ORDER BY id DESC LIMIT 20')]

    @app.get('/api/settings')
    def settings():return {**store.settings(),'storage_root':str(store.root)}

    @app.put('/api/settings')
    def update_settings(body:Settings):store.save_settings(body.model_dump(exclude_unset=True));return store.settings()

    @app.get('/api/events')
    async def live(request:Request):
        async def stream():
            previous=None
            while not await request.is_disconnected():
                rows=store.query('SELECT id,status,generation,updated,error FROM experiments ORDER BY updated DESC LIMIT 200');raw=encode(rows)
                if raw!=previous:yield 'data: '+raw+'\n\n';previous=raw
                else:yield ': heartbeat\n\n'
                await asyncio.sleep(store.settings()['dashboard_refresh'])
        return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache'})

    from .lab_api import install
    install(app,store)
    app.mount('/assets',StaticFiles(directory=web),name='assets')
    return app
