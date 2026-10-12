"""Read-only archive adapters with explicit experiment namespaces and provenance."""
from pathlib import Path
import hashlib
import gzip
import json
import re
import sqlite3
import zipfile
import numpy as np
from .config import Config
from .neural import Genome
from .storage import encode,historical_connection

def import_experiment8(store,path,world,generations):
    path=Path(path).resolve(strict=True)
    db=historical_connection(path)
    try:
        available=[r[0] for r in db.execute('SELECT DISTINCT generation FROM appearances WHERE world=? ORDER BY generation',(world,))]
        selected=available if generations is None else sorted(set(generations))
        if not selected or not set(selected)<=set(available):raise ValueError('world or generations missing from Experiment 8 database')
        eid=store.create(Config(name=f'Experiment 8 · {world}',generations=max(selected)+1),'imported',str(path))
        with store.transaction() as target:
            loaded=set();issues=[]
            def load(nid):
                chain=[];seen=set();current=nid
                while current and current not in loaded:
                    if current in seen:raise ValueError('cyclic ancestry in source database')
                    seen.add(current)
                    row=db.execute('SELECT birth_generation,mutation_count,parent_id,genes,first_generation FROM networks WHERE world=? AND id=?',(world,current)).fetchone()
                    if row is None:raise ValueError(f'missing ancestor {current}')
                    chain.append((current,row));current=row[2]
                for current,row in reversed(chain):
                    born,count,parent,blob,first=row;parameters=np.frombuffer(blob,dtype='<f8');changes=()
                    if parent:
                        pg=np.frombuffer(db.execute('SELECT genes FROM networks WHERE world=? AND id=?',(world,parent)).fetchone()[0],dtype='<f8')
                        changes=tuple((int(i),float(pg[i]),float(parameters[i])) for i in np.flatnonzero(pg!=parameters))
                        if count is not None and len(changes)!=count:issues.append(f'{current}: mutation count {count}, observed {len(changes)}')
                    g=Genome(current,(9,12,3),('sigmoid','linear'),parameters,parent or None,born,first,changes,count or 0)
                    store.put_genome(target,eid,g,{'path':str(path),'world':world});loaded.add(current)
            for gen in selected:
                rows=db.execute('SELECT slot,id,fitness FROM appearances WHERE world=? AND generation=? ORDER BY slot',(world,gen)).fetchall()
                for slot,nid,fit in rows:
                    load(nid)
                    target.execute('INSERT INTO populations VALUES(?,?,?,?)',(eid,gen,slot,nid))
                    target.execute('INSERT INTO fitness VALUES(?,?,?,?,NULL,NULL,NULL,NULL,NULL,NULL,?)',(eid,gen,nid,fit,'{}'))
                fits=[r[2] for r in rows];champ=max(rows,key=lambda r:r[2])[1]
                target.execute('INSERT INTO generations VALUES(?,?,?)',(eid,gen,encode({'mean':float(np.mean(fits)),'maximum':max(fits),'minimum':min(fits),'champion_id':champ,'historical':True})))
            target.execute('UPDATE experiments SET generation=? WHERE id=?',(max(selected)+1,eid))
            store.event(target,eid,'import',f'{len(selected)} snapshots, {len(loaded)} external genome references; source opened read-only; missing generation indices: {sorted(set(range(min(selected),max(selected)+1))-set(selected))[:100]}')
            if issues:store.event(target,eid,'import_warnings',encode(issues))
        return eid
    except BaseException as exc:
        if 'eid' in locals():
            with store.transaction() as target:
                target.execute("UPDATE experiments SET status='failed',error=? WHERE id=?",(str(exc),eid))
        raise
    finally:db.close()

