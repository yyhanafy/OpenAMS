#!/usr/bin/env python3
from __future__ import annotations

import argparse, concurrent.futures as cf, json, os, shutil, subprocess, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
import yaml

CC_VALUES_PF = [2, 4, 6, 8, 10, 15, 20, 30]

def args():
    r = Path.cwd()
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=r)
    p.add_argument("--plan", type=Path, default=r/"examples/two_stage_opamp/inputs/ngspice_validation.yaml")
    p.add_argument("--run-dir", type=Path, default=r/"validation/ngspice/two_stage_cc4pf_1500_parallel")
    p.add_argument("--sat-audit", type=Path, default=r/"validation/ngspice/two_stage_cc4pf_1500_op_audit/ngspice_saturation_audit.csv")
    p.add_argument("--output-dir", type=Path, default=r/"validation/ngspice/two_stage_cc_sweep_9x8")
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()

def norm(df, cols):
    x = df[cols].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    lo, hi = np.nanmin(x,0), np.nanmax(x,0)
    sp = hi-lo; sp[sp==0]=1
    return (x-lo)/sp

def median_three(valid):
    pm = pd.to_numeric(valid["ac_phase_margin_deg"], errors="coerce")
    med = float(pm.median())
    pool = valid.assign(_d=(pm-med).abs()).nsmallest(min(150,len(valid)),"_d").copy()
    z = norm(pool, ["w_m1_um","w_m3_um","w_m6_um"])
    sel=[0]; nearest=np.sum((z-z[0])**2,axis=1); nearest[0]=-np.inf
    while len(sel)<3:
        i=int(np.argmax(nearest)); sel.append(i)
        nearest=np.minimum(nearest,np.sum((z-z[i])**2,axis=1)); nearest[sel]=-np.inf
    return pool.iloc[sel].copy()

def representatives(run_dir, sat_path):
    ac = pd.read_csv(run_dir/"ngspice_validation_1500.csv")
    sel = pd.read_csv(run_dir/"selected_witnesses_1500.csv")
    sat = pd.read_csv(sat_path)
    widths=["point_index","w_m1_um","w_m3_um","w_m5_um","w_m6_um","w_m7_um"]
    d=ac.merge(sel[widths],on="point_index").merge(
        sat[["point_index","all_devices_saturated","minimum_sat_margin_v"]],
        on="point_index"
    )
    v=d[d["all_devices_saturated"]==True].copy()
    b=v.nlargest(3,"ac_phase_margin_deg").copy(); b["sweep_group"]="best"
    m=median_three(v); m["sweep_group"]="median"
    w=v.nsmallest(3,"ac_phase_margin_deg").copy(); w["sweep_group"]="worst"
    r=pd.concat([b,m,w],ignore_index=True)
    order={"best":0,"median":1,"worst":2}
    r["_o"]=r["sweep_group"].map(order)
    r=r.sort_values(["_o","ac_phase_margin_deg"],ascending=[True,False]).drop(columns="_o").reset_index(drop=True)
    r.insert(0,"representative_rank",np.arange(1,len(r)+1))
    return r

