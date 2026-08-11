#!/usr/bin/env python3
from pathlib import Path
import shutil
import yaml

ROOT = Path.home() / "AMS-Tutorial" / "openams"
ENGINE = ROOT / "src/openams/validation/ngspice_witness.py"
PLAN = ROOT / "examples/two_stage_opamp/inputs/ngspice_validation.yaml"

def backup(path, suffix):
    bak = path.with_suffix(path.suffix + suffix)
    shutil.copy2(path, bak)
    return bak

def patch_engine():
    s = ENGINE.read_text(encoding="utf-8")

    old_sig = 'def _parse_ac_raw(path: Path, output_name: str) -> dict[str, float]:'
    new_sig = 'def _parse_ac_raw(path: Path, output_name: str, transfer_sign: float = 1.0) -> dict[str, float]:'
    if old_sig in s:
        s = s.replace(old_sig, new_sig, 1)
    elif new_sig not in s:
        raise RuntimeError("AC parser signature not found")

    old = '''    freq = freq[order]
    out = out[order]

    magnitude = np.abs(out)
'''
    new = '''    freq = freq[order]
    out = out[order]

    # Normalize the measured transfer-function polarity before extracting
    # phase.  This is plan-configurable so every topology uses the same PM
    # implementation without topology-specific phase hacks.
    sign = float(transfer_sign)
    if sign not in (-1.0, 1.0):
        raise ValueError(f"transfer_sign must be +1 or -1, got {sign}")
    out = sign * out

    magnitude = np.abs(out)
'''
    if "sign = float(transfer_sign)" not in s:
        if old not in s:
            raise RuntimeError("AC output normalization block not found")
        s = s.replace(old, new, 1)

    old = '''                ac_metrics = (
                    _parse_ac_raw(ac_path, (plan.get("ac") or {}).get("output", "v(out)"))
                    if (plan.get("ac") or {}).get("enabled", False)
                    and proc.returncode == 0
                    else {}
                )'''
    new = '''                ac_cfg = plan.get("ac") or {}
                ac_metrics = (
                    _parse_ac_raw(
                        ac_path,
                        ac_cfg.get("output", "v(out)"),
                        float(ac_cfg.get("transfer_sign", 1.0)),
                    )
                    if ac_cfg.get("enabled", False)
                    and proc.returncode == 0
                    else {}
                )'''
    if 'ac_cfg.get("transfer_sign"' not in s:
        if old not in s:
            raise RuntimeError("AC parser call block not found")
        s = s.replace(old, new, 1)

    bak = backup(ENGINE, ".before_transfer_sign.bak")
    ENGINE.write_text(s, encoding="utf-8")
    print("engine backup:", bak)
    print("engine patched:", ENGINE)

def patch_plan():
    plan = yaml.safe_load(PLAN.read_text(encoding="utf-8"))
    ac = plan.setdefault("ac", {})
    ac["transfer_sign"] = -1
    bak = backup(PLAN, ".before_transfer_sign.bak")
    PLAN.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")
    print("plan backup:", bak)
    print("plan patched:", PLAN)
    print("ac.transfer_sign:", ac["transfer_sign"])

if __name__ == "__main__":
    if not ENGINE.is_file():
        raise SystemExit(f"missing: {ENGINE}")
    if not PLAN.is_file():
        raise SystemExit(f"missing: {PLAN}")
    patch_engine()
    patch_plan()
