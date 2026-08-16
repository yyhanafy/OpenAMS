#!/usr/bin/env python3
"""
Two-stage component dataset generator v2.

A:
  inputs  W1, I5, VY, VBIAS
  targets valid, Rmin, Rmax
  - W1 and I5 sampled geometrically to cover the feasible density manifold.
  - A electrical cut uses VY x VBIAS.

B:
  inputs  I5, VOUT, VY, VBIAS, R
  target  valid
  - generated independently of A so the dataset contains both positive and
    negative B states.
"""
from __future__ import annotations
import argparse, csv, importlib.util, math, subprocess, sys
from pathlib import Path
import numpy as np

def load_module(path):
    spec=importlib.util.spec_from_file_location("teacher",path)
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod

def rcsv(p):
    with open(p,newline="",encoding="utf-8") as f: return list(csv.DictReader(f))

def wcsv(p,rows):
    p.parent.mkdir(parents=True,exist_ok=True)
    if not rows: p.write_text("",encoding="utf-8"); return
    fields=[]; seen=set()
    for r in rows:
        for k in r:
            if k not in seen: fields.append(k); seen.add(k)
    with open(p,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)

def geom(lo,hi,n):
    return np.geomspace(float(lo),float(hi),int(n)).tolist()

def lin(lo,hi,n):
    return np.linspace(float(lo),float(hi),int(n)).tolist()

def run(root,engine,plan,keep,log):
    cmd=[sys.executable,str(engine),"--plan",str(plan),"--root",str(root),
         "--witnesses-per-point",str(keep)]
    log.parent.mkdir(parents=True,exist_ok=True)
    with open(log,"w",encoding="utf-8") as f:
        subprocess.run(cmd,cwd=root,stdout=f,stderr=subprocess.STDOUT,check=True)

def witness(rows):
    return [r for r in rows if r.get("generation_status")=="WITNESS"
            and r.get("witness_rank") not in (None,"")]

