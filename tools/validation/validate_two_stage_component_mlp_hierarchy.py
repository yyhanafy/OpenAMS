#!/usr/bin/env python3
"""
Validate the trained two-stage hierarchical component MLPs on one unseen point.

Teacher:
  corrected A/B witness engine
MLP:
  A(W1,I5,VY,VBIAS) -> feasibility + R envelope
  B(VOUT,VY,VBIAS,R) -> feasibility

Comparison is performed on final joined electrical cells (VY,VBIAS).
For each teacher A witness, exact R values are passed to teacher B.
For the MLP path, A predicts [Rmin,Rmax]; we sample a small log grid inside
the predicted envelope and accept a cell if any sampled R passes MLP-B.

Also reports pure component-MLP inference runtime.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import math
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn


class AMultiHead(nn.Module):
    def __init__(self, nin=4, hidden=(64,64)):
        super().__init__()
        layers=[]; d=nin
        for h in hidden:
            layers += [nn.Linear(d,h), nn.ReLU()]
            d=h
        self.backbone=nn.Sequential(*layers)
        self.valid_head=nn.Linear(d,1)
        self.range_head=nn.Linear(d,2)
    def forward(self,x):
        z=self.backbone(x)
        return self.valid_head(z).squeeze(-1), self.range_head(z)


class BMLP(nn.Module):
    def __init__(self, nin=4, hidden=(64,64)):
        super().__init__()
        layers=[]; d=nin
        for h in hidden:
            layers += [nn.Linear(d,h), nn.ReLU()]
            d=h
        layers.append(nn.Linear(d,1))
        self.net=nn.Sequential(*layers)
    def forward(self,x):
        return self.net(x).squeeze(-1)


def load_module(path):
    spec=importlib.util.spec_from_file_location("teacher",path)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_a(path):
    ck=torch.load(path,map_location="cpu",weights_only=False)
    m=AMultiHead(len(ck["feature_names"]),tuple(ck["hidden"]))
    m.load_state_dict(ck["state_dict"]); m.eval()
    mean=torch.tensor(np.asarray(ck["mean"],np.float32))
    std=torch.tensor(np.asarray(ck["std"],np.float32))
    return ck,m,mean,std,float(ck["threshold"])


def load_b(path):
    ck=torch.load(path,map_location="cpu",weights_only=False)
    m=BMLP(len(ck["feature_names"]),tuple(ck["hidden"]))
    m.load_state_dict(ck["state_dict"]); m.eval()
    mean=torch.tensor(np.asarray(ck["mean"],np.float32))
    std=torch.tensor(np.asarray(ck["std"],np.float32))
    return ck,m,mean,std,float(ck["threshold"])


def rcsv(p):
    with open(p,newline="",encoding="utf-8") as f:
        return list(csv.DictReader(f))


def witness(rows):
    return [r for r in rows if r.get("generation_status")=="WITNESS"
            and r.get("witness_rank") not in (None,"")]


def val(r,*names):
    for n in names:
        if r.get(n) not in (None,""):
            return float(r[n])
    raise KeyError((names, sorted(r)))


def run_engine(root,engine,plan,keep,log):
    cmd=[sys.executable,str(engine),"--plan",str(plan),"--root",str(root),
         "--witnesses-per-point",str(keep)]
    with open(log,"w",encoding="utf-8") as f:
        subprocess.run(cmd,cwd=root,stdout=f,stderr=subprocess.STDOUT,check=True)


def geom_between(lo,hi,n):
    lo=max(float(lo),1e-9); hi=max(float(hi),lo)
    if n<=1 or abs(math.log(hi/lo))<1e-12:
        return np.array([(lo+hi)/2],dtype=np.float32)
    return np.geomspace(lo,hi,n,dtype=np.float32)


def key(vy,vb):
    return (round(float(vy),9),round(float(vb),9))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",type=Path,default=Path("."))
    ap.add_argument("--teacher-script",type=Path,
        default=Path("tools/validation/run_two_stage_independent_tables_v2.py"))
    ap.add_argument("--engine",type=Path,default=Path("tools/validation/witness_engine.py"))
    ap.add_argument("--base-plan",type=Path,
        default=Path("examples/two_stage_opamp/inputs/two_stage_mlp_witness_plan.yaml"))
    ap.add_argument("--model-a",type=Path,
        default=Path("technology/component_models/two_stage_input_bias_network_v3.pt"))
    ap.add_argument("--model-b",type=Path,
        default=Path("technology/component_models/two_stage_output_stage_v3.pt"))
    ap.add_argument("--work-dir",type=Path,
        default=Path("runtime/two_stage_component_mlp_validation"))
    ap.add_argument("--w1",type=float,default=3.2)
    ap.add_argument("--i5-ua",type=float,default=25.0)
    ap.add_argument("--vout",type=float,default=0.80)
    ap.add_argument("--vy-count",type=int,default=61)
    ap.add_argument("--vbias-count",type=int,default=9)
    ap.add_argument("--a-witnesses",type=int,default=5)
    ap.add_argument("--b-witnesses",type=int,default=3)
    ap.add_argument("--r-samples",type=int,default=9)
    ap.add_argument("--runtime-repeats",type=int,default=100)
    args=ap.parse_args()

    torch.set_num_threads(1)

    root=args.root.resolve()
    absr=lambda p:p if p.is_absolute() else (root/p).resolve()
    teacher=load_module(absr(args.teacher_script))
    engine=absr(args.engine)
    base=teacher.read_yaml(absr(args.base_plan))
    work=absr(args.work_dir); work.mkdir(parents=True,exist_ok=True)

    # ---------- TEACHER ----------
    acov=work/"A_coverage.csv"; aout=work/"A_table.csv"; aplan=work/"A_plan.yaml"
    teacher.build_a_coverage(acov,args.w1,args.i5_ua*1e-6,args.vy_count,args.vbias_count)
    teacher.write_yaml(aplan,teacher.build_a_plan(base,acov,aout,args.a_witnesses))
    run_engine(root,engine,aplan,args.a_witnesses,work/"A_engine.log")
    arows=rcsv(aout)

    bcov=work/"B_coverage.csv"; bout=work/"B_table.csv"; bplan=work/"B_plan.yaml"
    bcov_rows=teacher.make_b_coverage(arows,bcov,args.vout)
    teacher_join_cells=set()
    teacher_a_cells=set()

    for r in witness(arows):
        teacher_a_cells.add(key(val(r,"vy_v","vy"), val(r,"vbias_v","vbias")))

    if bcov_rows:
        teacher.write_yaml(bplan,teacher.build_b_plan(base,bcov,bout,args.b_witnesses))
        run_engine(root,engine,bplan,args.b_witnesses,work/"B_engine.log")
        brows=rcsv(bout)
        for r in witness(brows):
            teacher_join_cells.add(key(val(r,"vy_v","vy"), val(r,"vbias_v","vbias")))
    else:
        brows=[]

    # ---------- MLP ----------
    ckA,mA,muA,sdA,thA=load_a(absr(args.model_a))
    ckB,mB,muB,sdB,thB=load_b(absr(args.model_b))

    cov=rcsv(acov)
    XA=torch.tensor([
        [float(r["w_m1_um"]),float(r["i_m5_a"]),
         float(r["vy_v"]),float(r["vbias_v"])]
        for r in cov
    ],dtype=torch.float32)

    def infer_once():
        with torch.inference_mode():
            la,rr=mA((XA-muA)/sdA)
            pa=torch.sigmoid(la)
        a_mask=(pa>=thA).cpu().numpy()
        rr=rr.cpu().numpy()

        mlp_a_cells=set()
        mlp_join_cells=set()

        b_inputs=[]
        b_owner=[]

        for i,r in enumerate(cov):
            if not a_mask[i]:
                continue
            vy=float(r["vy_v"]); vb=float(r["vbias_v"])
            cell=key(vy,vb)
            mlp_a_cells.add(cell)
            rlo=float(np.exp(rr[i,0])); rhi=float(np.exp(rr[i,1]))
            if not np.isfinite(rlo) or not np.isfinite(rhi):
                continue
            if rlo>rhi:
                rlo,rhi=rhi,rlo
            for R in geom_between(rlo,rhi,args.r_samples):
                b_inputs.append([args.vout,vy,vb,float(R)])
                b_owner.append(cell)

        if b_inputs:
            XB=torch.tensor(b_inputs,dtype=torch.float32)
            with torch.inference_mode():
                pb=torch.sigmoid(mB((XB-muB)/sdB))
            bm=(pb>=thB).cpu().numpy()
            for ok,cell in zip(bm,b_owner):
                if ok:
                    mlp_join_cells.add(cell)

        return mlp_a_cells,mlp_join_cells

    mlp_a_cells,mlp_join_cells=infer_once()

    # Runtime: pure inference + join construction.
    for _ in range(10):
        infer_once()
    times=[]
    for _ in range(args.runtime_repeats):
        t0=time.perf_counter()
        infer_once()
        times.append(time.perf_counter()-t0)

    # ---------- METRICS ----------
    def compare(truth,pred):
        tp=len(truth & pred); fp=len(pred-truth); fn=len(truth-pred)
        recall=tp/max(tp+fn,1)
        precision=tp/max(tp+fp,1)
        return tp,fp,fn,recall,precision

    atp,afp,afn,arec,apre=compare(teacher_a_cells,mlp_a_cells)
    jtp,jfp,jfn,jrec,jpre=compare(teacher_join_cells,mlp_join_cells)

    print("===== TWO-STAGE UNSEEN HIERARCHICAL VALIDATION =====")
    print(f"point W1/I5/VOUT              : {args.w1:.6g} um / {args.i5_ua:.6g} uA / {args.vout:.6g} V")
    print(f"electrical interface cells    : {len(cov)}")
    print()
    print("A electrical-cell comparison")
    print(f"  teacher / MLP cells         : {len(teacher_a_cells)} / {len(mlp_a_cells)}")
    print(f"  TP / FP / FN                : {atp} / {afp} / {afn}")
    print(f"  recall / precision          : {arec:.4f} / {apre:.4f}")
    print()
    print("FINAL A+B JOIN comparison")
    print(f"  teacher / MLP joined cells  : {len(teacher_join_cells)} / {len(mlp_join_cells)}")
    print(f"  TP / FP / FN                : {jtp} / {jfp} / {jfn}")
    print(f"  recall / precision          : {jrec:.4f} / {jpre:.4f}")
    print()
    print("Pure hierarchical MLP runtime")
    print(f"  median                      : {1000*np.median(times):.3f} ms/point")
    print(f"  mean                        : {1000*np.mean(times):.3f} ms/point")
    print(f"  throughput                  : {1/np.median(times):.1f} design points/s")
    print()
    print("teacher files:")
    print("  A:",aout)
    print("  B:",bout)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
