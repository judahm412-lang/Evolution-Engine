"""Research laboratory API; inherits the application's loopback and origin guard."""
from typing import Annotated,Literal
import json
from fastapi import APIRouter,Query
from fastapi.responses import FileResponse,Response
from pydantic import Field
from .config import Model,Config
from .annotations import (notes,save_notes,tag_experiments,repeat,save_bookmark,baskets,save_basket,config_diff,RETENTION_PRESETS)
from .lab_queries import search,family_graph,genetic_comparison
from .history_lab import chart_data,replay_frame,timeline,METRICS
from .storage_management import storage_summary,deletion_preview
from .resources import ResourceSampler
from .jobs import Jobs

Identifier=Annotated[str,Field(pattern=r'^[A-Za-z0-9_-]{1,80}$')]
Ids=Annotated[list[Identifier],Field(min_length=1,max_length=200)]
Tag=Annotated[str,Field(min_length=1,max_length=60)]

class NoteRequest(Model):
    content: dict[str,str]
class TagsRequest(Model):
    ids: Ids
    add: list[Tag]=Field(default_factory=list,max_length=30)
    remove: list[Tag]=Field(default_factory=list,max_length=30)
    group: str|None=Field(None,max_length=120)
class RepeatRequest(Model):
    seed_mode: Literal['same','fresh']='same'
    start: bool=False
    preset: Literal['detailed','balanced','compact']|None=None
class BookmarkRequest(Model):
    experiment_id: Identifier|None=None
    kind: Literal['experiment','generation','network','champion','branch','tournament','event']
    reference: dict[str,int]=Field(default_factory=dict,max_length=4)
    name: str=Field(min_length=1,max_length=200)
    notes: str=Field('',max_length=16000)
    tags: list[Tag]=Field(default_factory=list,max_length=30)
class BasketEntrant(Model):
    experiment_id: Identifier
    network_id: int=Field(ge=1,le=2**63-1)
class BasketRequest(Model):
    name: str=Field(min_length=1,max_length=120)
    entrants: list[BasketEntrant]=Field(max_length=100)
class DeleteRequest(Model):
    ids: Ids
    confirm: Ids
    acknowledge_no_backup: bool=False
    remove_analyses: bool=False
class Selection(Model):
    ids: Ids
class EmptyRequest(Model):
    pass
class VerifyRequest(Model):
    backup_id: Identifier
class ReportRequest(Model):
    experiment_id: Identifier
    include_weights: bool=False
    include_lineage: bool=False
class ExportRequest(Selection):
    kind: Literal['summary','statistics','config','population','champion','analysis']='summary'
    generation: int|None=Field(None,ge=0,le=1000000)
class ExactSweep(Model):
    config: dict
    bot_weights: list[float]=Field(min_length=1,max_length=20)

class MilestoneConfig(Model):
    record_high: bool=True
    fitness_threshold: float|None=None
    fitness_increase: float|None=Field(None,gt=0)
    diversity_threshold: float|None=Field(None,ge=0)
    mutation_change: float|None=Field(None,gt=0)
    champion_duration: int=Field(20,ge=2,le=1000000)
class MilestoneRequest(Model):
    experiment_id: Identifier
    config: MilestoneConfig=Field(default_factory=MilestoneConfig)
class MilestoneReview(Model):
    status: Literal['candidate','confirmed','dismissed']
    notes: str=Field('',max_length=16000)
class LineageRequest(Model):
    eid: Identifier
    nid: int=Field(ge=1,le=2**63-1)
    direction: Literal['ancestors','descendants']='ancestors'
    depth: int=Field(4,ge=1,le=30)
    limit: int=Field(100,ge=2,le=200)
class JobRequest(Model):
    kind: Literal['backup','verify_backup','storage_measure','reclaim','delete','tags','milestones','report','export','lineage']
    parameters: dict=Field(default_factory=dict)
class CreateRequest(Model):
    config: dict
    preset: Literal['detailed','balanced','compact']|None=None

