#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, json, math, statistics
from collections import Counter, defaultdict
from pathlib import Path


def f(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def stats(vals):
    a=sorted(x for x in vals if x is not None)
    if not a:
        return {k:None for k in ('min','max','mean','median','p95')} | {'count':0}
    return {
        'count':len(a),'min':a[0],'max':a[-1],
        'mean':statistics.fmean(a),'median':statistics.median(a),
        'p95':a[min(len(a)-1, math.ceil(.95*len(a))-1)],
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--results',type=Path,default=Path('examples/two_stage_opamp/generated/generic_ngspice_validation/generic_100_case_results.csv'))
    ap.add_argument('--assignments',type=Path,default=Path('examples/two_stage_opamp/generated/assignment_synthesis/generic_assignments_smoke.json'))
    ap.add_argument('--output-dir',type=Path,default=Path('examples/two_stage_opamp/generated/generic_ngspice_validation/analysis'))
    a=ap.parse_args()

    with a.results.open(newline='',encoding='utf-8') as s:
        results=list(csv.DictReader(s))
    art=json.loads(a.assignments.read_text())
    assignments={str(r['assignment_id']):r for r in art['assignments']}
    rows=[{**assignments.get(str(r['assignment_id']),{}),**r} for r in results]

    metric_map={
        'gain_ngspice_db':'gain_db','gain_table_estimate_db':'gain_table_estimate_db',
        'gain_abs_error_db':'gain_error_db','ugb_ngspice_hz':'ugb_hz',
        'phase_margin_ngspice_deg':'phase_margin_deg',
    }
    metrics={name:stats([f(r.get(col)) for r in rows]) for name,col in metric_map.items()}

    errors={}
    for m in ('gm','gds'):
        for i in range(1,8):
            col=f'{m}_relative_error_m{i}'
            errors[col]=stats([f(r.get(col)) for r in rows])

    coverage={}
    for col in ('i_m5_a','w_m1_um','vout_v'):
        vals=[f(r.get(col)) for r in rows]; clean=[x for x in vals if x is not None]
        coverage[col]=stats(clean)|{'unique_count':len(set(clean))}

    physical_fields=[*(f'i_m{i}_a' for i in range(1,8)),*(f'w_m{i}_um' for i in range(1,8)),'vtail_v','n1_v','n2_v','vbias_v','vout_v']
    exact=defaultdict(list); practical=defaultdict(list); ac=defaultdict(list)
    for r in rows:
        aid=str(r['assignment_id'])
        exact[tuple(None if f(r.get(c)) is None else round(f(r.get(c)),12) for c in physical_fields)].append(aid)
        pk=[]
        for c in physical_fields:
            x=f(r.get(c))
            if x is None: pk.append(None)
            elif c.startswith('i_'): pk.append(round(x,9))
            elif c.startswith('w_'): pk.append(round(x,3))
            else: pk.append(round(x,4))
        practical[tuple(pk)].append(aid)
        g,u,p=f(r.get('gain_db')),f(r.get('ugb_hz')),f(r.get('phase_margin_deg'))
        ac[(None if g is None else round(g,1),None if u is None or u<=0 else round(math.log10(u),2),None if p is None else round(2*p)/2)].append(aid)

    uniqueness={
        'exact_physical_unique_count':len(exact),
        'exact_duplicate_group_count':sum(len(v)>1 for v in exact.values()),
        'practical_physical_unique_count':len(practical),
        'practical_duplicate_group_count':sum(len(v)>1 for v in practical.values()),
        'ac_equivalence_class_count':len(ac),
        'ac_equivalence_multi_member_groups':sum(len(v)>1 for v in ac.values()),
    }

    report={
        'artifact':'openams.generic_100_case_results_analysis','cases':len(rows),
        'status_counts':dict(Counter(r.get('status','UNKNOWN') for r in rows)),
        'metric_summaries':metrics,'device_error_summaries':errors,
        'independent_variable_coverage':coverage,'uniqueness':uniqueness,
        'example_ac_equivalence_groups':[v for v in ac.values() if len(v)>1][:10],
    }
    a.output_dir.mkdir(parents=True,exist_ok=True)
    jp=a.output_dir/'generic_100_case_analysis.json'
    mp=a.output_dir/'GENERIC_100_CASE_ANALYSIS_REPORT.md'
    jp.write_text(json.dumps(report,indent=2)+'\n')

    lines=['# Generic 100-Case Analysis','',f"- Cases: {len(rows)}",f"- Status counts: `{json.dumps(report['status_counts'],sort_keys=True)}`",'', '## AC metric ranges','', '| Metric | Min | Max | Mean | Median | P95 |','|---|---:|---:|---:|---:|---:|']
    for n,s in metrics.items(): lines.append(f"| {n} | {s['min']} | {s['max']} | {s['mean']} | {s['median']} | {s['p95']} |")
    lines += ['', '## Independent-variable coverage','', '| Variable | Min | Max | Unique |','|---|---:|---:|---:|']
    for n,s in coverage.items(): lines.append(f"| {n} | {s['min']} | {s['max']} | {s['unique_count']} |")
    lines += ['', '## Uniqueness',''] + [f'- {k}: {v}' for k,v in uniqueness.items()]
    lines += ['', '## Interpretation','', 'This is a first-solution sample, not an exhaustive or uniform design-space sweep. The coverage counts show whether the 100 cases span the declared independent-variable ranges or cluster near the beginning of solver order. AC-equivalence bins use approximately 0.1 dB gain, 1% UGB, and 0.5° phase margin.']
    mp.write_text('\n'.join(lines)+'\n')

    print('===== GENERIC 100-CASE RESULTS ANALYSIS =====')
    print('cases:',len(rows)); print('status counts:',report['status_counts'])
    for n,s in metrics.items(): print(f"{n}: min={s['min']} max={s['max']} mean={s['mean']}")
    print('coverage:')
    for n,s in coverage.items(): print(f"  {n}: min={s['min']} max={s['max']} unique={s['unique_count']}")
    print('uniqueness:',uniqueness)
    print('json:',jp); print('report:',mp)
    return 0

if __name__=='__main__': raise SystemExit(main())
