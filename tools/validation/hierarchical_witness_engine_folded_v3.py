#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,importlib.util,itertools,json,os,subprocess,sys,time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import numpy as np
import torch
from torch import nn

class BinaryMLP(nn.Module):
    def __init__(self,nin,hidden):
        super().__init__(); layers=[]; d=nin
        for h in hidden:
            layers += [nn.Linear(d,h),nn.ReLU()]; d=h
        layers.append(nn.Linear(d,1)); self.net=nn.Sequential(*layers)
    def forward(self,x): return self.net(x).squeeze(-1)

def rjson(p): return json.loads(p.read_text())
def rcsv(p):
    with p.open(newline="",encoding="utf-8") as f:return list(csv.DictReader(f))
def wcsv(p,rows):
    p.parent.mkdir(parents=True,exist_ok=True)
    if not rows: p.write_text(""); return
    fs=[]; seen=set()
    for r in rows:
        for k in r:
            if k not in seen: seen.add(k); fs.append(k)
    with p.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fs); w.writeheader(); w.writerows(rows)

def modload(p):
    sp=importlib.util.spec_from_file_location("_step5_realizer",p)
    m=importlib.util.module_from_spec(sp); sp.loader.exec_module(m); return m

def nested_domains(x):
    if isinstance(x,dict):
        if isinstance(x.get("domains"),dict): return x["domains"]
        for v in x.values():
            q=nested_domains(v)
            if q is not None:return q
    return None

def independent_points(contract,root,max_points):
    cfg=contract["independent_point_source"]

    if cfg["kind"]=="explicit_grid":
        names=[]; vec=[]
        for name,s in cfg["variables"].items():
            g=s["grid"]
            lo=float(g["minimum"])
            hi=float(g["maximum"])
            n=int(g["count"])
            spacing=g.get("spacing","linear")
            if spacing in ("geom","log","geometric"):
                vals=np.geomspace(lo,hi,n).tolist()
            else:
                vals=np.linspace(lo,hi,n).tolist()
            names.append(name)
            vec.append(vals)

    elif cfg["kind"]=="independent_regions_json":
        dom=nested_domains(rjson(root/cfg["path"]))
        if not isinstance(dom,dict):
            raise RuntimeError("independent domains not found")
        names=[]; vec=[]
        for name,s in cfg["variables"].items():
            d=dom[s["domain"]]
            mode=s["sampling"]
            if mode=="candidate_values":
                vals=[float(x) for x in d.get("candidate_values",[])]
                if not vals:
                    raise RuntimeError(f"{s['domain']}: candidate_values empty")
            elif mode=="linear_from_domain":
                lo=float(d.get("declared_effective_minimum",d.get("technology_minimum")))
                hi=float(d.get("declared_effective_maximum",d.get("technology_maximum")))
                vals=np.linspace(lo,hi,int(s["count"])).tolist()
            else:
                raise ValueError(mode)
            names.append(name)
            vec.append(vals)
    else:
        raise ValueError(f"unsupported independent source: {cfg['kind']}")

    out=[]
    for i,v in enumerate(itertools.product(*vec)):
        r={"independent_point_index":i}
        r.update(dict(zip(names,v)))
        out.append(r)
        if max_points and len(out)>=max_points:
            break
    return out

def interface_grid(interface):
    c=interface["coordinates"][0]; g=c["grid"]
    if g.get("spacing","linear") in ("geom","log","geometric"):
        vals=np.geomspace(float(g["minimum"]),float(g["maximum"]),int(g["count"]))
    else:
        vals=np.linspace(float(g["minimum"]),float(g["maximum"]),int(g["count"]))
    return c["name"],[float(x) for x in vals]

def load_model(root,c):
    ck=torch.load(root/c["model"]["checkpoint"],map_location="cpu",weights_only=False)
    feats=list(ck["feature_names"])
    m=BinaryMLP(len(feats),tuple(ck["hidden"]))
    m.load_state_dict(ck["state_dict"]); m.eval()
    return m,feats,torch.tensor(np.asarray(ck["mean"],np.float32)),torch.tensor(np.asarray(ck["std"],np.float32)),float(ck["threshold"])

def predict(mi,rows):
    m,feats,mu,sd,th=mi
    X=torch.tensor([[float(r[f]) for f in feats] for r in rows],dtype=torch.float32)
    with torch.inference_mode(): p=torch.sigmoid(m((X-mu)/sd)).numpy()
    return p>=th,p

def split_rows(rows,n):
    if not rows:return []
    n=max(1,min(n,len(rows))); b=[[] for _ in range(n)]
    for i,r in enumerate(rows):b[i%n].append(r)
    return [x for x in b if x]

