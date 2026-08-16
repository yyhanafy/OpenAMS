"""Generic technology-backed Step-4 region primitives.

These primitives are configured by metadata. They contain no topology names and
make no assumptions about concrete device labels beyond the roles declared in a
solver configuration.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from .dependent_regions import (
    DependentRegionError, TechRow, _candidate_current_interval, _clip_interval,
    _derived_width_interval, _device_map, _domain_interval, _filtered_rows,
    _intersect, _interval, _legal_total_width, _minimum_nf, _num,
    _required_total_width, _row_can_realize_current_interval, _scale_interval,
    _values_interval, _width_policy,
)


def _cfg(group: Mapping[str, Any]) -> Mapping[str, Any]:
    config = group.get("solver_config")
    if not isinstance(config, Mapping):
        raise DependentRegionError(f"group {group.get('id')!r} has no solver_config")
    return config


def _name(config: Mapping[str, Any], section: str, key: str) -> str:
    values = config.get(section, {})
    value = values.get(key) if isinstance(values, Mapping) else None
    if not value:
        raise DependentRegionError(f"solver_config.{section}.{key} is required")
    return str(value)


def solve_matched_input_network(
    model: Mapping[str, Any], independent: Mapping[str, Any], rows: Sequence[TechRow],
    group: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive a differential-input, diode-load, and tail-bias network.

    Device identities and variable names are supplied by ``solver_config``.
    """
    config = _cfg(group)
    devices = _device_map(model)
    roles = config["devices"]
    var = config["variables"]
    left = str(roles["input_left"]).upper()
    right = str(roles["input_right"]).upper()
    diode = str(roles["load_diode"]).upper()
    mirror = str(roles["load_mirror"]).upper()
    tail = str(roles["tail"]).upper()

    rules = model["project_inputs"]["design_rules"]
    operating = rules["operating_conditions"]
    device_rules = rules["device_constraints"]["all_mos"]
    length_um = _num(device_rules["length_um"], "length_um")
    body_limit = _num(device_rules["body_voltage_abs_max_v"], "body limit")
    width_policy = _width_policy(model)
    vdd = _num(operating["vdd_v"], "vdd_v")
    vss = _num(operating["vss_v"], "vss_v")
    vin_cm = _num(operating["vin_cm_v"], "vin_cm_v")

    seed_i = _candidate_current_interval(independent["domains"][str(var["seed_current"])])
    seed_w = _domain_interval(independent["domains"][str(var["seed_width"])])
    branch_scale = _num(config.get("branch_current_scale", 0.5), "branch_current_scale")
    branch_i = _scale_interval(seed_i, branch_scale)

    left_rows = _filtered_rows(rows, devices[left], length_um=length_um, body_limit_v=body_limit)
    diode_rows = _filtered_rows(rows, devices[diode], length_um=length_um, body_limit_v=body_limit)
    tail_rows = _filtered_rows(rows, devices[tail], length_um=length_um, body_limit_v=body_limit)

    feasible_left = tuple(r for r in left_rows if _row_can_realize_current_interval(r, branch_i, seed_w))
    if not feasible_left:
        raise DependentRegionError(f"{left} has no feasible technology rows")

    vtail = _clip_interval(_values_interval((vin_cm-r.vgs_v for r in feasible_left), "tail node"), vss, vin_cm)
    feasible_left = tuple(r for r in feasible_left if vtail["minimum"] <= vin_cm-r.vgs_v <= vtail["maximum"])
    feasible_tail = tuple(r for r in tail_rows if vtail["minimum"] <= vss+r.vds_v <= vtail["maximum"])
    if not feasible_tail:
        raise DependentRegionError(f"{tail} has no rows consistent with tail node")

    n1_from_input = _clip_interval(_values_interval((vin_cm-r.vgs_v+r.vds_v for r in feasible_left), "first internal node"), vss, vdd)
    bias = _clip_interval(_values_interval((vss+r.vgs_v for r in feasible_tail), "bias"), vss, vdd)
    tail_width = _derived_width_interval(feasible_tail, seed_i, width_policy)

    diode_tol = _num(rules["technology_intersection"]["diode_voltage_tolerance_v"], "diode tolerance")
    feasible_diode = tuple(r for r in diode_rows if abs(r.vgs_v-r.vds_v) <= diode_tol and n1_from_input["minimum"]-diode_tol <= vdd-r.vgs_v <= n1_from_input["maximum"]+diode_tol)
    if not feasible_diode:
        raise DependentRegionError(f"{diode} has no diode-connected feasible rows")
    n1 = _intersect(n1_from_input, _clip_interval(_values_interval((vdd-r.vgs_v for r in feasible_diode), "first internal node from load"), vss, vdd))
    load_width = _derived_width_interval(feasible_diode, branch_i, width_policy)
    feasible_mirror = tuple(r for r in diode_rows if n1["minimum"]-diode_tol <= vdd-r.vgs_v <= n1["maximum"]+diode_tol)
    if not feasible_mirror:
        raise DependentRegionError(f"{mirror} has no gate-compatible feasible rows")
    n2 = _clip_interval(_values_interval((vdd-r.vds_v for r in feasible_mirror), "second internal node"), vss, vdd)

    dependent = {
        str(var["input_left_current"]): dict(branch_i),
        str(var["input_right_current"]): dict(branch_i),
        str(var["load_diode_current"]): dict(branch_i),
        str(var["load_mirror_current"]): dict(branch_i),
        str(var["input_right_width"]): dict(seed_w),
        str(var["load_diode_width"]): load_width,
        str(var["load_mirror_width"]): dict(load_width),
        str(var["tail_width"]): tail_width,
        str(var["tail_node"]): vtail,
        str(var["first_internal_node"]): n1,
        str(var["second_internal_node"]): n2,
        str(var["bias_node"]): bias,
    }
    return {
        "group_id": str(group["id"]), "solver_type": "matched_input_network", "status": "PASS",
        "dependent_regions": dependent,
        "technology_support": {left: len(feasible_left), diode: len(feasible_diode), mirror: len(feasible_mirror), tail: len(feasible_tail)},
        "physical_clipping": {str(var["tail_node"]): {"minimum": vss, "maximum": vin_cm}, str(var["first_internal_node"]): {"minimum": vss, "maximum": vdd}, str(var["second_internal_node"]): {"minimum": vss, "maximum": vdd}, str(var["bias_node"]): {"minimum": vss, "maximum": vdd}},
    }


