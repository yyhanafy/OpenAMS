#!/usr/bin/env python3
"""Audit redundancy/equivalence in an OpenAMS complete_assignments.json artifact."""
from __future__ import annotations

import argparse, csv, json, math, statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Mapping

PROV = ("assignment_id","solution_index","combination_index","row_index","row_id","provenance","source_row","lookup_row","route","physical_proof_level")
GEOM = ("width","w_m","length","l_m","nf","finger","mult")
NODE = ("node","vout","vin","vip","vtail","tail_v","fold","cascode","bias_v","vnb","vpb")
DEV = ("vgs","vsg","vds","vsd","vbs","vsb","vth","vdsat","id_","_id","current","region","saturat")
SS = ("gm","gds","go","ro","cgs","cgd","cdb","csb","cap")

@dataclass(frozen=True)
class Tol:
    voltage_abs_v: float
    current_rel: float
    current_abs_a: float
    width_rel: float
    width_abs_um: float
    gm_rel: float
    gds_rel: float
    capacitance_rel: float


def flatten(d: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, Mapping):
            out.update(flatten(v, key))
        elif isinstance(v, list):
            if len(v) <= 32 and all(x is None or isinstance(x, (str,bool,int,float)) for x in v):
                for i, x in enumerate(v): out[f"{key}[{i}]"] = x
        elif v is None or isinstance(v, (str,bool,int,float)):
            out[key] = v
    return out


def is_prov(k: str) -> bool:
    s = k.lower(); return any(t in s for t in PROV)


def fnum(v: Any):
    if isinstance(v, bool) or v is None: return None
    if isinstance(v, (int,float)) and math.isfinite(float(v)): return float(v)
    return None


def category(k: str):
    s = k.lower()
    if is_prov(k): return None
    if any(t in s for t in SS): return "small_signal"
    if any(t in s for t in GEOM): return "geometry"
    if any(t in s for t in DEV): return "device_state"
    if any(t in s for t in NODE) and not any(t in s for t in ("vgs","vsg","vds","vsd","vbs","vsb","vth","vdsat")):
        return "node"
    return None


def qabs(x: float, step: float):
    return int(round(x/step)) if step > 0 else x


def qrel(x: float, rel: float, abs_: float):
    step = max(abs_, abs(x)*rel)
    return ("bin", int(round(x/step))) if step > 0 else ("exact", x)


def qvalue(k: str, v: Any, c: str, t: Tol):
    x = fnum(v)
    if x is None: return v
    s = k.lower()
    if c == "geometry":
        return qrel(x, t.width_rel, t.width_abs_um if ("width" in s or "w_m" in s) else 0.0)
    if c == "node":
        return ("vbin", qabs(x, t.voltage_abs_v))
    if c == "device_state":
        if any(z in s for z in ("current","id_","_id")): return qrel(x, t.current_rel, t.current_abs_a)
        if any(z in s for z in ("vgs","vsg","vds","vsd","vbs","vsb","vth","vdsat")): return ("vbin", qabs(x, t.voltage_abs_v))
        return x
    if c == "small_signal":
        if "gm" in s: return qrel(x, t.gm_rel, 0.0)
        if any(z in s for z in ("gds","go","ro")): return qrel(x, t.gds_rel, 0.0)
        if any(z in s for z in ("cgs","cgd","cdb","csb","cap")): return qrel(x, t.capacitance_rel, 0.0)
    return x


def exact_sig(a: Mapping[str, Any], digits: int):
    flat = flatten(a)
    return tuple(sorted((k, round(v, digits) if isinstance(v,(int,float)) and not isinstance(v,bool) else v)
                        for k,v in flat.items() if not is_prov(k)))


def cat_sig(a: Mapping[str, Any], cats: set[str], t: Tol):
    vals=[]
    for k,v in flatten(a).items():
        c=category(k)
        if c in cats: vals.append((k,qvalue(k,v,c,t)))
    return tuple(sorted(vals))