def prepare_job(root,c,rows,d,sid):
    rr=c["exact_realizer"]; mod=modload(root/rr["module"])
    base=mod.read_yaml(root/rr["base_plan"]); builder=getattr(mod,rr["builder_function"])
    loc=[]
    for i,r in enumerate(rows):
        x=dict(r); x["global_point_index"]=r["point_index"]; x["point_index"]=i; loc.append(x)
    cov=d/"coverage.csv"; out=d/"exact.csv"; plan=d/"plan.yaml"
    wcsv(cov,loc); mod.write_yaml(plan,builder(base,cov,out,int(rr["witnesses_per_state"])))
    cmd=[sys.executable,str(root/"tools/validation/witness_engine.py"),
         "--plan",str(plan),"--root",str(root),
         "--witnesses-per-point",str(rr["witnesses_per_state"])]
    return sid,cmd,out,loc,d

def run_job(root,j):
    sid,cmd,out,cov,d=j
    env=os.environ.copy()
    env.update({"OMP_NUM_THREADS":"1","MKL_NUM_THREADS":"1","OPENBLAS_NUM_THREADS":"1",
                "NUMEXPR_NUM_THREADS":"1","VECLIB_MAXIMUM_THREADS":"1","BLIS_NUM_THREADS":"1"})
    with (d/"engine.log").open("w") as f:
        subprocess.run(cmd,cwd=root,stdout=f,stderr=subprocess.STDOUT,check=True,env=env)
    rr=[r for r in rcsv(out) if r.get("generation_status")=="WITNESS" and r.get("witness_rank") not in (None,"")]
    by={int(float(x["point_index"])):x for x in cov}; merged=[]
    for r in rr:
        x=dict(r)
        x["point_index"]=int(float(by[int(float(r["point_index"]))]["global_point_index"]))
        merged.append(x)
    return sid,merged

def realize(root,c,rows,work,workers):
    if not rows:return []
    ss=split_rows(rows,workers); jobs=[]; base=work/(c["id"]+"_parallel"); base.mkdir(parents=True,exist_ok=True)
    print(f"RUN exact realizer {c['id']}: coverage_rows={len(rows)} workers={len(ss)}",flush=True)
    for i,r in enumerate(ss):
        d=base/f"shard_{i:02d}"; d.mkdir(parents=True,exist_ok=True)
        jobs.append(prepare_job(root,c,r,d,i))
    got=[]
    with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        fs=[ex.submit(run_job,root,j) for j in jobs]; done=0
        for f in as_completed(fs):
            sid,rr=f.result(); done+=1
            print(f"  {c['id']} shard {sid:02d} done witnesses={len(rr)} [{done}/{len(jobs)}]",flush=True)
            got.append((sid,rr))
    got.sort(); return [r for _,rr in got for r in rr]

def enrich(exact,cov):
    by={int(float(r["point_index"])):r for r in cov}; out=[]
    for r in exact:
        x=dict(by[int(float(r["point_index"]))]); x.update(r); out.append(x)
    return out

def q(x): return round(float(x),9)
def eval_expr(expr,env): return eval(expr,{"__builtins__":{}},env)

def canonical(contract,a,b,c):
    env={}; raw={}
    for p,r in (("A",a),("B",b),("C",c)):
        for k,v in r.items():
            kk=f"{p}_{k}"; raw[kk]=v
            try:env[kk]=float(v)
            except (ValueError,TypeError):env[kk]=v
    out={"independent_point_index":int(float(a["independent_point_index"]))}
    for k,e in contract["final_witness"]["canonical_fields"].items():
        out[k]=eval_expr(e,env)
    out["all_saturated"]=int(all(str(r.get("all_saturated","0")) in ("1","1.0","True","true") for r in (a,b,c)))
    out["exact_device_pass"]=1
    out["witness_status"]="VALID_EXACT_COMPONENT_JOIN"
    out.update(raw)
    return out