def import_archive(store,path,name,population_size=100,prefix=None,start_generation=0):
    path=Path(path).resolve(strict=True)
    if not 2<=population_size<=1000:raise ValueError('invalid archive population size')
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names=[n for n in z.namelist() if n.endswith(('.txt','.json')) and (prefix is None or Path(n).name.startswith(prefix))]
            if not names:raise ValueError('no matching archive members')
            # Avoid accidentally merging Four Worlds into one identity namespace.
            stems={re.sub(r'\(\d+\)$','',Path(n).stem) for n in names}
            if len(stems)>1:raise ValueError('archive contains multiple experiments; select one --prefix')
            names.sort(key=lambda n:int(re.search(r'\((\d+)\)',n).group(1)) if re.search(r'\((\d+)\)',n) else 0)
        def chunks():
            with zipfile.ZipFile(path) as archive:
                for member in names:yield member,json.loads(archive.read(member))
        raw=chunks()
    else:
        content=gzip.decompress(path.read_bytes()).decode() if path.suffix=='.gz' else path.read_text()
        raw=[(path.name,json.loads(content))]
    eid=store.create(Config(name=name),'imported',str(path));known={};issues=[];generation=start_generation
    try:
        with store.transaction() as db:
            for member,content in raw:
                if isinstance(content,dict) and 'networks' in content:
                    records=content['networks'];generation=int(content.get('generation',generation));groups=[records]
                else:
                    records=[json.loads(x) if isinstance(x,str) else x for x in content]
                    if len(records)%population_size==1:records=records[1:] # timing header
                    if len(records)%population_size:raise ValueError(f'{member}: partial population')
                    groups=[records[i:i+population_size] for i in range(0,len(records),population_size)]
                match=re.search(r'\((\d+)\)',member)
                if match and int(match.group(1))*len(groups)+start_generation!=generation:
                    issues.append(f'missing generation range before {member}');generation=int(match.group(1))*len(groups)+start_generation
                for records in groups:
                    seen=set();fitness=[]
                    for slot,r in enumerate(records):
                        if isinstance(r,dict):g=Genome(**r);fit=0
                        else:
                            if len(r) not in (4,7):raise ValueError('record must have 4 or 7 fields')
                            nid=int(r[0]);w=json.loads(r[1]) if isinstance(r[1],str) else r[1];b=json.loads(r[2]) if isinstance(r[2],str) else r[2]
                            if len(w)!=144 or len(b)!=15:raise ValueError('invalid TurboWarp genome dimensions')
                            p=np.array(w+b,dtype=float);fit=float(r[3]);old=known.get(nid)
                            if old:
                                if not np.array_equal(old.parameters,p):raise ValueError('conflicting duplicate genome')
                                g=old
                            else:
                                born,count,parent=map(int,r[4:]) if len(r)==7 else (None,0,0)
                                if len(r)==4:issues.append(f'{nid}: first appearance lacks elite metadata')
                                changes=()
                                if parent in known:
                                    pg=known[parent].parameters;changed=np.flatnonzero(pg!=p);changes=tuple((int(i),float(pg[i]),float(p[i])) for i in changed)
                                    if len(changes)!=count:issues.append(f'{nid}: recorded mutations {count}, observed {len(changes)}')
                                elif parent:issues.append(f'{nid}: missing parent {parent}')
                                g=Genome(nid,(9,12,3),('sigmoid','linear'),p,parent or None,born,generation,changes,count)
                        if g.id in seen:raise ValueError('duplicate identity in population')
                        fitness_record=None
                        if isinstance(content,dict):
                            fitness_record=next((f for f in content.get('fitness',[]) if f['network_id']==g.id),None)
                            if fitness_record is not None:fit=float(fitness_record['total'])
                        if not np.isfinite(fit):raise ValueError('nonfinite fitness')
                        seen.add(g.id);known[g.id]=g;store.put_genome(db,eid,g)
                        db.execute('INSERT INTO populations VALUES(?,?,?,?)',(eid,generation,slot,g.id))
                        f=fitness_record or {}
                        db.execute('INSERT INTO fitness VALUES(?,?,?,?,?,?,?,?,?,?,?)',(eid,generation,g.id,fit,f.get('self_play'),f.get('bot'),f.get('matches'),f.get('wins'),f.get('losses'),f.get('draws'),f.get('components','{}')));fitness.append((g.id,fit))
                    db.execute('INSERT INTO generations VALUES(?,?,?)',(eid,generation,encode({'mean':float(np.mean([f for _,f in fitness])),'maximum':max(f for _,f in fitness),'champion_id':max(fitness,key=lambda t:t[1])[0],'historical':True})))
                    generation+=1
            db.execute('UPDATE experiments SET generation=? WHERE id=?',(generation,eid))
            for nid in known:
                seen=set();cur=nid
                while cur in known and known[cur].parent_id:
                    if cur in seen:raise ValueError('cyclic ancestry in archive')
                    seen.add(cur);cur=known[cur].parent_id
            with path.open('rb') as source:digest=hashlib.file_digest(source,'sha256').hexdigest()
            store.event(db,eid,'import',encode({'source_sha256':digest,'issues':issues,'genomes':len(known)}))
        return {'experiment_id':eid,'issues':issues,'genomes':len(known)}
    except BaseException as exc:
        with store.transaction() as db:db.execute("UPDATE experiments SET status='failed',error=? WHERE id=?",(str(exc),eid))
        raise