def summarize(name: str, source_count: int, sigs):
    counts=Counter(sigs); sizes=sorted(counts.values(), reverse=True)
    classes=len(counts); dup=max(0,source_count-classes)
    return {
        "level":name,"source_count":source_count,"class_count":classes,
        "duplicate_count":dup,"reduction_fraction":0 if source_count==0 else dup/source_count,
        "mean_class_size":0 if not sizes else statistics.mean(sizes),
        "median_class_size":0 if not sizes else statistics.median(sizes),
        "max_class_size":0 if not sizes else sizes[0],
        "singleton_classes":sum(1 for x in sizes if x==1),
        "largest_class_sizes":sizes[:20],
    }, counts


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, default=Path("runtime/folded_assignment_equivalence_audit"))
    ap.add_argument("--exact-digits", type=int, default=12)
    ap.add_argument("--voltage-abs-v", type=float, default=2e-3)
    ap.add_argument("--current-rel", type=float, default=5e-3)
    ap.add_argument("--current-abs-a", type=float, default=1e-9)
    ap.add_argument("--width-rel", type=float, default=5e-3)
    ap.add_argument("--width-abs-um", type=float, default=1e-3)
    ap.add_argument("--gm-rel", type=float, default=1e-2)
    ap.add_argument("--gds-rel", type=float, default=2e-2)
    ap.add_argument("--capacitance-rel", type=float, default=2e-2)
    args=ap.parse_args()

    data=json.loads(args.input.read_text())
    assignments=data.get("assignments") or data.get("complete_assignments")
    if not isinstance(assignments,list): raise SystemExit("No assignments list found")
    assignments=[a for a in assignments if isinstance(a,Mapping)]
    print(f"Raw assignments: {len(assignments):,}")

    reps={}; exact_counts=Counter()
    for a in assignments:
        s=exact_sig(a,args.exact_digits); exact_counts[s]+=1; reps.setdefault(s,a)
    exact_reps=list(reps.values())
    exact_summary,_=summarize("exact_canonical",len(assignments),(exact_sig(a,args.exact_digits) for a in assignments))
    print(f"Exact unique: {len(exact_reps):,}")

    t=Tol(args.voltage_abs_v,args.current_rel,args.current_abs_a,args.width_rel,args.width_abs_um,args.gm_rel,args.gds_rel,args.capacitance_rel)
    levels=[
        ("geometry",{"geometry"}),
        ("node_voltage",{"node"}),
        ("device_state",{"device_state"}),
        ("small_signal",{"small_signal"}),
        ("combined_dc",{"geometry","node","device_state"}),
        ("combined_small_signal",{"geometry","node","device_state","small_signal"}),
    ]
    summaries=[exact_summary]; class_sizes={"exact_canonical":sorted(exact_counts.values(),reverse=True)}
    for name,cats in levels:
        sm,counts=summarize(name,len(exact_reps),(cat_sig(a,cats,t) for a in exact_reps))
        summaries.append(sm); class_sizes[name]=sorted(counts.values(),reverse=True)
        print(f"{name}: {sm['class_count']:,} classes, reduction {sm['reduction_fraction']:.2%}")

    discovered=defaultdict(set)
    for a in exact_reps[:1000]:
        for k in flatten(a):
            c=category(k)
            if c: discovered[c].add(k)

    args.output.mkdir(parents=True,exist_ok=True)
    payload={
        "artifact":"openams.assignment_equivalence_audit","schema_version":1,
        "input_artifact":str(args.input.resolve()),
        "input_metadata":{k:data.get(k) for k in (
            "artifact","schema_version","status","circuit_name","algorithm","device_provider",
            "compiled_model","independent_regions","dependent_regions","technology_source",
            "independent_variable_names","independent_values","independent_combination_count",
            "complete_assignment_count","recommended_route")},
        "raw_assignment_count_loaded":len(assignments),"tolerances":asdict(t),
        "summaries":summaries,"discovered_fields":{k:sorted(v) for k,v in discovered.items()},
    }
    (args.output/"equivalence_audit.json").write_text(json.dumps(payload,indent=2,sort_keys=True))
    (args.output/"class_size_distributions.json").write_text(json.dumps(class_sizes,indent=2,sort_keys=True))
    with (args.output/"equivalence_summary.csv").open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(summaries[0].keys())); w.writeheader()
        for r in summaries:
            rr=dict(r); rr["largest_class_sizes"]=json.dumps(rr["largest_class_sizes"]); w.writerow(rr)

    md=["# OpenAMS Assignment Equivalence Audit","",f"Input: `{args.input}`","",
        "| Level | Source | Classes | Duplicates | Reduction | Max class | Singletons |",
        "|---|---:|---:|---:|---:|---:|---:|"]
    for r in summaries:
        md.append(f"| {r['level']} | {r['source_count']:,} | {r['class_count']:,} | {r['duplicate_count']:,} | {r['reduction_fraction']:.2%} | {r['max_class_size']:,} | {r['singleton_classes']:,} |")
    (args.output/"EQUIVALENCE_AUDIT.md").write_text("\n".join(md))
    print(f"\nWrote audit to {args.output}")

if __name__ == "__main__":
    main()