def solve_correlated_output_pair(
    model: Mapping[str, Any], independent: Mapping[str, Any], upstream: Mapping[str, Any],
    rows: Sequence[TechRow], group: Mapping[str, Any],
) -> dict[str, Any]:
    """Build atomic upper/lower output-device candidates and a headroom range."""
    config = _cfg(group); devices = _device_map(model); roles=config["devices"]; var=config["variables"]
    upper=str(roles["upper"]).upper(); lower=str(roles["lower"]).upper()
    rules=model["project_inputs"]["design_rules"]; operating=rules["operating_conditions"]
    dr=rules["device_constraints"]["all_mos"]; length=_num(dr["length_um"],"length"); body=_num(dr["body_voltage_abs_max_v"],"body")
    policy=_width_policy(model); vdd=_num(operating["vdd_v"],"vdd"); vss=_num(operating["vss_v"],"vss")
    dep=upstream["dependent_regions"]; upper_gate=dep[str(var["upper_gate_node"])]; lower_gate=dep[str(var["lower_gate_node"])]
    tol=_num(rules["technology_intersection"]["node_voltage_tolerance_v"],"node tolerance")
    upper_rows=_filtered_rows(rows,devices[upper],length_um=length,body_limit_v=body); lower_rows=_filtered_rows(rows,devices[lower],length_um=length,body_limit_v=body)
    upper_rows=tuple(r for r in upper_rows if upper_gate["minimum"]-tol <= vdd-r.vgs_v <= upper_gate["maximum"]+tol)
    lower_rows=tuple(r for r in lower_rows if lower_gate["minimum"]-tol <= vss+r.vgs_v <= lower_gate["maximum"]+tol)
    if not upper_rows or not lower_rows: raise DependentRegionError("correlated output pair has no feasible rows")

    ranged=model["project_inputs"]["design_intent"].get("synthesis_parameterization",{}).get("dependent_ranged_variables",{}).get(str(var["output_range"]))
    exact_name=str(var["output_range"]); exact_mode=exact_name in independent.get("domains",{})
    if exact_mode: bounds=_domain_interval(independent["domains"][exact_name])
    elif isinstance(ranged,Mapping):
        declared=ranged.get("declared_bounds",{}); bounds={"minimum":_num(declared.get("minimum",vss),"min"),"maximum":_num(declared.get("maximum",vdd),"max")}
    else: raise DependentRegionError("output range requires an independent domain or dependent-ranged contract")

    correlated=[]; max_records=int(config.get("max_candidates",100000))
    for ru in upper_rows:
      for rl in lower_rows:
        out_u=vdd-ru.vds_v; out_l=vss+rl.vds_v
        if exact_mode and abs(out_u-out_l)>tol: continue
        if exact_mode: lo=hi=0.5*(out_u+out_l)
        else:
          margin=_num(ranged.get("margin_v",0.0),"margin"); lo=max(bounds["minimum"],vss+rl.vdsat_v+margin); hi=min(bounds["maximum"],vdd-ru.vdsat_v-margin)
          if lo>hi: continue
        # Common current interval induced by legal total-width range.
        iu_min=ru.id_a*policy["total_min_um"]/ru.width_um; iu_max=ru.id_a*policy["total_max_um"]/ru.width_um
        il_min=rl.id_a*policy["total_min_um"]/rl.width_um; il_max=rl.id_a*policy["total_max_um"]/rl.width_um
        cmin=max(iu_min,il_min); cmax=min(iu_max,il_max)
        if cmin>cmax: continue
        for current in (cmin,cmax):
          wu=_required_total_width(ru,current); wl=_required_total_width(rl,current)
          if not (_legal_total_width(wu,policy) and _legal_total_width(wl,policy)): continue
          nfu=_minimum_nf(wu,policy); nfl=_minimum_nf(wl,policy)
          if nfu is None or nfl is None: continue
          c={str(var["upper_gate_node"]):vdd-ru.vgs_v,str(var["lower_gate_node"]):vss+rl.vgs_v,str(var["upper_current"]):current,str(var["lower_current"]):current,str(var["upper_width"]):wu,str(var["lower_width"]):wl,
             f"nf_{upper.lower()}":nfu,f"nf_{lower.lower()}":nfl,f"w_finger_{upper.lower()}_um":wu/nfu,f"w_finger_{lower.lower()}_um":wl/nfl,
             f"{upper.lower()}_technology_row_index":ru.index,f"{lower.lower()}_technology_row_index":rl.index,
             f"{upper.lower()}_vgs_v":ru.vgs_v,f"{upper.lower()}_vds_v":ru.vds_v,f"{lower.lower()}_vgs_v":rl.vgs_v,f"{lower.lower()}_vds_v":rl.vds_v,
             f"{upper.lower()}_vdsat_v":ru.vdsat_v,f"{lower.lower()}_vdsat_v":rl.vdsat_v}
          if exact_mode: c[exact_name]=lo
          else: c[str(var["output_min"])]=lo; c[str(var["output_max"])]=hi
          correlated.append(c)
          if len(correlated)>=max_records: break
        if len(correlated)>=max_records: break
      if len(correlated)>=max_records: break
    if not correlated: raise DependentRegionError("no correlated output-device tuples")
    dependent={str(var["upper_current"]):_values_interval((x[str(var["upper_current"])] for x in correlated),"upper current"),str(var["lower_current"]):_values_interval((x[str(var["lower_current"])] for x in correlated),"lower current"),str(var["upper_width"]):_values_interval((x[str(var["upper_width"])] for x in correlated),"upper width"),str(var["lower_width"]):_values_interval((x[str(var["lower_width"])] for x in correlated),"lower width")}
    if not exact_mode: dependent[exact_name]={"minimum":min(x[str(var["output_min"])] for x in correlated),"maximum":max(x[str(var["output_max"])] for x in correlated),"kind":"dependent_ranged_variable","selection_policy":str(ranged.get("selection_policy","preserve_feasible_interval"))}
    return {"group_id":str(group["id"]),"solver_type":"correlated_output_pair","status":"PASS","dependent_regions":dependent,"technology_support":{upper:len(upper_rows),lower:len(lower_rows)},"correlated_candidate_count":len(correlated),"correlated_candidate_mode":"exact_node_value" if exact_mode else "derived_node_range","correlated_candidates":correlated,"deferred_to_step_5":list(config.get("deferred_to_step_5",[]))}


PRIMITIVES = {
    "matched_input_network": solve_matched_input_network,
    "correlated_output_pair": solve_correlated_output_pair,
}
