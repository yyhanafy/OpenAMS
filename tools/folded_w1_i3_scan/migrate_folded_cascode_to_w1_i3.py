#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, shutil
from pathlib import Path
from typing import Any, MutableMapping
import yaml

def mapping(value: Any, label: str) -> MutableMapping[str, Any]:
    if not isinstance(value, MutableMapping):
        raise SystemExit(f"[FAIL] {label} is not a mapping")
    return value

def backup(path: Path) -> None:
    dst = path.with_suffix(path.suffix + ".before_w1_i3_migration")
    if not dst.exists():
        shutil.copy2(path, dst)

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--design-intent', type=Path, default=Path('examples/folded_cascode/inputs/design_intent.yaml'))
    ap.add_argument('--compiled-model', type=Path, default=Path('examples/folded_cascode/generated/compiled_circuit_model.json'))
    args = ap.parse_args()

    data = yaml.safe_load(args.design_intent.read_text())
    root = mapping(data, 'design_intent')
    sp = mapping(root['synthesis_parameterization'], 'synthesis_parameterization')
    indep = mapping(sp['independent_variables'], 'independent_variables')
    indep.pop('vnb1_v', None)
    dep = mapping(sp.setdefault('dependent_variables', {}), 'dependent_variables')
    dep['vnb1_v'] = {
        'kind': 'bias_voltage',
        'device': 'M3',
        'terminal': 'gate',
        'role': 'technology_derived_tail_bias',
        'derivation': {
            'method': 'inverse_feasible_device_realization',
            'current': 'i_m3_a',
            'relation': 'source_voltage_plus_vgs',
        },
    }
    ci = root.get('circuit_intent', {})
    if isinstance(ci, MutableMapping):
        bn = ci.get('bias_nodes', {})
        if isinstance(bn, MutableMapping) and isinstance(bn.get('vnb1_v'), MutableMapping):
            bn['vnb1_v']['role'] = 'dependent_tail_bias'
            bn['vnb1_v']['selection_policy'] = 'inverse_feasible_realization'
    backup(args.design_intent)
    args.design_intent.write_text(yaml.safe_dump(data, sort_keys=False, width=100))
    print(f"[PASS] migrated {args.design_intent}")

    model = json.loads(args.compiled_model.read_text())
    si = mapping(model['synthesis_interface'], 'synthesis_interface')
    si['independent_variables'] = [x for x in si['independent_variables'] if x.get('id') != 'vnb1_v']
    backup(args.compiled_model)
    args.compiled_model.write_text(json.dumps(model, indent=2) + '\n')
    names = [x['id'] for x in si['independent_variables']]
    print('[PASS] compiled independent variables:', names)
    if names != ['w_m1_um', 'i_m3_a']:
        raise SystemExit(f"[FAIL] expected ['w_m1_um','i_m3_a'], found {names}")
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
