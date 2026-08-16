#!/usr/bin/env python3
from __future__ import annotations
import argparse, copy, csv, itertools, math, subprocess, sys
from pathlib import Path
import yaml

DEFAULT_PLAN=Path("examples/two_stage_opamp/inputs/two_stage_mlp_witness_plan.yaml")
DEFAULT_ENGINE=Path("tools/validation/witness_engine.py")
DEFAULT_WORK=Path("runtime/two_stage_independent_component_tables")

def ry(p):
    with open(p,"r",encoding="utf-8") as f: return yaml.safe_load(f)
def wy(p,d):
    p.parent.mkdir(parents=True,exist_ok=True)
    with open(p,"w",encoding="utf-8") as f: yaml.safe_dump(d,f,sort_keys=False)
def rcsv(p):
    with open(p,newline="",encoding="utf-8") as f: return list(csv.DictReader(f))
def wcsv(p,rows):
    p.parent.mkdir(parents=True,exist_ok=True)
    with open(p,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
def dev(base,name):
    for d in base["final"]["devices"]:
        if d["name"]==name: return copy.deepcopy(d)
    raise KeyError(name)
def real(rows): return [r for r in rows if r.get("generation_status")=="WITNESS"]
def lin(lo,hi,n): return [lo+i*(hi-lo)/(n-1) for i in range(n)]
def geom(lo,hi,n):
    a,b=math.log(lo),math.log(hi)
    return [math.exp(a+i*(b-a)/(n-1)) for i in range(n)]
def shell(base,name,cov,out,keep,bindings,derived,stages,final,aliases):
    return {"schema_version":1,"name":name,"coverage_csv":str(cov),"output_csv":str(out),
            "witnesses_per_point":keep,"sat_margin_v":base.get("sat_margin_v",0.05),
            "mlp":copy.deepcopy(base["mlp"]),"constants":copy.deepcopy(base["constants"]),
            "point_bindings":bindings,"derived_bindings":derived,"stages":stages,
            "final":final,"csv_aliases":aliases}

def build_coverages(work,w1,i5,vout,ny,nv,nr):
    vys=lin(0.15,1.65,ny); vbs=lin(0.55,1.05,nv); rs=geom(0.1,20.0,nr)
    A=[]; B=[]
    for k,(vy,vb,r) in enumerate(itertools.product(vys,vbs,rs)):
        A.append({"point_index":k,"w_m1_um":w1,"i_m5_a":i5,"vy_v":vy,"vbias_v":vb,"stage_ratio":r})
        B.append({"point_index":k,"i_m5_a":i5,"vout_v":vout,"vy_v":vy,"vbias_v":vb,"stage_ratio":r})
    ap,bp=work/"A_coverage.csv",work/"B_coverage.csv"; wcsv(ap,A); wcsv(bp,B)
    return ap,bp,vys,vbs,rs

def build_A(base,cov,out,keep):
    s1={"id":"input_pair_fixed_cut",
        "sweeps":{"vtail":{"source":"row_interval","prefix":"ntail","unit":"v","default_lo":0.0,"default_hi":0.899,"count":81}},
        "derived":{"vx":"vy"},
        "devices":[
          {"name":"M1","polarity":"nmos","width":"w1","vgs":"vin-vtail","vds":"vx-vtail","vbs":"vtail-vss"},
          {"name":"M2","polarity":"nmos","width":"w1","vgs":"vin-vtail","vds":"vy-vtail","vbs":"vtail-vss"}],
        "constraints":["M1_domain & M2_domain","(vx-vtail)>=M1_vdsat+sat_margin_v","(vy-vtail)>=M2_vdsat+sat_margin_v",
                       "relerr(M1_id,ib)<=current_rel_tol","relerr(M2_id,ib)<=current_rel_tol"],
        "score":"max(relerr(M1_id,ib),relerr(M2_id,ib))","outputs":{"vtail":"vtail"},
        "selection_coordinates":["vtail"],"per_parent_keep":3,"global_cap":64,"diversity_keys":["vtail"]}
    s2={"id":"tail_fixed_vbias",
        "sweeps":{"w5":{"source":"model_width_interval","polarity":"nmos","row_interval":{"prefix":"w_m5","unit":"um","default_lo":0.42,"default_hi":100.0},"count":120,"spacing":"geom"}},
        "devices":[{"name":"M5","polarity":"nmos","width":"w5","vgs":"vbias-vss","vds":"vtail-vss","vbs":"0.0"}],
        "constraints":["M5_domain","(vtail-vss)>=M5_vdsat+sat_margin_v","relerr(M5_id,i5_target)<=current_rel_tol"],
        "score":"relerr(M5_id,i5_target)","outputs":{"w5":"w5"},"selection_coordinates":["w5"],
        "per_parent_keep":3,"global_cap":64,"diversity_keys":["vtail","w5"]}
    s3={"id":"load_fixed_ratio","derived":{"w3":"0.5*stage_ratio*w5"},
        "devices":[
          {"name":"M3","polarity":"pmos","width":"w3","vgs":"vdd-vy","vds":"vdd-vy","vbs":"0.0"},
          {"name":"M4","polarity":"pmos","width":"w3","vgs":"vdd-vy","vds":"vdd-vy","vbs":"0.0"}],
        "constraints":["M3_domain & M4_domain","(w3>=0.42) & (w3<=100.0)","(vdd-vy)>=M3_vdsat+sat_margin_v",
                       "(vdd-vy)>=M4_vdsat+sat_margin_v","relerr(M3_id,ib)<=current_rel_tol","relerr(M4_id,ib)<=current_rel_tol"],
        "score":"max(relerr(M3_id,ib),relerr(M4_id,ib))","outputs":{"w3":"w3"},
        "selection_coordinates":["w3"],"per_parent_keep":3,"global_cap":64,"diversity_keys":["w5","w3"]}
    bindings={"w1":{"column":"w_m1_um"},"i5_target":{"column":"i_m5_a"},"vy":{"column":"vy_v"},
              "vbias":{"column":"vbias_v"},"stage_ratio":{"column":"stage_ratio"}}
    derived={"ib":"0.5*i5_target","vx":"vy"}
    final={"devices":[dev(base,n) for n in ("M1","M2","M3","M4","M5")],
           "residuals":{k:base["final"]["residuals"][k] for k in ("tail_kcl","x_kcl","y_kcl","mirror_balance","i5_target")},
           "saturation_headroom":{k:base["final"]["saturation_headroom"][k] for k in ("M1","M2","M3","M4","M5")},
           "constraints":["M1_domain & M2_domain & M3_domain & M4_domain & M5_domain",
                          "((vx-vtail)-M1_vdsat)>=sat_margin_v","((vy-vtail)-M2_vdsat)>=sat_margin_v",
                          "((vdd-vx)-M3_vdsat)>=sat_margin_v","((vdd-vy)-M4_vdsat)>=sat_margin_v",
                          "((vtail-vss)-M5_vdsat)>=sat_margin_v"]}
    aliases={"w_m1_um":"w1","i_m5_a":"i5_target","vy_v":"vy","vbias_v":"vbias","stage_ratio":"stage_ratio",
             "vtail_v":"vtail","w_m5_um":"w5","w_m3_um":"w3"}
    return shell(base,"two_stage_A_independent",cov,out,keep,bindings,derived,[s1,s2,s3],final,aliases)

def build_B(base,cov,out,keep):
    s={"id":"output_fixed_interface",
       "sweeps":{"w7":{"source":"model_width_interval","polarity":"nmos","row_interval":{"prefix":"w_m7","unit":"um","default_lo":0.42,"default_hi":100.0},"count":120,"spacing":"geom"}},
       "derived":{"w6":"stage_ratio*w7"},
       "devices":[
         {"name":"M6","polarity":"pmos","width":"w6","vgs":"vdd-vy","vds":"vdd-vout","vbs":"0.0"},
         {"name":"M7","polarity":"nmos","width":"w7","vgs":"vbias-vss","vds":"vout-vss","vbs":"0.0"}],
       "constraints":["M6_domain & M7_domain","(w6>=0.42) & (w6<=100.0)",
                      "(vdd-vout)>=M6_vdsat+sat_margin_v","(vout-vss)>=M7_vdsat+sat_margin_v",
                      "relerr(M6_id,M7_id)<=output_kcl_rel_tol"],
       "score":"relerr(M6_id,M7_id)","outputs":{"w6":"w6","w7":"w7"},"selection_coordinates":["w7"],
       "per_parent_keep":3,"global_cap":64,"diversity_keys":["w7"]}
    bindings={"i5_target":{"column":"i_m5_a"},"vout":{"column":"vout_v"},"vy":{"column":"vy_v"},
              "vbias":{"column":"vbias_v"},"stage_ratio":{"column":"stage_ratio"}}
    final={"devices":[dev(base,"M6"),dev(base,"M7")],
           "residuals":{"output_kcl":base["final"]["residuals"]["output_kcl"]},
           "saturation_headroom":{"M6":base["final"]["saturation_headroom"]["M6"],"M7":base["final"]["saturation_headroom"]["M7"]},
           "constraints":["M6_domain & M7_domain","((vdd-vout)-M6_vdsat)>=sat_margin_v","((vout-vss)-M7_vdsat)>=sat_margin_v"]}
    aliases={"i_m5_a":"i5_target","vout_v":"vout","vy_v":"vy","vbias_v":"vbias","stage_ratio":"stage_ratio",
             "w_m6_um":"w6","w_m7_um":"w7"}
    return shell(base,"two_stage_B_independent",cov,out,keep,bindings,{},[s],final,aliases)

def run(root,engine,plan,keep):
    cmd=[sys.executable,str(engine),"--plan",str(plan),"--root",str(root),"--witnesses-per-point",str(keep)]
    print("\\nRUN:"," ".join(cmd),flush=True); subprocess.run(cmd,cwd=root,check=True)

def q(x): return round(float(x),9)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",type=Path,default=Path(".")); ap.add_argument("--base-plan",type=Path,default=DEFAULT_PLAN)
    ap.add_argument("--engine",type=Path,default=DEFAULT_ENGINE); ap.add_argument("--work-dir",type=Path,default=DEFAULT_WORK)
    ap.add_argument("--w1",type=float,default=25.75); ap.add_argument("--i5-ua",type=float,default=32.5); ap.add_argument("--vout",type=float,default=1.36)
    ap.add_argument("--vy-count",type=int,default=11); ap.add_argument("--vbias-count",type=int,default=9); ap.add_argument("--ratio-count",type=int,default=9)
    ap.add_argument("--witnesses",type=int,default=3)
    args=ap.parse_args()
    root=args.root.resolve(); absr=lambda p:p if p.is_absolute() else (root/p).resolve()
    base=ry(absr(args.base_plan)); engine=absr(args.engine); work=absr(args.work_dir); work.mkdir(parents=True,exist_ok=True)
    acov,bcov,vys,vbs,rs=build_coverages(work,args.w1,args.i5_ua*1e-6,args.vout,args.vy_count,args.vbias_count,args.ratio_count)
    apath,aout=work/"A_plan.yaml",work/"A_table.csv"; bpath,bout=work/"B_plan.yaml",work/"B_table.csv"
    wy(apath,build_A(base,acov,aout,args.witnesses)); wy(bpath,build_B(base,bcov,bout,args.witnesses))
    print("===== INDEPENDENT A TABLE ====="); run(root,engine,apath,args.witnesses)
    print("===== INDEPENDENT B TABLE ====="); run(root,engine,bpath,args.witnesses)
    A={(q(r["vy_v"]),q(r["vbias_v"]),q(r["stage_ratio"])) for r in real(rcsv(aout))}
    B={(q(r["vy_v"]),q(r["vbias_v"]),q(r["stage_ratio"])) for r in real(rcsv(bout))}
    J=A&B
    print("\\n===== TWO-STAGE INDEPENDENT COMPONENT JOIN =====")
    print(f"W1 / I5 / VOUT             : {args.w1:.6g} um / {args.i5_ua:.6g} uA / {args.vout:.6g} V")
    print(f"interface cells            : {len(vys)} x {len(vbs)} x {len(rs)} = {len(vys)*len(vbs)*len(rs)}")
    print(f"A feasible interface cells : {len(A)}"); print(f"B feasible interface cells : {len(B)}"); print(f"A∩B joined cells           : {len(J)}")
    for vy,vb,r in sorted(J)[:20]: print(f"  VY={vy:.6f}  VBIAS={vb:.6f}  R={r:.6f}")
    print(f"\\nA table: {aout}\\nB table: {bout}")
    return 0 if J else 4

if __name__=="__main__": raise SystemExit(main())
