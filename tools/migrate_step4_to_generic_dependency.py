#!/usr/bin/env python3
"""Migrate assignment-synthesis groups to the generic Step-4 engine."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import yaml


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument('--design-intent',type=Path,required=True)
    p.add_argument('--compiled-model',type=Path)
    a=p.parse_args()
    data=yaml.safe_load(a.design_intent.read_text())
    groups=data['assignment_synthesis']['groups']
    for group in groups:
        group['legacy_solver']=group.get('solver')
        group['solver']='generic_dependency_graph'
    a.design_intent.write_text(yaml.safe_dump(data,sort_keys=False))
    print(f'[PASS] migrated {a.design_intent}')
    if a.compiled_model:
        model=json.loads(a.compiled_model.read_text())
        intent=model['project_inputs']['design_intent']
        for group in intent['assignment_synthesis']['groups']:
            group['legacy_solver']=group.get('solver')
            group['solver']='generic_dependency_graph'
        a.compiled_model.write_text(json.dumps(model,indent=2)+'\n')
        print(f'[PASS] migrated {a.compiled_model}')
    return 0
if __name__=='__main__': raise SystemExit(main())
