#!/usr/bin/env python3
from __future__ import annotations
import argparse, math, re
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

@dataclass
class Metric:
    column:str; direction:str; limit:float; weight:float=1.0; scale:float|None=None

def parse_metric(s):
    p=s.split(':')
    if not 3 <= len(p) <= 5:
        raise argparse.ArgumentTypeError('COLUMN:DIRECTION:LIMIT[:WEIGHT[:SCALE]]')
    c,d,l=p[:3]; d=d.lower()
    if d not in {'min','max','target','high','low'}:
        raise argparse.ArgumentTypeError(f'bad direction {d}')
    return Metric(c,d,float(l),float(p[3]) if len(p)>3 else 1.0,
                  float(p[4]) if len(p)>4 else None)

def args():
    p=argparse.ArgumentParser(description='Generic metric-aware, diversity-aware pre-SPICE candidate selector')
    p.add_argument('--input',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--count',type=int,default=100)
    p.add_argument('--metric',action='append',type=parse_metric,default=[])
    p.add_argument('--diversity-columns',nargs='+')
    p.add_argument('--extra-diversity-columns',nargs='*',default=[])
    p.add_argument('--group-column')
    p.add_argument('--max-per-group',type=int,default=3)
    p.add_argument('--eligible-column')
    p.add_argument('--exploit-fraction',type=float,default=.5)
    p.add_argument('--boundary-fraction',type=float,default=.2)
    p.add_argument('--diversity-fraction',type=float,default=.3)
    p.add_argument('--prefer-pass',action=argparse.BooleanOptionalAction,default=True)
    return p.parse_args()

def passlike(s):
    if pd.api.types.is_bool_dtype(s):
        return s.fillna(False).to_numpy(bool)
    return s.astype(str).str.strip().str.upper().isin(
        {'1','TRUE','YES','PASS','PASSED','VALID','FEASIBLE','OK'}
    ).to_numpy()

def widthcols(df):
    r=[]
    for c in df.columns:
        m=re.match(r'^w_m(\d+)_um$',str(c),re.I)
        if m:r.append((int(m.group(1)),c))
    return [c for _,c in sorted(r)]

def norm01(x):
    lo=np.nanmin(x,0); hi=np.nanmax(x,0)
    span=hi-lo; span[span==0]=1
    return (x-lo)/span

def mscale(v,m):
    if m.scale:return m.scale
    q=v[np.isfinite(v)]
    if not len(q):return max(abs(m.limit),1.0)
    a,b=np.percentile(q,[10,90])
    return max(abs(b-a),abs(m.limit)*.1,1e-12)

def metrics(df,ms):
    n=len(df); hard=np.ones(n,bool); score=np.zeros(n)
    boundary=np.full(n,np.inf); info={}
    tw=sum(m.weight for m in ms) or 1
    for m in ms:
        if m.column not in df:
            raise RuntimeError(f'missing metric column {m.column}')
        v=pd.to_numeric(df[m.column],errors='coerce').to_numpy(float)
        sc=mscale(v,m)
        if m.direction=='min':
            viol=np.maximum(0,m.limit-v)/sc
            rew=np.maximum(0,v-m.limit)/sc
            hard &= np.isfinite(v)&(v>=m.limit)
            b=np.abs(v-m.limit)/sc
            comp=viol-.1*np.minimum(rew,5)
        elif m.direction=='max':
            viol=np.maximum(0,v-m.limit)/sc
            rew=np.maximum(0,m.limit-v)/sc
            hard &= np.isfinite(v)&(v<=m.limit)
            b=np.abs(v-m.limit)/sc
            comp=viol-.1*np.minimum(rew,5)
        elif m.direction=='target':
            comp=np.abs(v-m.limit)/sc; b=comp
        elif m.direction=='high':
            finite=v[np.isfinite(v)]
            ref=np.nanmax(finite) if len(finite) else 0.0
            comp=(ref-v)/sc; b=np.full(n,np.inf)
        else:
            finite=v[np.isfinite(v)]
            ref=np.nanmin(finite) if len(finite) else 0.0
            comp=(v-ref)/sc; b=np.full(n,np.inf)
        comp[~np.isfinite(comp)]=1e6
        score += m.weight*comp
        boundary=np.minimum(boundary,b)
        info[m.column]=sc
    return score/tw,hard,boundary,info

def group_counts(groups, already):
    cnt={}
    if groups is not None:
        for i in already:
            g=groups[i]
            cnt[g]=cnt.get(g,0)+1
    return cnt

def group_limit(order,groups,limit,already=None):
    if groups is None:return order
    cnt=group_counts(groups, already or [])
    out=[]
    for i in order:
        g=groups[i]
        if cnt.get(g,0)>=limit:continue
        out.append(i); cnt[g]=cnt.get(g,0)+1
    return out

def farthest_k(z,seeds,candidates,k,groups=None,max_per_group=3):
    """Return only the next k farthest feasible candidates.

    Complexity is O(k*N*D), not O(N^2*D).
    """
    if k <= 0 or not candidates:
        return []

    selected=list(dict.fromkeys(seeds))
    selected_set=set(selected)
    candidates=np.asarray(list(dict.fromkeys(candidates)),dtype=int)

    nearest=np.full(len(z),np.inf,dtype=float)
    for s in selected:
        d=np.sum((z-z[s])**2,axis=1)
        nearest=np.minimum(nearest,d)

    counts=group_counts(groups, selected)

    if not selected:
        center=np.full(z.shape[1],.5)
        d=np.sum((z[candidates]-center)**2,axis=1)
        first=int(candidates[np.argmin(d)])
        selected.append(first); selected_set.add(first)
        if groups is not None:
            g=groups[first]; counts[g]=counts.get(g,0)+1
        nearest=np.minimum(nearest,np.sum((z-z[first])**2,axis=1))

    out=[]
    while len(out) < k:
        mask=np.array([i not in selected_set for i in candidates],dtype=bool)
        avail=candidates[mask]
        if groups is not None and len(avail):
            gmask=np.array([counts.get(groups[i],0)<max_per_group for i in avail],dtype=bool)
            avail=avail[gmask]
        if len(avail)==0:
            break

        idx=int(avail[np.argmax(nearest[avail])])
        out.append(idx)
        selected.append(idx)
        selected_set.add(idx)

        if groups is not None:
            g=groups[idx]; counts[g]=counts.get(g,0)+1

        nearest=np.minimum(nearest,np.sum((z-z[idx])**2,axis=1))

    return out

def main():
    a=args()
    if a.count<=0: raise SystemExit('--count must be >0')
    if not a.metric: raise SystemExit('at least one --metric is required')

    df=pd.read_csv(a.input).copy()
    df['_openams_source_row']=np.arange(len(df))

    if a.eligible_column:
        if a.eligible_column not in df:
            raise SystemExit(f'missing eligible column {a.eligible_column}')
        df=df.loc[passlike(df[a.eligible_column])].reset_index(drop=True)

    score,hard,boundary,info=metrics(df,a.metric)

    dcols=a.diversity_columns or widthcols(df)
    for c in a.extra_diversity_columns:
        if c not in dcols:dcols.append(c)
    if not dcols:
        raise SystemExit('no diversity columns found; use --diversity-columns')
    miss=[c for c in dcols if c not in df]
    if miss:
        raise SystemExit('missing diversity columns: '+', '.join(miss))

    x=df[dcols].apply(pd.to_numeric,errors='coerce').to_numpy(float)
    keep=np.isfinite(x).all(1)&np.isfinite(score)

    df=df.loc[keep].reset_index(drop=True)
    x=x[keep]; score=score[keep]; hard=hard[keep]; boundary=boundary[keep]
    z=norm01(x)

    n=len(df); budget=min(a.count,n)
    den=a.exploit_fraction+a.boundary_fraction+a.diversity_fraction
    ne=round(budget*a.exploit_fraction/den)
    nb=round(budget*a.boundary_fraction/den)
    nd=max(0,budget-ne-nb)

    groups=df[a.group_column].astype(str).to_numpy() if a.group_column else None
    ids=np.arange(n)
    base=ids[hard] if a.prefer_pass and hard.any() else ids

    exploit=list(base[np.argsort(score[base])])
    exploit=group_limit(exploit,groups,a.max_per_group)
    sel=exploit[:ne]

    bp=[i for i in base[np.argsort(boundary[base])] if i not in set(sel)]
    bp=group_limit(bp,groups,a.max_per_group,sel)
    sel+=bp[:nb]

    cand=[i for i in base if i not in set(sel)]
    div=farthest_k(
        z, sel, cand, nd,
        groups=groups,
        max_per_group=a.max_per_group
    )
    sel+=div

    sel=list(dict.fromkeys(sel))
    if len(sel)<budget:
        rem=[i for i in ids if i not in set(sel)]
        rem=group_limit(sorted(rem,key=lambda i:score[i]),groups,a.max_per_group,sel)
        sel+=rem[:budget-len(sel)]

    sel=sel[:budget]
    out=df.iloc[sel].copy()

    roles=[]
    E=set(exploit[:ne]); B=set(bp[:nb]); D=set(div)
    for i in sel:
        roles.append('EXPLOIT' if i in E else
                     'BOUNDARY' if i in B else
                     'DIVERSITY' if i in D else 'FILL')

    out.insert(0,'selection_rank',np.arange(1,len(out)+1))
    out.insert(1,'selection_metric_score',score[sel])
    out.insert(2,'selection_estimated_pass',hard[sel])
    out.insert(3,'selection_boundary_distance',boundary[sel])
    out.insert(4,'selection_role',roles)

    a.output.parent.mkdir(parents=True,exist_ok=True)
    out.to_csv(a.output,index=False)

    print('===== OPENAMS GENERIC PRE-SPICE CANDIDATE SELECTION =====')
    print('input rows               :',len(df))
    print('estimated hard-pass rows :',int(hard.sum()))
    print('selected                 :',len(out))
    print('diversity columns        :',', '.join(dcols))
    print('output                   :',a.output)
    print('selection roles          :',pd.Series(roles).value_counts().to_dict())
    print('selected estimated-pass  :',int(out.selection_estimated_pass.sum()))
    print('metric scales:')
    for m in a.metric:
        print(f'  {m.column}: {m.direction} {m.limit:g}, weight={m.weight:g}, scale={info[m.column]:g}')

if __name__=='__main__':
    main()