def install(app,store):
    router=APIRouter(prefix='/api/lab');jobs=Jobs(store);sampler=ResourceSampler();app.state.jobs=jobs
    specs={'backup':EmptyRequest,'reclaim':EmptyRequest,'storage_measure':EmptyRequest,'verify_backup':VerifyRequest,'delete':DeleteRequest,'tags':TagsRequest,'report':ReportRequest,'export':ExportRequest,'lineage':LineageRequest,'milestones':MilestoneRequest}

    @router.get('/search')
    def find(q:str=Query('',max_length=500),status:str='',environment:str='',tags:list[str]=Query(default=[]),group:str='',seed:str=Query('',max_length=20),origin:str='',since:float=0,until:float=1e20,min_generation:int=Query(0,ge=0),max_generation:int=Query(1000000,ge=0),min_fitness:float|None=None,max_fitness:float|None=None,min_size:int|None=Query(None,ge=0),max_size:int|None=Query(None,ge=0),sort:Literal['date','name','generation','size','status']='date',descending:bool=True,limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0)):
        if len(tags)>30:raise ValueError('at most 30 tag filters')
        return search(store,**locals_without_store(locals()))

    @router.get('/storage')
    def storage():return storage_summary(store)
    @router.post('/delete-preview')
    def preview(body:Selection):return deletion_preview(store,body.ids)
    @router.get('/resources')
    def resources():return sampler.sample(store)
    @router.get('/tags')
    def tags():return store.query('SELECT t.name,COUNT(et.experiment_id) AS count FROM tags t LEFT JOIN experiment_tags et ON et.tag=t.name GROUP BY t.name ORDER BY t.name LIMIT 1000')
    @router.put('/tags')
    def update_tags(body:TagsRequest):return tag_experiments(store,**body.model_dump())
    @router.get('/experiments/{eid}/notes')
    def get_notes(eid:Identifier):return notes(store,eid)
    @router.put('/experiments/{eid}/notes')
    def put_notes(eid:Identifier,body:NoteRequest):return save_notes(store,eid,body.content)
    @router.get('/experiments/{eid}/notes/export')
    def export_notes(eid:Identifier):return Response(json.dumps(notes(store,eid),indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="{eid}-notes.json"'})
    @router.post('/experiments/{eid}/repeat')
    def repeat_run(eid:Identifier,body:RepeatRequest):return repeat(store,eid,**body.model_dump())
    @router.get('/retention-presets')
    def presets():return {'presets':RETENTION_PRESETS,'notice':'New runs only. All genomes and parent edges remain. Sparse presets omit detailed population/fitness snapshots between strides. Aggregate statistics and current crash recovery remain. No existing data is pruned.'}
    @router.post('/experiments')
    def create(body:CreateRequest):
        raw=body.config
        if isinstance(raw.get('seed'),str):
            if not raw['seed'].isdigit() or len(raw['seed'])>19:raise ValueError('seed must be an exact nonnegative integer')
            raw['seed']=int(raw['seed'])
        if body.preset:raw.setdefault('execution',{}).update(RETENTION_PRESETS[body.preset])
        config=Config.model_validate(raw)
        if config.replicates>1:
            from .manager import enqueue
            ids=enqueue(store,config);return {'id':ids[0],'ids':ids,'seed_text':str(config.seed)}
        return {'id':store.create(config),'seed_text':str(config.seed)}
    @router.post('/sweeps')
    def exact_sweep(body:ExactSweep):
        raw=body.config
        if isinstance(raw.get('seed'),str):
            if not raw['seed'].isdigit() or len(raw['seed'])>19:raise ValueError('seed must be an exact integer')
            raw['seed']=int(raw['seed'])
        from .manager import enqueue
        return {'ids':enqueue(store,Config.model_validate(raw),body.bot_weights)}
    @router.get('/config-diff')
    def diff(a:Identifier,b:Identifier):return config_diff(store,a,b)
    @router.get('/baskets')
    def get_baskets():return baskets(store)
    @router.put('/baskets/{bid}')
    def put_basket(bid:Identifier,body:BasketRequest):return save_basket(store,bid,body.name,[e.model_dump() for e in body.entrants])
    @router.delete('/baskets/{bid}')
    def remove_basket(bid:Identifier):
        with store.transaction() as db:
            if not db.execute('DELETE FROM baskets WHERE id=?',(bid,)).rowcount:raise KeyError(bid)
        return {'deleted':bid}
    @router.get('/bookmarks')
    def get_bookmarks(eid:str='',q:str=Query('',max_length=500),limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0)):
        rows=store.query("SELECT * FROM bookmarks WHERE (?='' OR experiment_id=?) AND (name LIKE ? OR notes LIKE ? OR tags LIKE ?) ORDER BY created DESC LIMIT ? OFFSET ?",(eid,eid,f'%{q}%',f'%{q}%',f'%{q}%',limit+1,offset))
        for row in rows:row['reference']=json.loads(row['reference']);row['tags']=json.loads(row['tags'])
        return {'items':rows[:limit],'next_offset':offset+limit if len(rows)>limit else None}
    @router.post('/bookmarks')
    def bookmark(body:BookmarkRequest):return save_bookmark(store,body.model_dump())
    @router.put('/bookmarks/{bid}')
    def edit_bookmark(bid:int,body:BookmarkRequest):return save_bookmark(store,body.model_dump(),bid)
    @router.delete('/bookmarks/{bid}')
    def remove_bookmark(bid:int):
        with store.transaction() as db:
            if not db.execute('DELETE FROM bookmarks WHERE id=?',(bid,)).rowcount:raise KeyError(bid)
        return {'deleted':bid}
    @router.get('/experiments/{eid}/family/{nid}')
    def family(eid:Identifier,nid:int,direction:Literal['ancestors','descendants']='ancestors',depth:int=Query(4,ge=1,le=30),limit:int=Query(100,ge=2,le=200),cursor:str|None=Query(None,max_length=12000),generation_min:int=Query(0,ge=0),generation_max:int=Query(1000000,ge=0)):
        if nid<1 or nid>2**63-1:raise ValueError('invalid network identity')
        return family_graph(store,eid,nid,direction,depth,limit,cursor,generation_min,generation_max)
    @router.get('/genetic-comparison')
    def genetic(a:Identifier,an:int=Query(ge=1,le=2**63-1),b:Identifier='',bn:int=Query(ge=1,le=2**63-1),layer:int=Query(0,ge=0,le=6),offset:int=Query(0,ge=0),limit:int=Query(256,ge=1,le=1024),kind:Literal['weights','biases']='weights'):
        return genetic_comparison(store,a,an,b,bn,layer,offset,limit,kind)
    @router.get('/experiments/{eid}/chart')
    def chart(eid:Identifier,start:int=Query(0,ge=0),end:int|None=Query(None,ge=0),metrics:list[str]=Query(default=['mean','maximum']),points:int=Query(800,ge=50,le=2000)):
        return chart_data(store,eid,start,end,metrics,points)
    @router.get('/experiments/{eid}/replay/{generation}')
    def replay(eid:Identifier,generation:int):return replay_frame(store,eid,generation)
    @router.get('/experiments/{eid}/timeline')
    def events(eid:Identifier,offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=200),kind:str=''):return timeline(store,eid,offset,limit,kind)
    @router.get('/experiments/{eid}/milestones')
    def milestones(eid:Identifier,offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=200)):
        store.experiment(eid);rows=store.query('SELECT * FROM milestones WHERE experiment_id=? ORDER BY generation,id LIMIT ? OFFSET ?',(eid,limit+1,offset))
        for row in rows:row['provenance']=json.loads(row['provenance'])
        return {'items':rows[:limit],'next_offset':offset+limit if len(rows)>limit else None}
    @router.put('/milestones/{mid}')
    def review(mid:int,body:MilestoneReview):
        with store.transaction() as db:
            if not db.execute('UPDATE milestones SET status=?,notes=? WHERE id=?',(body.status,body.notes,mid)).rowcount:raise KeyError(mid)
        return {'id':mid,**body.model_dump()}
    @router.post('/jobs')
    def job(body:JobRequest):
        from pydantic import ValidationError
        from fastapi import HTTPException
        try:params=specs[body.kind].model_validate(body.parameters).model_dump()
        except ValidationError as exc:raise HTTPException(422,detail=str(exc)) from exc
        return jobs.submit(body.kind,params)
    @router.get('/jobs')
    def job_list():return jobs.list()
    @router.get('/jobs/{jid}')
    def job_status(jid:Identifier):
        jobs.wake();rows=store.query('SELECT * FROM jobs WHERE id=?',(jid,))
        if not rows:raise KeyError(jid)
        return {**rows[0],'result':json.loads(rows[0]['result']) if rows[0]['result'] else None,'request':json.loads(rows[0]['request'])}
    @router.get('/jobs/{jid}/download')
    def artifact(jid:Identifier):
        rows=store.query("SELECT result FROM jobs WHERE id=? AND status='completed'",(jid,))
        if not rows:raise KeyError('completed job')
        result=json.loads(rows[0]['result']);name=result.get('filename','')
        if not name.startswith(jid+'.') or '/' in name or '\\' in name:raise ValueError('this job has no downloadable report or export')
        path=store.root/'exports'/name
        if not path.is_file():raise KeyError('artifact missing; generate it again')
        return FileResponse(path,media_type=result['content_type'],filename=name)
    @router.get('/backups')
    def backups():
        rows=store.query('SELECT * FROM backups ORDER BY created DESC LIMIT 200')
        for row in rows:row['manifest']=json.loads(row['manifest']);row['available']=(store.root/'backups'/row['filename']).is_file()
        return {'items':rows,'restore_instructions':'Use the CLI: evolution-engine restore BACKUP.zip --destination NEW_DIRECTORY. Restore never overwrites an existing directory. Active/queued snapshot states become paused. External references must still exist at their recorded paths.'}
    @router.get('/backups/{bid}/download')
    def backup_download(bid:Identifier):
        rows=store.query('SELECT filename FROM backups WHERE id=?',(bid,))
        if not rows:raise KeyError(bid)
        path=store.root/'backups'/rows[0]['filename']
        if not path.is_file():raise KeyError('backup archive missing')
        return FileResponse(path,media_type='application/zip',filename=path.name)
    app.include_router(router)
    jobs.wake()

def locals_without_store(values):
    # FastAPI closures can include the captured store in locals().
    return {k:v for k,v in values.items() if k!='store'}
