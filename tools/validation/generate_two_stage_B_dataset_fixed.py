#!/usr/bin/env python3
"""
Generate ONLY the corrected two-stage B dataset.

B inputs:
    VY, VBIAS, R, VOUT
B target:
    valid / invalid

I5 is intentionally excluded from the learned B feature set because the local
M6/M7 equations are fully determined by (VY,VBIAS,R,VOUT) plus the fixed
technology/constants.  The teacher plan may still carry I5 as a bookkeeping
binding; it is held at a harmless reference value.
"""
from __future__ import annotations
import argparse, csv, importlib.util, subprocess, sys
from pathlib import Path
import numpy as np

def load_module(path):
    spec=importlib.util.spec_from_file_location("teacher",path)
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod

def wcsv(p,rows):
    p.parent.mkdir(parents=True,exist_ok=True)
    fields=list(rows[0].keys())
    with open(p,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)

def rcsv(p):
    with open(p,newline="",encoding="utf-8") as f:return list(csv.DictReader(f))

def witness(rows):
    return [r for r in rows if r.get("generation_status")=="WITNESS"
            and r.get("witness_rank") not in (None,"")]

def lin(lo,hi,n): return np.linspace(float(lo),float(hi),int(n)).tolist()
def geom(lo,hi,n): return np.geomspace(float(lo),float(hi),int(n)).tolist()

def run(root,engine,plan,keep,log):
    cmd=[sys.executable,str(engine),"--plan",str(plan),"--root",str(root),
         "--witnesses-per-point",str(keep)]
    with open(log,"w",encoding="utf-8") as f:
        subprocess.run(cmd,cwd=root,stdout=f,stderr=subprocess.STDOUT,check=True)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",type=Path,default=Path("."))
    ap.add_argument("--teacher-script",type=Path,
        default=Path("tools/validation/run_two_stage_independent_tables_v2.py"))
    ap.add_argument("--engine",type=Path,default=Path("tools/validation/witness_engine.py"))
    ap.add_argument("--base-plan",type=Path,
        default=Path("examples/two_stage_opamp/inputs/two_stage_mlp_witness_plan.yaml"))
    ap.add_argument("--work-dir",type=Path,
        default=Path("runtime/two_stage_component_training_B_fixed"))
    ap.add_argument("--vy-count",type=int,default=31)
    ap.add_argument("--vbias-count",type=int,default=9)
    ap.add_argument("--r-count",type=int,default=21)
    ap.add_argument("--r-min",type=float,default=0.10)
    ap.add_argument("--r-max",type=float,default=20.0)
    ap.add_argument("--vout-count",type=int,default=8)
    ap.add_argument("--vout-min",type=float,default=0.30)
    ap.add_argument("--vout-max",type=float,default=1.35)
    ap.add_argument("--i5-reference-ua",type=float,default=10.009030134)
    ap.add_argument("--witnesses",type=int,default=3)
    args=ap.parse_args()

    root=args.root.resolve()
    absr=lambda p:p if p.is_absolute() else (root/p).resolve()
    teacher=load_module(absr(args.teacher_script))
    engine=absr(args.engine)
    base=teacher.read_yaml(absr(args.base_plan))
    work=absr(args.work_dir); work.mkdir(parents=True,exist_ok=True)

    vys=lin(0.15,1.65,args.vy_count)
    vbs=lin(0.55,1.05,args.vbias_count)
    rs=geom(args.r_min,args.r_max,args.r_count)
    vouts=lin(args.vout_min,args.vout_max,args.vout_count)

    dataset=[]
    for oi,vout in enumerate(vouts):
        case=work/f"vout_{oi:02d}"
        case.mkdir(parents=True,exist_ok=True)
        rows=[]; pi=0
        for vy in vys:
            for vb in vbs:
                for R in rs:
                    rows.append({
                        "point_index":pi,
                        "a_point_index":pi,
                        "a_witness_rank":0,
                        "i_m5_a":args.i5_reference_ua*1e-6,
                        "vy_v":vy,
                        "vbias_v":vb,
                        "stage_ratio":R,
                        "vout_v":vout,
                        "w_m3_um":0.5*R,
                        "w_m5_um":1.0,
                    })
                    pi+=1

        cov=case/"coverage.csv"; out=case/"table.csv"; plan=case/"plan.yaml"
        wcsv(cov,rows)
        teacher.write_yaml(plan,teacher.build_b_plan(base,cov,out,args.witnesses))
        run(root,engine,plan,args.witnesses,case/"engine.log")
        good={int(float(r["point_index"])) for r in witness(rcsv(out))}

        for r in rows:
            dataset.append({
                "group_id":f"vout_{oi:02d}",
                "vout_v":r["vout_v"],
                "vy_v":r["vy_v"],
                "vbias_v":r["vbias_v"],
                "stage_ratio":r["stage_ratio"],
                "valid":int(r["point_index"] in good),
            })

        print(
            f"[{oi+1:2d}/{len(vouts)}] VOUT={vout:.4f} "
            f"valid={len(good):5d}/{len(rows)}",
            flush=True
        )

    outdir=work/"datasets"
    bpath=outdir/"B_dataset.csv"
    wcsv(bpath,dataset)
    pos=sum(r["valid"] for r in dataset)
    print("\n===== CORRECTED TWO-STAGE B DATASET =====")
    print("VOUT samples:",[round(x,6) for x in vouts])
    print(f"rows={len(dataset)} valid={pos} invalid={len(dataset)-pos}")
    print("output:",bpath)
    return 0

if __name__=="__main__": raise SystemExit(main())
