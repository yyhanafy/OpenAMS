#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json,math
from pathlib import Path
from typing import Any,Mapping,MutableMapping

def parse_args():
 p=argparse.ArgumentParser();p.add_argument('--compiled-model',type=Path,required=True);p.add_argument('--assignments-json',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--repair-output-json',type=Path);p.add_argument('--voltage-tolerance-v',type=float,default=0.025);return p.parse_args()
def pol(m):
 t=m.lower();
 if 'pfet' in t or 'pmos' in t:return 'pmos'
 if 'nfet' in t or 'nmos' in t:return 'nmos'
 raise ValueError(m)
def dmap(model):
 out={}
 for x in model['topology']['devices']:
  if str(x.get('kind','')).lower()!='mos':continue
  n=str(x['name']);n=n[1:] if n.upper().startswith('X') else n;out[n.upper()]=x
 return out
def pnum(point,*names):
 for n in names:
  v=point.get(n)
  if v not in (None,''):
   try:f=float(v)
   except:continue
   if math.isfinite(f):return f
 return None
def setnode(nodes,node,val,tol,conflicts,why):
 k=str(node).strip().lower()
 if not k:return False
 val=float(val)
 if k in nodes:
  if abs(nodes[k]-val)>tol:conflicts.append(f'{k}: existing={nodes[k]:.12g}, derived={val:.12g}, reason={why}')
  return False
 nodes[k]=val;return True
def initial_nodes(model,a):
 nodes={};op=model.get('project_inputs',{}).get('design_rules',{}).get('operating_conditions',{})
 aliases={'vdd':('vdd_v','vdd'),'vss':('vss_v','vss'),'inp':('vin_cm_v','input_common_mode_v'),'inn':('vin_cm_v','input_common_mode_v'),'vip':('vin_cm_v','input_common_mode_v'),'vin':('vin_cm_v','input_common_mode_v')}
 for node,keys in aliases.items():
  for k in keys:
   if isinstance(op.get(k),(int,float)):nodes[node]=float(op[k]);break
 for k,v in a.items():
  if isinstance(v,(int,float)) and k.endswith('_v'):
   t=k[:-2].lower();nodes[t]=float(v)
   if t.startswith('v') and len(t)>1:nodes.setdefault(t[1:],float(v))
 return nodes
def reconstruct(model,a,tol):
 devices=dmap(model);prov=a.get('device_technology_provenance',{});nodes=initial_nodes(model,a);conflicts=[];deriv=[]
 for _ in range(max(4,len(devices)*3)):
  progress=False
  for name,dev in devices.items():
   point=prov.get(name,{})
   if not isinstance(point,Mapping):continue
   t={k:str(v).strip().lower() for k,v in dev.get('terminals',{}).items()};p=pol(str(dev['model']))
   if not {'gate','source','drain'}.issubset(t):continue
   gate,source=t['gate'],t['source'];bulk=t.get('bulk') or ('vss' if p=='nmos' else 'vdd')
   vgs=pnum(point,'vgs_v');vbs=pnum(point,'vbs_v');vg=nodes.get(gate);vs=nodes.get(source);vb=nodes.get(bulk)
   if vbs is not None and vb is not None and vs is None:
    dvs=vb+vbs if p=='nmos' else vb-vbs
    if setnode(nodes,source,dvs,tol,conflicts,f'{name} source from bulk/VBS'):deriv.append(f'{source}={dvs:.12g} from {name} bulk/VBS');progress=True
   vg,vs=nodes.get(gate),nodes.get(source)
   if vgs is not None:
    if vg is not None and vs is None:
     dvs=vg-vgs if p=='nmos' else vg+vgs
     if setnode(nodes,source,dvs,tol,conflicts,f'{name} source from gate/VGS'):deriv.append(f'{source}={dvs:.12g} from {name} gate/VGS');progress=True
    elif vs is not None and vg is None:
     dvg=vs+vgs if p=='nmos' else vs-vgs
     if setnode(nodes,gate,dvg,tol,conflicts,f'{name} gate from source/VGS'):deriv.append(f'{gate}={dvg:.12g} from {name} source/VGS');progress=True
  if not progress:break
 return nodes,conflicts,deriv
def audit_rows(model,a,nodes,tol):
 rows=[];devices=dmap(model);prov=a.get('device_technology_provenance',{})
 for name,dev in sorted(devices.items()):
  point=prov.get(name,{});t={k:str(v).strip().lower() for k,v in dev.get('terminals',{}).items()};p=pol(str(dev['model']))
  d,g,s=t.get('drain',''),t.get('gate',''),t.get('source','');b=t.get('bulk') or ('vss' if p=='nmos' else 'vdd')
  vd,vg,vs,vb=nodes.get(d),nodes.get(g),nodes.get(s),nodes.get(b)
  avgs=None if vg is None or vs is None else (vg-vs if p=='nmos' else vs-vg)
  avds=None if vd is None or vs is None else (vd-vs if p=='nmos' else vs-vd)
  avbs=None if vb is None or vs is None else abs(vb-vs)
  evgs=pnum(point,'vgs_v');evbs=pnum(point,'vbs_v');minv=pnum(point,'minimum_saturated_vds_v','vds_v');maxv=pnum(point,'maximum_characterized_vds_v');vdsat=pnum(point,'maximum_vdsat_v','vdsat_v')
  fails=[];checks=[];expbulk='vss' if p=='nmos' else 'vdd'
  (checks if b==expbulk else fails).append('bulk_connection' if b==expbulk else f'bulk_node={b},expected={expbulk}')
  if avgs is None:fails.append('VGS_UNRESOLVED')
  elif evgs is not None and abs(avgs-evgs)>tol:fails.append(f'VGS_MISMATCH actual={avgs:.12g} expected={evgs:.12g}')
  else:checks.append('vgs')
  if avbs is None:fails.append('VBS_UNRESOLVED')
  elif evbs is not None and abs(avbs-evbs)>tol:fails.append(f'VBS_MISMATCH actual={avbs:.12g} expected={evbs:.12g}')
  else:checks.append('vbs')
  if avds is None:
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
  rows.append({'assignment_id':a.get('assignment_id'),'device':name,'polarity':p,'model':dev.get('model'),'drain_node':d,'gate_node':g,'source_node':s,'bulk_node':b,'vd_v':vd,'vg_v':vg,'vs_v':vs,'vb_v':vb,'actual_vgs_v':avgs,'expected_vgs_v':evgs,'actual_vds_v':avds,'minimum_saturated_vds_v':minv,'maximum_characterized_vds_v':maxv,'actual_vbs_v':avbs,'expected_vbs_v':evbs,'vdsat_v':vdsat,'status':'PASS' if not fails else 'INCOMPLETE_OR_FAIL','passed_checks':';'.join(checks),'failures':';'.join(fails)})
 return rows
def main():
 args=parse_args();model=json.loads(args.compiled_model.read_text());art=json.loads(args.assignments_json.read_text());assignments=art.get('assignments',[]);args.output_dir.mkdir(parents=True,exist_ok=True);allrows=[];sums=[];repaired=json.loads(json.dumps(art))
 for i,a in enumerate(assignments):
  nodes,conf,deriv=reconstruct(model,a,args.voltage_tolerance_v);rows=audit_rows(model,a,nodes,args.voltage_tolerance_v);allrows+=rows;bad=[r for r in rows if r['status']!='PASS'];status='PASS' if not bad and not conf else 'INCOMPLETE_OR_FAIL';sums.append({'assignment_id':a.get('assignment_id'),'resolved_node_count':len(nodes),'device_count':len(rows),'device_pass_count':len(rows)-len(bad),'device_incomplete_or_fail_count':len(bad),'node_conflict_count':len(conf),'status':status,'nodes':dict(sorted(nodes.items())),'node_conflicts':conf,'derivations':deriv})
  e=repaired['assignments'][i];e['dc_audit_status']=status;e['resolved_nodes_v']=dict(sorted(nodes.items()));e['dc_audit_node_conflicts']=conf;e['dc_audit_derivations']=deriv
  for n,v in nodes.items():e.setdefault(f'{n}_v',v)
  for r in rows:
   tok=r['device'].lower()
   for sk,suf in [('vd_v','vd_v'),('vg_v','vg_v'),('vs_v','vs_v'),('vb_v','vb_v'),('actual_vgs_v','vgs_v'),('actual_vds_v','vds_v'),('actual_vbs_v','vbs_v')]:
    if r[sk] is not None:e[f'{suf}_{tok}']=r[sk]
 payload={'artifact':'openams.generic_dc_assignment_audit','schema_version':1,'compiled_model':str(args.compiled_model.resolve()),'assignments_json':str(args.assignments_json.resolve()),'assignment_count':len(assignments),'assignment_pass_count':sum(x['status']=='PASS' for x in sums),'assignment_incomplete_or_fail_count':sum(x['status']!='PASS' for x in sums),'assignments':sums}
 (args.output_dir/'dc_assignment_audit.json').write_text(json.dumps(payload,indent=2)+'\n')
 if allrows:
  with (args.output_dir/'device_audit.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(allrows[0]));w.writeheader();w.writerows(allrows)
 with (args.output_dir/'node_audit.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=['assignment_id','node','voltage_v']);w.writeheader()
  for s in sums:
   for n,v in s['nodes'].items():w.writerow({'assignment_id':s['assignment_id'],'node':n,'voltage_v':v})
 (args.output_dir/'DC_ASSIGNMENT_AUDIT.md').write_text('# Generic DC Assignment Audit\n\n'+f"- Assignments: {len(assignments)}\n- Fully resolved and passing: {payload['assignment_pass_count']}\n- Incomplete or failing: {payload['assignment_incomplete_or_fail_count']}\n")
 if args.repair_output_json:args.repair_output_json.parent.mkdir(parents=True,exist_ok=True);args.repair_output_json.write_text(json.dumps(repaired,indent=2)+'\n')
 print('===== OPENAMS GENERIC DC ASSIGNMENT AUDIT =====');print('assignments:',len(assignments));print('fully resolved and passing:',payload['assignment_pass_count']);print('incomplete or failing:',payload['assignment_incomplete_or_fail_count']);print('audit JSON:',args.output_dir/'dc_assignment_audit.json');print('device CSV:',args.output_dir/'device_audit.csv');print('node CSV:',args.output_dir/'node_audit.csv');
 if args.repair_output_json:print('enriched assignments:',args.repair_output_json)
 return 0
if __name__=='__main__':raise SystemExit(main())
