"""Low-overhead Linux resource sampling and generation-boundary disk guards."""
from pathlib import Path
import os
import shutil
import threading
import time

DEFAULT_DISK_POLICY={'enabled':True,'unit':'gib','warning':5.0,'critical':2.0,'pause':1.0}

from typing import Literal
from pydantic import Field, model_validator
from .config import Model

class DiskPolicy(Model):
    enabled: bool = True
    unit: Literal['gib','percent'] = 'gib'
    warning: float = Field(5,ge=0,le=1000000)
    critical: float = Field(2,ge=0,le=1000000)
    pause: float = Field(1,ge=0,le=1000000)

    @model_validator(mode='after')
    def thresholds(self):
        if not self.warning>=self.critical>=self.pause:raise ValueError('thresholds must satisfy warning >= critical >= pause')
        if self.unit=='percent' and self.warning>100:raise ValueError('percent threshold cannot exceed 100')
        return self

def disk_status(root,policy=None,usage=None):
    policy=policy or DEFAULT_DISK_POLICY
    usage=usage or shutil.disk_usage(root)
    value=usage.free/(1024**3) if policy['unit']=='gib' else usage.free/usage.total*100
    level='normal'
    if policy['enabled']:
        for label,key in [('warning','warning'),('critical','critical'),('pause','pause')]:
            if value<=policy[key]:level=label
    return {'level':level,'free_bytes':usage.free,'total_bytes':usage.total,'free_percent':usage.free/usage.total*100,
            'block_scheduling':level in ('critical','pause'),'pause_workers':level=='pause','policy':policy,
            'guidance':'Create a backup, delete unneeded inactive experiments, then reclaim storage; or restore a backup to a larger workspace.' if level!='normal' else ''}

def disk_guard(store):
    return disk_status(store.root,store.settings().get('disk_policy',DEFAULT_DISK_POLICY))

class ResourceSampler:
    def __init__(self):
        self.previous=None;self.lock=threading.Lock();self.cached=None

    def sample(self,store):
        with self.lock:
            now=time.monotonic()
            if self.cached and now-self.previous[0]<1:return self.cached
            ticks=[int(v) for v in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
            total,idle=sum(ticks),ticks[3]+ticks[4]
            mem={line.split(':')[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines()}
            workers=[];process_ticks={};hz=os.sysconf('SC_CLK_TCK')
            for row in store.query("SELECT id,name,pid,generation FROM experiments WHERE status IN ('running','pausing','cancelling')"):
                item={**row,'cpu_percent':None,'rss_bytes':None}
                try:
                    # comm may contain spaces or parentheses; fields follow its last ).
                    parts=Path(f'/proc/{row["pid"]}/stat').read_text().rsplit(')',1)[1].split()
                    used=int(parts[11])+int(parts[12]);process_ticks[row['pid']]=(used,parts[19])
                    item['rss_bytes']=int(parts[21])*os.sysconf('SC_PAGE_SIZE')
                    if self.previous:
                        old=self.previous[3].get(row['pid'])
                        if old and old[1]==parts[19]:item['cpu_percent']=max(0,(used-old[0])/hz/(now-self.previous[0])*100)
                except (OSError,ValueError,IndexError):item['unavailable']='Process exited or /proc unavailable'
                workers.append(item)
            cpu=None
            if self.previous and total>self.previous[1]:cpu=max(0,min(100,100*(1-(idle-self.previous[2])/(total-self.previous[1]))))
            states={r['status']:r['n'] for r in store.query('SELECT status,COUNT(*) n FROM experiments GROUP BY status')}
            throughput=0
            for row in workers:
                stats=store.query('SELECT statistics FROM generations WHERE experiment_id=? ORDER BY generation DESC LIMIT 1',(row['id'],))
                if stats:
                    import json
                    seconds=json.loads(stats[0]['statistics']).get('compute_seconds',0)
                    if seconds:throughput+=1/seconds
            self.previous=(now,total,idle,process_ticks)
            self.cached={'sampled':time.time(),'cpu_count':os.cpu_count(),'overall_cpu_percent':cpu,'worker_cpu_percent':sum(w['cpu_percent'] or 0 for w in workers) if any(w['cpu_percent'] is not None for w in workers) else None,
                         'worker_cpu_scale':'100% = one core; overall CPU is normalized across all cores','memory_total_bytes':mem['MemTotal'],'memory_available_bytes':mem.get('MemAvailable',mem['MemFree']),
                         'memory_used_bytes':mem['MemTotal']-mem.get('MemAvailable',mem['MemFree']),'workers':workers,'max_workers':store.settings()['max_workers'],'queued':states.get('queued',0),
                         'aggregate_compute_generations_per_second':throughput,'throughput_note':'Estimate from most recent recorded compute duration, excludes persistence and idle time.',
                         'disk':disk_guard(store),'load_average':os.getloadavg(),'database_bytes':store.path.stat().st_size,
                         'failures':store.query('SELECT id,name,error FROM experiments WHERE error IS NOT NULL ORDER BY updated DESC LIMIT 10')}
            return self.cached
