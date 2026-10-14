"""Offline reports preserve observation/annotation provenance and missingness."""
from html import escape
import json
import time
from . import __version__
from .annotations import notes
from .history_lab import chart_data
from .research import run_metrics
from .storage_management import estimate

def report_html(store,eid,include_weights=False,include_lineage=False):
    exp=store.experiment(eid);end=max(0,exp['generation']-1);history=chart_data(store,eid,end=end,points=1000)
    summary=store.stats(eid,end,1);summary=summary[0] if summary else {}
    annotations=notes(store,eid);db=store.connect()
    try:storage=estimate(db,eid)
    finally:db.close()
    marks=store.query('SELECT generation,kind,value,status,notes,provenance FROM milestones WHERE experiment_id=? ORDER BY generation LIMIT 2000',(eid,))
    bookmarks=store.query('SELECT kind,reference,name,notes,tags FROM bookmarks WHERE experiment_id=? ORDER BY created LIMIT 2000',(eid,))
    dependencies=store.query('SELECT DISTINCT external FROM genomes WHERE experiment_id=? AND external IS NOT NULL LIMIT 200',(eid,))
    champion=None;lineage=None
    if summary.get('champion_id'):
        nid=summary['champion_id']
        row=store.query('SELECT id,layers,activations,metadata,fingerprint,external FROM genomes WHERE experiment_id=? AND id=?',(eid,nid))
        champion=row[0] if row else {'id':nid,'missing':True}
        if include_weights and row:
            try:champion['parameters']=store.genome(eid,nid).parameters.tolist()
            except (FileNotFoundError,ValueError) as exc:champion['weights_unavailable']=str(exc)
        if include_lineage:
            from .lab_queries import family_graph
            lineage=family_graph(store,eid,nid,depth=30,limit=200)
    def pre(value):return '<pre>'+escape(json.dumps(value,indent=2,ensure_ascii=False))+'</pre>'
    vals=[r[k] for r in history['rows'] for k in ('mean','maximum') if r.get(k) is not None];chart='No recorded fitness history.'
    if vals:
        low,high=min(vals),max(vals);span=high-low or 1;rows=history['rows'];a,b=rows[0]['generation'],rows[-1]['generation']
        lines=[]
        for key,color in [('mean','#14775d'),('maximum','#a18633')]:
            points=' '.join(f'{40+900*(r["generation"]-a)/max(1,b-a):.2f},{260-220*(r[key]-low)/span:.2f}' for r in rows if r.get(key) is not None)
            lines.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2"/>')
        chart=f'<svg viewBox="0 0 980 300" role="img" aria-label="Mean and maximum recorded fitness">{"".join(lines)}<text x="40" y="290">Generation {a} to {b}; fitness {low:.4g} to {high:.4g}</text></svg><p>Green: mean. Ochre: maximum. {history["plotted_count"]} plotted observations of {history["raw_count"]}. {escape(history["method"])}</p>'
    sections=[('User research notes',pre(annotations)),('Scientific configuration (exact seed)',pre(exp['config'])),('Latest recorded observations',pre(summary)),('Recorded fitness history',chart),
              ('Champion metadata'+(' and parameters' if include_weights else ''),pre(champion)),('Descriptive milestone candidates (up to 2,000)',pre(marks)),('User bookmarks (up to 2,000)',pre(bookmarks)),('Execution information',pre(run_metrics(store,eid))),('Logical storage estimate',pre(storage)),('External historical dependencies',pre(dependencies))]
    if include_lineage:sections.append(('Bounded recorded lineage',pre(lineage)))
    sections.append(('Reproducibility and limitations',f'<p>Report application {__version__}; experiment created by {escape(exp["engine_version"])}. Seed <strong>{exp["config"]["seed"]}</strong>. PCG64 streams and checkpoints remain in the workspace backup. Experiment ID {escape(eid)}; origin {escape(str(exp["origin"]))}.</p><p>This report uses saved observations through generation {end}. Sparse population retention means some detailed snapshots are unavailable. Aggregate cluster counts are not individual cluster memberships. Milestones are descriptive associations, never evidence of causation. No scientific conclusion is generated. Annotations are user statements. Active runs may advance while this report is collected. This report is not a database backup or a complete raw-data archive.</p>'))
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+escape(exp['name'])+' · Research report</title><style>body{max-width:1000px;margin:40px auto;padding:0 24px;font:16px/1.6 system-ui;color:#183329;background:#fafbf7}h1,h2{line-height:1.2}section{border-top:1px solid #cbd6c9;margin-top:32px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef2e9;padding:20px;font-size:12px}svg{width:100%;background:white}p{overflow-wrap:anywhere}</style><h1>'+escape(exp['name'])+'</h1><p>Evolution Engine research report · '+time.strftime('%Y-%m-%d %H:%M:%S UTC',time.gmtime())+'</p>'+''.join('<section><h2>'+escape(title)+'</h2>'+body+'</section>' for title,body in sections)+'</html>'
