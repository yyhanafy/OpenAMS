#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
import yaml

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--intent",type=Path,required=True)
    a=ap.parse_args()
    d=yaml.safe_load(a.intent.read_text())
    d["hierarchical_feasibility"]={
      "schema_version":2,
      "strategy":"hierarchical_component_mlp_discrete_exact_join",
      "independent_point_source":{
        "kind":"independent_regions_json",
        "path":"examples/folded_cascode/generated/assignment_synthesis/independent_regions.json",
        "variables":{
          "w_m1_um":{"domain":"w_m1_um","sampling":"linear_from_domain","count":25},
          "i_m3_a":{"domain":"i_m3_a","sampling":"candidate_values"}
        }},
      "components":[
        {"id":"input_tail_network","source_group":"input_tail_network",
         "checkpoint":"technology/component_models/folded_input_tail_network.pt",
         "model_kind":"binary_feasibility_classifier",
         "mlp_features":["w_m1_um","i_m3_a","vp_v"],
         "interface_inputs":[],"interface_outputs":["upper_folded_cut"],
         "exact_realizer":{"driver":"witness_plan_builder",
           "module":"tools/validation/folded_component_realizer_adapter.py",
           "builder_function":"build_A",
           "base_plan":"examples/folded_cascode/inputs/folded_cascode_mlp_witness_plan.yaml",
           "witnesses_per_state":5}},
        {"id":"upper_folded_network","source_group":"upper_folded_network",
         "checkpoint":"technology/component_models/folded_upper_folded_network.pt",
         "model_kind":"binary_feasibility_classifier",
         "mlp_features":["i_m3_a","vp_v","vx_v"],
         "interface_inputs":["upper_folded_cut"],"interface_outputs":["folded_lower_cut"],
         "exact_realizer":{"driver":"witness_plan_builder",
           "module":"tools/validation/folded_component_realizer_adapter.py",
           "builder_function":"build_B",
           "base_plan":"examples/folded_cascode/inputs/folded_cascode_mlp_witness_plan.yaml",
           "witnesses_per_state":5}},
        {"id":"lower_output_network","source_group":"lower_output_network",
         "checkpoint":"technology/component_models/folded_lower_output_network.pt",
         "model_kind":"binary_feasibility_classifier",
         "mlp_features":["i_m3_a","vx_v"],
         "interface_inputs":["folded_lower_cut"],"interface_outputs":[],
         "exact_realizer":{"driver":"witness_plan_builder",
           "module":"tools/validation/folded_component_realizer_adapter.py",
           "builder_function":"build_C",
           "base_plan":"examples/folded_cascode/inputs/folded_cascode_mlp_witness_plan.yaml",
           "witnesses_per_state":5}}
      ],
      "interfaces":[
        {"id":"upper_folded_cut","between":["input_tail_network","upper_folded_network"],
         "coordinates":[{"name":"vp_v","kind":"voltage","physical_nodes":["psrc_left","psrc_right"],
          "relation":"shared_equal_coordinate",
          "grid":{"minimum":0.001,"maximum":1.799,"count":31,"spacing":"linear"}}],
         "propagated_variables":[]},
        {"id":"folded_lower_cut","between":["upper_folded_network","lower_output_network"],
         "coordinates":[{"name":"vx_v","kind":"voltage","physical_nodes":["x","vout"],
          "relation":"shared_equal_coordinate",
          "grid":{"minimum":0.05,"maximum":1.75,"count":21,"spacing":"linear"}}],
         "propagated_variables":[]}
      ],
      "final_witness":{
        "semantics":"complete_spice_realizable_assignment",
        "deduplicate_on":["w_m1_um","w_m3_um","w_m4_um","w_m6_um","w_m8_um",
                          "vnb1_v","vpb1_v","vpb2_v","vnb2_v","vp_v","vx_v"],
        "canonical_fields":{
          "w_m1_um":"A_w_m1_um","w_m2_um":"A_w_m1_um","w_m3_um":"A_w_m3_um",
          "w_m4_um":"B_w_m4_um","w_m5_um":"B_w_m4_um","w_m6_um":"B_w_m6_um",
          "w_m7_um":"B_w_m6_um","w_m8_um":"C_w_m8_um","w_m9_um":"C_w_m8_um",
          "w_m10_um":"C_w_m8_um","w_m11_um":"C_w_m8_um",
          "i_m1_a":"0.5*A_i_m3_a","i_m2_a":"0.5*A_i_m3_a","i_m3_a":"A_i_m3_a",
          "i_m4_a":"1.5*A_i_m3_a","i_m5_a":"1.5*A_i_m3_a",
          "i_m6_a":"A_i_m3_a","i_m7_a":"A_i_m3_a","i_m8_a":"A_i_m3_a",
          "i_m9_a":"A_i_m3_a","i_m10_a":"A_i_m3_a","i_m11_a":"A_i_m3_a",
          "tail_v":"A_tail_v","vnb1_v":"A_vnb1_v",
          "psrc_left_v":"A_vp_v","psrc_right_v":"A_vp_v","vp_v":"A_vp_v",
          "vpb1_v":"B_vpb1_v","vpb2_v":"B_vpb2_v",
          "x_v":"B_vx_v","vout_v":"B_vx_v","vx_v":"B_vx_v",
          "nsink_left_v":"C_nsink_left_v","nsink_right_v":"C_nsink_right_v",
          "vnb2_v":"C_vnb2_v",
          "sat_M1_headroom_v":"A_sat_M1_headroom_v","sat_M2_headroom_v":"A_sat_M2_headroom_v",
          "sat_M3_headroom_v":"A_sat_M3_headroom_v","sat_M4_headroom_v":"B_sat_M4_headroom_v",
          "sat_M5_headroom_v":"B_sat_M5_headroom_v","sat_M6_headroom_v":"B_sat_M6_headroom_v",
          "sat_M7_headroom_v":"B_sat_M7_headroom_v","sat_M8_headroom_v":"C_sat_M8_headroom_v",
          "sat_M9_headroom_v":"C_sat_M9_headroom_v","sat_M10_headroom_v":"C_sat_M10_headroom_v",
          "sat_M11_headroom_v":"C_sat_M11_headroom_v"
        }}
    }
    a.intent.write_text(yaml.safe_dump(d,sort_keys=False))
    print("updated:",a.intent)

if __name__=="__main__": main()
