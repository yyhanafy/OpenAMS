#!/usr/bin/env python3
from pathlib import Path
import argparse,yaml
p=argparse.ArgumentParser();p.add_argument('--intent',required=True,type=Path);a=p.parse_args();d=yaml.safe_load(a.intent.read_text());hf=d['hierarchical_feasibility'];cm={c['id']:c for c in hf['components']};ain=cm['input_bias_network'];b=cm['output_stage']
for itf in hf['interfaces']:
    for pv in itf.get('propagated_variables',[]):
        if pv['name']=='stage_ratio' and pv.get('destination_component')=='output_stage':pv['training_domain']={'minimum':0.04,'maximum':200.0,'count':21,'spacing':'log'}
ain['training']={'feature_domains':{'w_m1_um':{'count':7,'spacing':'log'},'i_m5_a':{'count':7,'spacing':'log'}}}
b['training']={'coverage_bindings':{'a_point_index':'point_index','a_witness_rank':0,'i_m5_a':1.0009030134e-05,'w_m3_um':'0.5 * stage_ratio','w_m5_um':1.0}}
a.intent.write_text(yaml.safe_dump(d,sort_keys=False));print('updated:',a.intent)
