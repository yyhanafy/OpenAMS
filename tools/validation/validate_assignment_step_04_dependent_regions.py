#!/usr/bin/env python3
"""Generic validation for assignment-synthesis Step 4."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from openams.synthesis.dependent_regions import write_dependent_regions


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument('--compiled-model',type=Path,required=True)
    p.add_argument('--independent-regions',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--mode',choices=('generic','two_stage_regression'),default='generic')
    a=p.parse_args()
    artifact=write_dependent_regions(a.compiled_model,a.independent_regions,a.output)
    regions=artifact['dependent_regions']
    checks={
      'status_pass':artifact['status']=='PASS',
      'no_missing_declared_quantities':not artifact['missing_declared_quantities'],
      'all_intervals_nonempty':all(v['minimum']<=v['maximum'] for v in regions.values()),
      'groups_executed':len(artifact['groups'])>0,
      'next_stage_correct':artifact['next_stage']=='intersect_complete_dc_assignments',
    }
    if a.mode=='generic':
      checks['generic_semantics']=artifact.get('resolution_semantics')=='conservative_regions_with_step5_correlation_deferred'
      checks['all_groups_generic']=all(g.get('solver')=='generic_dependency_graph' for g in artifact['groups'])
    else:
      checks['legacy_semantics']=artifact.get('resolution_semantics')=='legacy_adapter_correlated_regions'
      output_group=next(g for g in artifact['groups'] if g['group_id']=='output_stage')
      checks['correlated_output_candidates_exist']=len(output_group.get('correlated_candidates',[]))>0
    passed=all(checks.values())
    compact={k:{'minimum':v['minimum'],'maximum':v['maximum'],'derivation':v.get('derivation')} for k,v in regions.items()}
    report=("# Assignment Synthesis Step 4 Report\n\n"
      f"**Status:** {'PASS' if passed else 'FAIL'}\n\n"
      f"- Mode: `{a.mode}`\n- Groups: {len(artifact['groups'])}\n- Regions: {len(regions)}\n"
      f"- Deferred correlations: {len(artifact.get('deferred_correlations',[]))}\n\n"
      "## Derived Regions\n\n```json\n"+json.dumps(compact,indent=2)+"\n```\n\n"
      "## Checks\n\n```json\n"+json.dumps(checks,indent=2)+"\n```\n")
    a.report.parent.mkdir(parents=True,exist_ok=True); a.report.write_text(report)
    print('===== OPENAMS ASSIGNMENT STEP 4: DEPENDENT REGIONS =====')
    print(f"status:       {'PASS' if passed else 'FAIL'}")
    print(f"mode:         {a.mode}")
    print(f"groups:       {len(artifact['groups'])}")
    print(f"regions:      {len(regions)}")
    print(f"missing:      {artifact['missing_declared_quantities'] or 'none'}")
    print(f"deferred:     {len(artifact.get('deferred_correlations',[]))}")
    print(f"output:       {a.output}")
    if not passed:
      for k,v in checks.items():
        if not v: print(f'[FAIL] {k}')
    return 0 if passed else 1
if __name__=='__main__': raise SystemExit(main())
