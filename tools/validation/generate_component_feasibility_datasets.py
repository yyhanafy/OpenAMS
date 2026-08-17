#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,importlib.util,itertools,json,math
from collections import defaultdict
from pathlib import Path
import numpy as np

def pa():
    p=argparse.ArgumentParser()
    p.add_argument('--contract',required=True,type=Path); p.add_argument('--root',type=Path,default=Path('.'))
    p.add_argument('--output-dir',required=True,type=Path); p.add_argument('--work-dir',type=Path,default=None)
    p.add_argument('--workers',type=int,default=12); p.add_argument('--component',action='append',default=[])
    p.add_argument('--max-values-per-dimension',type=int,default=0); p.add_argument('--max-coverage-rows',type=int,default=0)
    p.add_argument('--dry-run',action='store_true'); return p.parse_args()

def ab(root,p):
    p=Path(p); return p if p.is_absolute() else (root/p).resolve()
def lj(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def lm(p,name):
    s=importlib.util.spec_from_file_location(name,p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m

def nd(x):
    if isinstance(x,dict):
        if isinstance(x.get('domains'),dict): return x['domains']
        for v in x.values():
            r=nd(v)
            if r is not None:return r
    elif isinstance(x,list):
        for v in x:
            r=nd(v)
            if r is not None:return r
    return None

def gv(g):
    lo=float(g['minimum']); hi=float(g['maximum']); n=int(g['count']); sp=str(g.get('spacing','linear')).lower()
    if n==1:return [lo]
    if sp in ('log','geom','geometric','log10','logarithmic'): return np.geomspace(lo,hi,n).astype(float).tolist()
    if sp=='linear': return np.linspace(lo,hi,n).astype(float).tolist()
    raise ValueError(sp)

def indep_vals(root,src,name,spec):
    if src['kind']=='explicit_grid': return gv(spec['grid']),'independent:explicit_grid'
    if src['kind']!='independent_regions_json': raise ValueError(src['kind'])
    dom=nd(lj(ab(root,src['path']))); d=dom[spec['domain']]; mode=spec['sampling']
    if mode=='candidate_values':
        vals=[float(x) for x in d.get('candidate_values',[])]
        if not vals: raise RuntimeError(f'{name}: empty candidate_values')
    else:
        lo=float(d.get('declared_effective_minimum',d.get('technology_minimum'))); hi=float(d.get('declared_effective_maximum',d.get('technology_maximum')))
        if mode=='linear_from_domain': vals=np.linspace(lo,hi,int(spec['count'])).tolist()
        elif mode=='log_from_domain': vals=np.geomspace(lo,hi,int(spec['count'])).tolist()
        else: raise ValueError(mode)
    return vals,f"independent_regions:{spec['domain']}:{mode}"

def feats(c):
    x=list(c.get('model',{}).get('features',[]))
    if not x: raise RuntimeError(f"{c.get('id')}: no model.features")
    return x

def domains(contract,root,c):
    allv={}; src=contract['independent_point_source']
    for n,s in src.get('variables',{}).items(): allv[n]=indep_vals(root,src,n,s)
    for itf in contract.get('interfaces',[]):
        iid=itf.get('id','?')
        for q in itf.get('coordinates',[]):
            if 'grid' in q: allv[q['name']]=(gv(q['grid']),f'interface:{iid}')
        for pv in itf.get('propagated_variables',[]):
            if pv.get('destination_component')!=c['id']: continue
            td=pv.get('training_domain')
            if td:
                if 'count' not in td: raise RuntimeError(f"{pv['name']}: training_domain missing count")
                g=dict(td); g.setdefault('spacing','linear'); allv[pv['name']]=(gv(g),f'propagated_training:{iid}')
    for q in c.get('local_search_coordinates',[]):
        if 'grid' in q: allv[q['name']]=(gv(q['grid']),f"local_search:{c['id']}")
    overrides=c.get('training',{}).get('feature_domains',{})
    out=[]
    for f in feats(c):
        if f not in allv: raise RuntimeError(f"component {c['id']}: feature {f!r} has no declared training domain")
        vals,origin=allv[f]
        if f in overrides:
            o=dict(overrides[f])
            lo=float(o.get('minimum',min(vals))); hi=float(o.get('maximum',max(vals)))
            count=int(o.get('count',len(vals))); spacing=o.get('spacing','linear')
            vals=gv({'minimum':lo,'maximum':hi,'count':count,'spacing':spacing})
            origin=f"training_override:{c['id']}"
        out.append((f,vals,origin))
    return out

def sub(v,n):
    if n<=0 or len(v)<=n:return v
    if n==1:return [v[len(v)//2]]
    idx=sorted({round(i*(len(v)-1)/(n-1)) for i in range(n)}); return [v[i] for i in idx]

def se(expr,env):
    if isinstance(expr,(int,float)): return expr
    return eval(str(expr),{'__builtins__':{},'min':min,'max':max,'abs':abs,'exp':math.exp,'log':math.log},env)

def cover(c,res,maxdim,maxrows):
    res=[(n,sub(v,maxdim),o) for n,v,o in res]; rows=[]
    for i,combo in enumerate(itertools.product(*(v for _,v,_ in res))):
        r={'coverage_index':i,'point_index':i,'independent_point_index':i}
        for (n,_,_),x in zip(res,combo): r[n]=float(x)
        env=dict(r)
        for n,e in c.get('training',{}).get('coverage_bindings',{}).items(): r[n]=se(e,env); env[n]=r[n]
        rows.append(r)
        if maxrows>0 and len(rows)>=maxrows: break
    return rows,res

def key(r,fs):
    try:return tuple(round(float(r[f]),12) for f in fs)
    except:return None

def rv(r,n):
    if r.get(n) not in (None,''): return float(r[n])
    for k,v in r.items():
        if k.endswith('_'+n) and v not in (None,''): return float(v)
    raise KeyError(n)

def wc(p,rows,fields):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)

def main():
    a=pa(); root=a.root.resolve(); cp=ab(root,a.contract); out=ab(root,a.output_dir); work=ab(root,a.work_dir) if a.work_dir else out.parent/'oracle'
    con=lj(cp); cs=list(con.get('components',[]))
    if a.component:
        want=set(a.component); cs=[c for c in cs if c['id'] in want]
    h=lm(root/'tools/validation/hierarchical_witness_engine.py','_hwe_ds')
    print('===== GENERIC COMPONENT DATASET GENERATOR V2 ====='); print('contract:',cp)
    manifest={'schema_version':2,'contract':str(cp),'components':[]}
    for c in cs:
        cid=c['id']; kind=c['model']['kind']; fs=feats(c); cov,res=cover(c,domains(con,root,c),a.max_values_per_dimension,a.max_coverage_rows)
        print(f'\n--- {cid} ---\nkind: {kind}')
        for n,v,o in res: print(f'  {n}: {len(v)} [{v[0]:.12g},{v[-1]:.12g}] from {o}')
        print('coverage rows:',len(cov)); dp=out/f'{cid}_dataset.csv'
        if a.dry_run: print('dry-run output:',dp); continue
        ex=h.enrich_exact_rows(h.exact_realize(root,c,cov,work/cid,a.workers),cov,c); bk=defaultdict(list)
        for r in ex:
            k=key(r,fs)
            if k is not None: bk[k].append(r)
        em=list(c['model'].get('emitted_ranges',[])); ds=[]; pos=0
        for r in cov:
            wr=bk.get(key(r,fs),[]); valid=int(bool(wr)); pos+=valid; z={f:r[f] for f in fs}; z['valid']=valid; z['witness_count']=len(wr)
            if kind=='feasibility_range_emitter':
                if not em: raise RuntimeError(f'{cid}: no emitted_ranges')
                for s in em:
                    vals=[rv(x,s['name']) for x in wr] if wr else []; z[s['name']+'_min']=min(vals) if vals else ''; z[s['name']+'_max']=max(vals) if vals else ''
            ds.append(z)
        fields=[*fs,'valid','witness_count']
        for s in em: fields += [s['name']+'_min',s['name']+'_max']
        wc(dp,ds,fields); print('exact witnesses:',len(ex)); print(f'dataset: rows={len(ds)} valid={pos} invalid={len(ds)-pos}'); print('output:',dp)
        manifest['components'].append({'id':cid,'kind':kind,'features':fs,'coverage_rows':len(ds),'valid_rows':pos,'invalid_rows':len(ds)-pos,'exact_witnesses':len(ex),'dataset':str(dp)})
    if not a.dry_run:
        mp=out/'component_dataset_manifest.json'; mp.parent.mkdir(parents=True,exist_ok=True); mp.write_text(json.dumps(manifest,indent=2)+'\n'); print('\nmanifest:',mp)
if __name__=='__main__': main()