def dedup(contract,rows):
    ks=contract["final_witness"].get("deduplicate_on",[]); seen=set(); out=[]
    for r in rows:
        sig=tuple(q(r[k]) for k in ks)
        if sig in seen:continue
        seen.add(sig); out.append(r)
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--contract",type=Path,required=True)
    ap.add_argument("--root",type=Path,default=Path("."))
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--work-dir",type=Path,default=Path("runtime/hierarchical_step5_folded"))
    ap.add_argument("--max-points",type=int)
    ap.add_argument("--workers",type=int,default=12)
    a=ap.parse_args()
    torch.set_num_threads(1)
    root=a.root.resolve()
    con=rjson(a.contract if a.contract.is_absolute() else root/a.contract)
    work=a.work_dir if a.work_dir.is_absolute() else root/a.work_dir
    work.mkdir(parents=True,exist_ok=True)
    comps=con["components"]
    if len(comps)!=3: raise RuntimeError("this strategy requires 3 components")
    A,B,C=comps
    vp_name,vps=interface_grid(con["interfaces"][0])
    vx_name,vxs=interface_grid(con["interfaces"][1])
    seeds=independent_points(con,root,a.max_points)
    t0=time.perf_counter()
    print("independent points:",len(seeds))
    print("parallel workers  :",a.workers)
    print("VP/VX grid        :",len(vps),"x",len(vxs))

    ar=[]; br=[]; cr=[]
    for s in seeds:
        for vp in vps: ar.append(dict(s,**{vp_name:vp}))
        for vp in vps:
            for vx in vxs: br.append(dict(s,**{vp_name:vp,vx_name:vx}))
        for vx in vxs: cr.append(dict(s,**{vx_name:vx}))
    print("MLP evaluations A/B/C:",len(ar),len(br),len(cr))
    pa,_=predict(load_model(root,A),ar)
    pb,_=predict(load_model(root,B),br)
    pc,_=predict(load_model(root,C),cr)

    SA=defaultdict(set); SB=defaultdict(set); SC=defaultdict(set)
    for r,y in zip(ar,pa):
        if y:SA[int(r["independent_point_index"])].add(q(r[vp_name]))
    for r,y in zip(br,pb):
        if y:SB[int(r["independent_point_index"])].add((q(r[vp_name]),q(r[vx_name])))
    for r,y in zip(cr,pc):
        if y:SC[int(r["independent_point_index"])].add(q(r[vx_name]))

    joined=[]
    for s in seeds:
        pi=int(s["independent_point_index"])
        for vp,vx in SB[pi]:
            if vp in SA[pi] and vx in SC[pi]:joined.append((pi,vp,vx))
    print("MLP joined interface cells:",len(joined))

    seed_by={int(s["independent_point_index"]):s for s in seeds}
    akeys=sorted({(pi,vp) for pi,vp,vx in joined})
    bkeys=sorted(joined)
    ckeys=sorted({(pi,vx) for pi,vp,vx in joined})
    Ac=[]; Bc=[]; Cc=[]
    for i,(pi,vp) in enumerate(akeys):
        Ac.append({"point_index":i,**seed_by[pi],"vp_v":vp})
    for i,(pi,vp,vx) in enumerate(bkeys):
        Bc.append({"point_index":i,**seed_by[pi],"vp_v":vp,"vx_v":vx})
    for i,(pi,vx) in enumerate(ckeys):
        Cc.append({"point_index":i,**seed_by[pi],"vx_v":vx})

    Ae=enrich(realize(root,A,Ac,work,a.workers),Ac)
    Be=enrich(realize(root,B,Bc,work,a.workers),Bc)
    Ce=enrich(realize(root,C,Cc,work,a.workers),Cc)
    print("exact witnesses A/B/C:",len(Ae),len(Be),len(Ce))

    GA=defaultdict(list); GB=defaultdict(list); GC=defaultdict(list)
    for r in Ae:GA[(int(r["independent_point_index"]),q(r["vp_v"]))].append(r)
    for r in Be:GB[(int(r["independent_point_index"]),q(r["vp_v"]),q(r["vx_v"]))].append(r)
    for r in Ce:GC[(int(r["independent_point_index"]),q(r["vx_v"]))].append(r)

    final=[]
    for pi,vp,vx in joined:
        for aa in GA.get((pi,vp),[]):
            for bb in GB.get((pi,vp,vx),[]):
                for cc in GC.get((pi,vx),[]):
                    final.append(canonical(con,aa,bb,cc))
    final=dedup(con,final)
    grouped=defaultdict(list)
    for r in final:grouped[int(r["independent_point_index"])].append(r)
    ranked=[]
    for pi in sorted(grouped):
        for n,r in enumerate(grouped[pi],1):
            r["witness_rank"]=n; ranked.append(r)

    out=a.output if a.output.is_absolute() else root/a.output
    wcsv(out,ranked)
    wall=time.perf_counter()-t0
    print("\n===== GENERIC HIERARCHICAL STEP 5 =====")
    print("workers                   :",a.workers)
    print("independent points        :",len(seeds))
    print("points with >=1 witness   :",len(grouped))
    print("coverage                  :",f"{100*len(grouped)/max(len(seeds),1):.2f}%")
    print("final exact witnesses     :",len(ranked))
    print("wall seconds              :",f"{wall:.3f}")
    print("output                    :",out)

if __name__=="__main__":main()