def val(r,*names):
    for n in names:
        if r.get(n) not in (None,""): return float(r[n])
    raise KeyError(names)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",type=Path,default=Path("."))
    ap.add_argument("--teacher-script",type=Path,
        default=Path("tools/validation/run_two_stage_independent_tables_v2.py"))
    ap.add_argument("--engine",type=Path,default=Path("tools/validation/witness_engine.py"))
    ap.add_argument("--base-plan",type=Path,
        default=Path("examples/two_stage_opamp/inputs/two_stage_mlp_witness_plan.yaml"))
    ap.add_argument("--work-dir",type=Path,
        default=Path("runtime/two_stage_component_training_v2"))
    ap.add_argument("--w1-samples",type=int,default=7)
    ap.add_argument("--i5-samples",type=int,default=7)
    ap.add_argument("--w1-min-um",type=float,default=1.0)
    ap.add_argument("--w1-max-um",type=float,default=100.0)
    ap.add_argument("--i5-min-ua",type=float,default=10.009030134)
    ap.add_argument("--i5-max-ua",type=float,default=99.956552025)
    ap.add_argument("--a-vy-count",type=int,default=61)
    ap.add_argument("--a-vbias-count",type=int,default=9)
    ap.add_argument("--a-witnesses",type=int,default=5)

    ap.add_argument("--b-vout-min",type=float,default=0.20)
    ap.add_argument("--b-vout-max",type=float,default=1.70)
    ap.add_argument("--b-vout-count",type=int,default=5)
    ap.add_argument("--b-vy-count",type=int,default=21)
    ap.add_argument("--b-vbias-count",type=int,default=5)
    ap.add_argument("--b-r-min",type=float,default=0.10)
    ap.add_argument("--b-r-max",type=float,default=20.0)
    ap.add_argument("--b-r-count",type=int,default=11)
    ap.add_argument("--b-witnesses",type=int,default=3)
    args=ap.parse_args()

    root=args.root.resolve()
    absr=lambda p:p if p.is_absolute() else (root/p).resolve()
    teacher=load_module(absr(args.teacher_script))
    engine=absr(args.engine)
    base=teacher.read_yaml(absr(args.base_plan))
    work=absr(args.work_dir); work.mkdir(parents=True,exist_ok=True)

    w1s=geom(args.w1_min_um,args.w1_max_um,args.w1_samples)
    i5uas=geom(args.i5_min_ua,args.i5_max_ua,args.i5_samples)

    A=[]
    total=len(w1s)*len(i5uas); k=0
    for wi,w1 in enumerate(w1s):
        for ii,i5ua in enumerate(i5uas):
            k+=1; case=work/"oracle_A"/f"w{wi:02d}_i{ii:02d}"; case.mkdir(parents=True,exist_ok=True)
            acov=case/"coverage.csv"; aout=case/"table.csv"; aplan=case/"plan.yaml"
            teacher.build_a_coverage(acov,w1,i5ua*1e-6,args.a_vy_count,args.a_vbias_count)
            teacher.write_yaml(aplan,teacher.build_a_plan(base,acov,aout,args.a_witnesses))
            run(root,engine,aplan,args.a_witnesses,case/"engine.log")
            cov=rcsv(acov); out=rcsv(aout)
            by={}
            for r in witness(out):
                pi=int(float(r["point_index"]))
                R=2.0*val(r,"w_m3_um","w3")/val(r,"w_m5_um","w5")
                by.setdefault(pi,[]).append(R)
            nvalid=0
            for r in cov:
                pi=int(float(r["point_index"])); rr=by.get(pi,[])
                nvalid += bool(rr)
                A.append({
                    "group_id":f"w{wi:02d}_i{ii:02d}",
                    "w_m1_um":float(r["w_m1_um"]),
                    "i_m5_a":float(r["i_m5_a"]),
                    "vy_v":float(r["vy_v"]),
                    "vbias_v":float(r["vbias_v"]),
                    "valid":int(bool(rr)),
                    "r_count":len(rr),
                    "r_min":min(rr) if rr else "",
                    "r_max":max(rr) if rr else "",
                })
            print(f"A [{k:2d}/{total}] W1={w1:8.4f} I5={i5ua:8.4f}uA valid={nvalid:3d}/{len(cov)}",flush=True)

    # Independent B dataset.
    print("\n===== GENERATING INDEPENDENT B DATASET =====",flush=True)
    vouts=lin(args.b_vout_min,args.b_vout_max,args.b_vout_count)
    vys=lin(0.15,1.65,args.b_vy_count)
    vbs=lin(0.55,1.05,args.b_vbias_count)
    ratios=geom(args.b_r_min,args.b_r_max,args.b_r_count)

    B=[]
    bseq=0
    for ii,i5ua in enumerate(i5uas):
        for oi,vout in enumerate(vouts):
            bseq+=1
            case=work/"oracle_B"/f"i{ii:02d}_o{oi:02d}"; case.mkdir(parents=True,exist_ok=True)
            rows=[]; pi=0
            for vy in vys:
                for vb in vbs:
                    for R in ratios:
                        # build_b_plan carries w3/w5 bindings although its B
                        # equations only need stage_ratio.  Supply a harmless
                        # consistent pair.
                        rows.append({
                            "point_index":pi,
                            "a_point_index":pi,
                            "a_witness_rank":0,
                            "i_m5_a":i5ua*1e-6,
                            "vy_v":vy,
                            "vbias_v":vb,
                            "stage_ratio":R,
                            "vout_v":vout,
                            "w_m3_um":0.5*R,
                            "w_m5_um":1.0,
                        }); pi+=1
            cov=case/"coverage.csv"; out=case/"table.csv"; plan=case/"plan.yaml"
            wcsv(cov,rows)
            teacher.write_yaml(plan,teacher.build_b_plan(base,cov,out,args.b_witnesses))
            run(root,engine,plan,args.b_witnesses,case/"engine.log")
            wr=witness(rcsv(out))
            good={int(float(r["point_index"])) for r in wr}
            for r in rows:
                B.append({
                    "group_id":f"i{ii:02d}_o{oi:02d}",
                    "i_m5_a":r["i_m5_a"],"vout_v":r["vout_v"],
                    "vy_v":r["vy_v"],"vbias_v":r["vbias_v"],
                    "stage_ratio":r["stage_ratio"],
                    "valid":int(r["point_index"] in good),
                })
            print(f"B [{bseq:2d}/{len(i5uas)*len(vouts)}] I5={i5ua:8.4f}uA VOUT={vout:.3f} valid={len(good):4d}/{len(rows)}",flush=True)

    outdir=work/"datasets"; apath=outdir/"A_dataset.csv"; bpath=outdir/"B_dataset.csv"
    wcsv(apath,A); wcsv(bpath,B)
    apos=sum(r["valid"] for r in A); bpos=sum(r["valid"] for r in B)
    pos_groups=sorted({r["group_id"] for r in A if r["valid"]})
    print("\n===== TWO-STAGE V2 DATASET SUMMARY =====")
    print("W1 geom samples (um):",[round(x,6) for x in w1s])
    print("I5 geom samples (uA):",[round(x,6) for x in i5uas])
    print(f"A rows={len(A)} valid={apos} invalid={len(A)-apos} positive_groups={len(pos_groups)}")
    print(f"B rows={len(B)} valid={bpos} invalid={len(B)-bpos}")
    print("A positive groups:",pos_groups)
    print("A:",apath); print("B:",bpath)
    return 0

if __name__=="__main__": raise SystemExit(main())
