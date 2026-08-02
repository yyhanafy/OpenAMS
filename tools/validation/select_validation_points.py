#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,hashlib,json,random,subprocess
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path

ALGORITHM='openams_stratified_validation_selection'
VERSION='1.0'
COUNTS={'random_interior':20,'boundary':20,'gain_low':10,'gain_high':10,'ugb_low':10,'ugb_high':10,'phase_margin_low':10,'phase_margin_high':10}
METRICS={'gain_low':('gain_est_db',False),'gain_high':('gain_est_db',True),'ugb_low':('ugb_est_hz',False),'ugb_high':('ugb_est_hz',True),'phase_margin_low':('phase_margin_est_deg',False),'phase_margin_high':('phase_margin_est_deg',True)}

def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def args():
    p=argparse.ArgumentParser()
    p.add_argument('--benchmark',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--count',type=int,default=100)
    p.add_argument('--seed',type=int,default=7)
    p.add_argument('--overwrite',action='store_true')
    return p.parse_args()

def shape(benchmark:Path,nrows:int):
    p=benchmark/'coarse_scan_summary.json'
    if p.is_file():
        d=json.loads(p.read_text()).get('grid',{})
        vals=(d.get('i5_count'),d.get('w1_count'),d.get('vout_count'))
        if all(isinstance(v,int) and v>0 for v in vals): return vals
    if nrows==10000: return (40,25,10)
    raise ValueError('Cannot determine grid shape')

def coord(idx,w1,vout):
    return idx//(w1*vout),(idx%(w1*vout))//vout,idx%vout

def idx(c,w1,vout):
    return c[0]*w1*vout+c[1]*vout+c[2]

def rejected_neighbors(i,rejected,sh):
    a,b,c=coord(i,sh[1],sh[2]); n=0
    for da,db,dc in ((-1,0,0),(1,0,0),(0,-1,0),(0,1,0),(0,0,-1),(0,0,1)):
        q=(a+da,b+db,c+dc)
        if 0<=q[0]<sh[0] and 0<=q[1]<sh[1] and 0<=q[2]<sh[2] and idx(q,sh[1],sh[2]) in rejected: n+=1
    return n

def metric_sort(rows,col,desc):
    good=[]
    for r in rows:
        try:v=float(r[col])
        except:continue
        if v==v and abs(v)!=float('inf'): good.append(r)
    return sorted(good,key=lambda r:((-float(r[col])) if desc else float(r[col]),int(r['grid_index'])))

def add(sel,row,reason):
    i=int(row['grid_index'])
    sel.setdefault(i,{'row':row,'reasons':[]})
    if reason not in sel[i]['reasons']: sel[i]['reasons'].append(reason)

def main():
    a=args(); b=a.benchmark.resolve(); o=a.output.resolve(); src=b/'coarse_scan_results.csv'; man=o/'selection_manifest.json'; out=o/'selected_points.csv'
    if a.count<=0: raise ValueError('--count must be positive')
    if not src.is_file(): raise FileNotFoundError(src)
    if not a.overwrite and (out.exists() or man.exists()): raise FileExistsError(f'Output exists in {o}')
    with src.open(newline='') as f:
        rd=csv.DictReader(f); rows=list(rd); fields=list(rd.fieldnames or [])
    acc=[r for r in rows if r.get('status')=='PASS']; rej=[r for r in rows if r.get('status')=='REJECT']
    if len(acc)<a.count: raise ValueError('Not enough accepted rows')
    sh=shape(b,len(rows))
    if sh[0]*sh[1]*sh[2]!=len(rows): raise ValueError('Grid shape does not match row count')
    rejidx={int(r['grid_index']) for r in rej}
    boundary=[]; interior=[]
    for r in acc:
        n=rejected_neighbors(int(r['grid_index']),rejidx,sh)
        (boundary if n else interior).append(((-n,int(r['grid_index']),r)) if n else r)
    boundary=sorted(boundary,key=lambda x:(x[0],x[1]))
    rng=random.Random(a.seed); sel={}
    ints=sorted(interior,key=lambda r:int(r['grid_index']))
    for r in rng.sample(ints,min(COUNTS['random_interior'],len(ints))): add(sel,r,'random_interior')
    for _,_,r in boundary[:COUNTS['boundary']]: add(sel,r,'accepted_adjacent_to_rejected')
    for reason,(col,desc) in METRICS.items():
        for r in metric_sort(acc,col,desc)[:COUNTS[reason]]: add(sel,r,reason)
    remain=[r for r in sorted(acc,key=lambda r:int(r['grid_index'])) if int(r['grid_index']) not in sel]
    rng.shuffle(remain)
    for r in remain:
        if len(sel)>=a.count: break
        add(sel,r,'fixed_seed_backfill')
    priority={'accepted_adjacent_to_rejected':0,'gain_low':1,'gain_high':2,'ugb_low':3,'ugb_high':4,'phase_margin_low':5,'phase_margin_high':6,'random_interior':7,'fixed_seed_backfill':8}
    items=list(sel.values()); items.sort(key=lambda x:(min(priority[z] for z in x['reasons']),int(x['row']['grid_index']))); items=items[:a.count]
    o.mkdir(parents=True,exist_ok=True)
    extra=['selection_order','selection_reasons','rejected_neighbor_count']
    with out.open('w',newline='') as f:
        wr=csv.DictWriter(f,fieldnames=extra+fields); wr.writeheader()
        for k,it in enumerate(items):
            r=dict(it['row']); gi=int(r['grid_index']); wr.writerow({'selection_order':k,'selection_reasons':';'.join(it['reasons']),'rejected_neighbor_count':rejected_neighbors(gi,rejidx,sh),**r})
    rc=defaultdict(int)
    for it in items:
        for z in it['reasons']: rc[z]+=1
    repo=b
    while repo.parent!=repo and not (repo/'.git').exists(): repo=repo.parent
    try: commit=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True,stderr=subprocess.DEVNULL).strip()
    except: commit=None
    payload={'status':'PASS','algorithm':ALGORITHM,'algorithm_version':VERSION,'created_at_utc':datetime.now(timezone.utc).isoformat(),'seed':a.seed,'requested_count':a.count,'selected_unique_count':len(items),'selection_policy':COUNTS,'selection_reason_membership_counts':dict(sorted(rc.items())),'source':{'benchmark_directory':str(b),'coarse_scan_results_sha256':sha256(src),'coarse_scan_summary_sha256':sha256(b/'coarse_scan_summary.json') if (b/'coarse_scan_summary.json').is_file() else None,'constructed_assignments_sha256':sha256(b/'constructed_assignments.jsonl') if (b/'constructed_assignments.jsonl').is_file() else None,'git_commit_at_selection':commit},'benchmark_counts':{'rows':len(rows),'accepted':len(acc),'rejected':len(rej),'grid_shape':{'i5_count':sh[0],'w1_count':sh[1],'vout_count':sh[2]},'accepted_adjacent_to_rejected_count':len(boundary),'interior_accepted_count':len(interior)},'outputs':{'selected_points_csv':str(out),'selected_points_sha256':sha256(out)},'selected_grid_indices':[int(it['row']['grid_index']) for it in items]}
    man.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
    print('===== OPENAMS NGSPICE VALIDATION POINT SELECTION =====')
    print(f'benchmark rows:     {len(rows)}\naccepted rows:      {len(acc)}\nrejected rows:      {len(rej)}\nboundary accepted:  {len(boundary)}\ninterior accepted:  {len(interior)}\nselected unique:    {len(items)}\nselected CSV:       {out}\nselection manifest: {man}')
    if len(items)!=a.count: raise RuntimeError('Incorrect selection count')
    return 0

if __name__=='__main__': raise SystemExit(main())
