#!/usr/bin/env python3
"""Patch the generic DC audit to validate output-connected devices over VOUT ranges."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

target = Path(
    sys.argv[1]
    if len(sys.argv) > 1
    else "tools/validation/audit_generic_dc_assignments.py"
)

text = target.read_text(encoding="utf-8")

old = """  if avds is None:fails.append('VDS_UNRESOLVED')
  else:
   if minv is not None and avds+tol<minv:fails.append(f'VDS_BELOW_MIN actual={avds:.12g} min={minv:.12g}')
   elif maxv is not None and avds-tol>maxv:fails.append(f'VDS_ABOVE_MAX actual={avds:.12g} max={maxv:.12g}')
   else:checks.append('vds_range')
   if vdsat is not None and avds+tol<vdsat:fails.append(f'NOT_SATURATED actual_vds={avds:.12g} vdsat={vdsat:.12g}')
   else:checks.append('saturation')
"""

new = """  if avds is None:
   # A missing exact drain voltage is valid when this device drains into the
   # ranged output node and the assignment provides a nonempty VOUT window.
   vout_lo=pnum(a,'vout_min_v');vout_hi=pnum(a,'vout_max_v')
   output_drain=d in {'out','vout'}
   if output_drain and vs is not None and vout_lo is not None and vout_hi is not None and vout_lo<vout_hi:
    if p=='nmos':
     ranged_vds_lo=vout_lo-vs;ranged_vds_hi=vout_hi-vs
    else:
     ranged_vds_lo=vs-vout_hi;ranged_vds_hi=vs-vout_lo
    if minv is not None and ranged_vds_lo+tol<minv:
     fails.append(f'RANGED_VDS_BELOW_MIN range=[{ranged_vds_lo:.12g},{ranged_vds_hi:.12g}] min={minv:.12g}')
    elif maxv is not None and ranged_vds_hi-tol>maxv:
     fails.append(f'RANGED_VDS_ABOVE_MAX range=[{ranged_vds_lo:.12g},{ranged_vds_hi:.12g}] max={maxv:.12g}')
    else:
     checks.append('vds_range_ranged_vout')
    if vdsat is not None and ranged_vds_lo+tol<vdsat:
     fails.append(f'RANGED_NOT_SATURATED range=[{ranged_vds_lo:.12g},{ranged_vds_hi:.12g}] vdsat={vdsat:.12g}')
    else:
     checks.append('saturation_ranged_vout')
   else:
    fails.append('VDS_UNRESOLVED')
  else:
   if minv is not None and avds+tol<minv:fails.append(f'VDS_BELOW_MIN actual={avds:.12g} min={minv:.12g}')
   elif maxv is not None and avds-tol>maxv:fails.append(f'VDS_ABOVE_MAX actual={avds:.12g} max={maxv:.12g}')
   else:checks.append('vds_range')
   if vdsat is not None and avds+tol<vdsat:fails.append(f'NOT_SATURATED actual_vds={avds:.12g} vdsat={vdsat:.12g}')
   else:checks.append('saturation')
"""

if new in text:
    print("[INFO] ranged-VOUT audit logic already installed")
elif old in text:
    backup = target.with_suffix(target.suffix + ".before_ranged_vout_audit_fix")
    if not backup.exists():
        shutil.copy2(target, backup)
    text = text.replace(old, new, 1)
    target.write_text(text, encoding="utf-8")
    print(f"[PASS] patched: {target}")
    print(f"[PASS] backup:  {backup}")
else:
    raise SystemExit("[FAIL] could not locate VDS_UNRESOLVED audit block")