def run_case(cid, root, plan, outcsv, log):
    cmd=[sys.executable,"-m","openams.validation.ngspice_witness","--plan",str(plan),"--root",str(root),"--top-n","1","--output-csv",str(outcsv)]
    env=os.environ.copy()
    env["PYTHONPATH"]=str(root/"src")+(":"+env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    for k in ["OMP_NUM_THREADS","MKL_NUM_THREADS","OPENBLAS_NUM_THREADS","NUMEXPR_NUM_THREADS"]:
        env[k]="1"
    t=time.perf_counter()
    with log.open("w") as f:
        cp=subprocess.run(cmd,cwd=root,env=env,stdout=f,stderr=subprocess.STDOUT,text=True)
    return {"case_id":cid,"returncode":cp.returncode,"elapsed_s":time.perf_counter()-t,"log":str(log)}

def main():
    a=args(); root=a.root.resolve(); plan_path=a.plan.resolve(); run_dir=a.run_dir.resolve(); sat_path=a.sat_audit.resolve(); out=a.output_dir.resolve()
    for p in [plan_path,run_dir/"ngspice_validation_1500.csv",run_dir/"selected_witnesses_1500.csv",sat_path]:
        if not p.exists(): raise SystemExit(f"missing: {p}")
    if out.exists():
        if not a.overwrite: raise SystemExit(f"output exists: {out}")
        shutil.rmtree(out)
    rowsd, plansd, resultsd, logsd = [out/x for x in ["rows","plans","results","logs"]]
    for d in [rowsd,plansd,resultsd,logsd]: d.mkdir(parents=True,exist_ok=True)
    base=yaml.safe_load(plan_path.read_text())
    reps=representatives(run_dir,sat_path)
    reps.to_csv(out/"representative_circuits.csv",index=False)
    show=["representative_rank","sweep_group","point_index","w_m1_um","w_m3_um","w_m5_um","w_m6_um","w_m7_um","ac_phase_margin_deg"]
    print("===== REPRESENTATIVE CIRCUITS ====="); print(reps[show].to_string(index=False))
    source=pd.read_csv(run_dir/"selected_witnesses_1500.csv")
    jobs=[]; meta=[]; cid=0
    for _,rep in reps.iterrows():
        pi=int(rep["point_index"])
        one=source[pd.to_numeric(source["point_index"],errors="coerce")==pi]
        if len(one)!=1: raise SystemExit(f"point {pi}: expected 1 row, got {len(one)}")
        for cc in CC_VALUES_PF:
            cid+=1
            rowcsv=rowsd/f"case_{cid:03d}.csv"; one.to_csv(rowcsv,index=False)
            pl=dict(base); pl["input_csv"]=str(rowcsv); pl["top_n"]=1
            const=dict(pl.get("constants") or {}); const["c_miller"]=cc*1e-12; pl["constants"]=const
            pp=plansd/f"case_{cid:03d}.yaml"; pp.write_text(yaml.safe_dump(pl,sort_keys=False))
            oc=resultsd/f"case_{cid:03d}.csv"; lg=logsd/f"case_{cid:03d}.log"
            jobs.append((cid,root,pp,oc,lg))
            meta.append({"case_id":cid,"representative_rank":int(rep["representative_rank"]),"sweep_group":rep["sweep_group"],"point_index":pi,"cc_pf":cc,
                         "w_m1_um":float(rep["w_m1_um"]),"w_m3_um":float(rep["w_m3_um"]),"w_m5_um":float(rep["w_m5_um"]),"w_m6_um":float(rep["w_m6_um"]),"w_m7_um":float(rep["w_m7_um"])})
    print(f"cases: {len(jobs)}; workers: {a.workers}; Cc: {CC_VALUES_PF} pF")
    rr=[]
    with cf.ThreadPoolExecutor(max_workers=a.workers) as pool:
        futs={pool.submit(run_case,*j):j[0] for j in jobs}
        for f in cf.as_completed(futs):
            r=f.result(); rr.append(r)
            print(f"[case {r['case_id']:03d}/072] {'PASS' if r['returncode']==0 else 'FAIL'} time={r['elapsed_s']:.1f}s",flush=True)
    man=pd.DataFrame(rr).sort_values("case_id"); man.to_csv(out/"run_manifest.csv",index=False)
    if (man["returncode"]!=0).any(): raise SystemExit("one or more cases failed; inspect logs")
    frames=[]
    for m in meta:
        r=pd.read_csv(resultsd/f"case_{m['case_id']:03d}.csv")
        r.insert(0,"case_id",m["case_id"]); frames.append(r)
    res=pd.concat(frames,ignore_index=True)
    merged=pd.DataFrame(meta).merge(res,on=["case_id","point_index"]).sort_values(["representative_rank","cc_pf"])
    merged.to_csv(out/"cc_sweep_results.csv",index=False)
    table=merged.pivot_table(index=["representative_rank","sweep_group","point_index"],columns="cc_pf",values="ac_phase_margin_deg",aggfunc="first")
    table.to_csv(out/"pm_vs_cc_table.csv")
    print("\n===== PM VS Cc ====="); print(table.round(2).to_string())
    print("\noutputs:",out/"cc_sweep_results.csv",out/"pm_vs_cc_table.csv")
    (out/"summary.json").write_text(json.dumps({"cc_values_pf":CC_VALUES_PF,"cases":72,"workers":a.workers},indent=2)+"\n")

if __name__=="__main__":
    main()
