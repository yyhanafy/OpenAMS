#!/usr/bin/env python3
from pathlib import Path
import shutil

ROOT = Path.home() / "AMS-Tutorial" / "openams"

def backup(p):
    b = p.with_suffix(p.suffix + ".before_supply_power.bak")
    shutil.copy2(p, b)
    return b

def patch_two_stage():
    p = ROOT / "tools/validation/run_two_stage_native_witness_ngspice.py"
    if not p.is_file():
        raise SystemExit(f"missing: {p}")
    s = p.read_text()

    old = '''        "print v(xu1.ntail) v(xu1.n1) v(xu1.n2) v(vbias) v(out)",
        "echo OPENAMS_OP_END",'''
    new = '''        "print v(xu1.ntail) v(xu1.n1) v(xu1.n2) v(vbias) v(out)",
        "print vdd_src#branch",
        "echo OPENAMS_OP_END",'''
    if "print vdd_src#branch" not in s:
        if old not in s:
            raise RuntimeError("two-stage OP block not found")
        s = s.replace(old, new, 1)

    old = '''        "vout_v": ["v(out)", "out"],
    }'''
    new = '''        "vout_v": ["v(out)", "out"],
        "supply_current_a": ["vdd_src#branch"],
    }'''
    if '"supply_current_a": ["vdd_src#branch"]' not in s:
        if old not in s:
            raise RuntimeError("two-stage parse_nodes map not found")
        s = s.replace(old, new, 1)

    old = '''def ac_metrics(path):
    f,gain,phase = parse_ac(path)
    rel = phase-phase[0]
    unwrapped=np.rad2deg(np.unwrap(np.deg2rad(rel)))
    g0=float(gain[0])
    out={"gain_db":g0,"gain_v_v":10**(g0/20)}
    bw=cross(f,gain,g0-3)
    out["bandwidth_3db_hz"]=None if bw is None else float(bw[1])
    ug=cross(f,gain,0.0)
    if ug is None:
        out.update({"ugb_hz":None,"phase_at_ugb_deg":None,"phase_margin_deg":None})
    else:
        i,u=ug
        ph=interp_log(u,float(f[i]),float(f[i+1]),float(unwrapped[i]),float(unwrapped[i+1]))
        ph=(ph+180)%360-180
        out.update({"ugb_hz":float(u),"phase_at_ugb_deg":float(ph),"phase_margin_deg":180+float(ph)})
    return out
'''
    new = '''def ac_metrics(path):
    f,gain,phase_raw = parse_ac(path)
    phase_unwrapped = np.rad2deg(np.unwrap(np.deg2rad(phase_raw)))

    g0=float(gain[0])
    out={
        "gain_db":g0,
        "gain_v_v":10**(g0/20),
        "phase_low_frequency_raw_deg":float(phase_raw[0]),
        "phase_low_frequency_unwrapped_deg":float(phase_unwrapped[0]),
    }
    bw=cross(f,gain,g0-3)
    out["bandwidth_3db_hz"]=None if bw is None else float(bw[1])
    ug=cross(f,gain,0.0)
    if ug is None:
        out.update({
            "ugb_hz":None,
            "phase_at_ugb_raw_deg":None,
            "phase_at_ugb_unwrapped_deg":None,
            "phase_at_ugb_deg":None,
            "phase_margin_deg":None,
        })
    else:
        i,u=ug
        ph_raw=interp_log(
            u,float(f[i]),float(f[i+1]),
            float(phase_raw[i]),float(phase_raw[i+1])
        )
        ph=interp_log(
            u,float(f[i]),float(f[i+1]),
            float(phase_unwrapped[i]),float(phase_unwrapped[i+1])
        )
        out.update({
            "ugb_hz":float(u),
            "phase_at_ugb_raw_deg":float(ph_raw),
            "phase_at_ugb_unwrapped_deg":float(ph),
            "phase_at_ugb_deg":float(ph),
            "phase_margin_deg":180.0+float(ph),
        })
    return out
'''
    if "phase_at_ugb_unwrapped_deg" not in s:
        if old not in s:
            raise RuntimeError("two-stage ac_metrics block not found")
        s = s.replace(old, new, 1)

    b = backup(p)
    p.write_text(s)
    print("two-stage backup:", b)
    print("two-stage patched:", p)

def patch_folded():
    p = ROOT / "tools/validation/run_folded_cascode_native_witness_ngspice.py"
    if not p.is_file():
        print("folded runner not found; skipped")
        return
    s = p.read_text()

    old = '''        f"print {node_prints}",
        "echo OPENAMS_OP_END",'''
    new = '''        f"print {node_prints}",
        "print vdd_supply#branch",
        "echo OPENAMS_OP_END",'''
    if "print vdd_supply#branch" not in s:
        if old not in s:
            raise RuntimeError("folded OP block not found")
        s = s.replace(old, new, 1)

    b = backup(p)
    p.write_text(s)
    print("folded backup:", b)
    print("folded patched:", p)

if __name__ == "__main__":
    patch_two_stage()
    patch_folded()
    print("DONE")
