# Gate 4A Constraint Classification Report

## Summary

- **Status:** PASS
- **Classified items:** 55
- **Linear compiler constraints:** 10
- **Topology heuristics excluded from compiler:** input_pair_width_match, upper_current_source_width_match, folded_pmos_width_match, lower_nmos_width_match

## Classification

| ID | Category | Owner | Compiler expression |
|---|---|---|---|
| `balanced_input_left` | `linear_compiler_constraint` | `synthesis.constraint_compiler` | `device.M1.current == 0.5 * device.M3.current` |
| `balanced_input_right` | `linear_compiler_constraint` | `synthesis.constraint_compiler` | `device.M2.current == 0.5 * device.M3.current` |
| `upper_source_left` | `linear_compiler_constraint` | `synthesis.constraint_compiler` | `device.M4.current == 1.5 * device.M3.current` |
| `upper_source_right` | `linear_compiler_constraint` | `synthesis.constraint_compiler` | `device.M5.current == 1.5 * device.M3.current` |
| `folded_branch_left` | `linear_compiler_constraint` | `synthesis.constraint_compiler` | `device.M6.current == device.M4.current - device.M1.current` |
| `folded_branch_right` | `linear_compiler_constraint` | `synthesis.constraint_compiler` | `device.M7.current == device.M5.current - device.M2.current` |
| `lower_cascode_left` | `linear_compiler_constraint` | `synthesis.constraint_compiler` | `device.M8.current == device.M6.current` |
| `lower_cascode_right` | `linear_compiler_constraint` | `synthesis.constraint_compiler` | `device.M9.current == device.M7.current` |
| `lower_sink_left` | `linear_compiler_constraint` | `synthesis.constraint_compiler` | `device.M10.current == device.M8.current` |
| `lower_sink_right` | `linear_compiler_constraint` | `synthesis.constraint_compiler` | `device.M11.current == device.M9.current` |
| `input_pair_width_match` | `topology_heuristic` | `topology_specific_synthesis_adapter` | `—` |
| `upper_current_source_width_match` | `topology_heuristic` | `topology_specific_synthesis_adapter` | `—` |
| `folded_pmos_width_match` | `topology_heuristic` | `topology_specific_synthesis_adapter` | `—` |
| `lower_nmos_width_match` | `topology_heuristic` | `topology_specific_synthesis_adapter` | `—` |
| `w_m1_um` | `synthesis_parameter` | `synthesis_parameterization` | `—` |
| `vnb1_v` | `synthesis_parameter` | `synthesis_parameterization` | `—` |
| `i_m3_a` | `synthesis_parameter` | `synthesis_parameterization` | `—` |
| `i_m1_a` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `i_m2_a` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `i_m4_a` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `i_m5_a` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `i_m6_a` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `i_m7_a` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `i_m8_a` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `i_m9_a` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `i_m10_a` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `i_m11_a` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `w_m2_um` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `w_m3_um` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `w_m4_um` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `w_m5_um` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `w_m6_um` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `w_m7_um` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `w_m8_um` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `w_m9_um` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `w_m10_um` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `w_m11_um` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `vtail_v` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `psrc_left_v` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `psrc_right_v` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `x_v` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `nsink_left_v` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `nsink_right_v` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `vout_v` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `vpb1_v` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `vpb2_v` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `vnb2_v` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `input_tail_network` | `dependency_group` | `hierarchical_synthesis_workflow` | `—` |
| `upper_folded_network` | `dependency_group` | `hierarchical_synthesis_workflow` | `—` |
| `lower_output_network` | `dependency_group` | `hierarchical_synthesis_workflow` | `—` |
| `operating_conditions` | `operating_or_assignment_policy` | `orchestration` | `—` |
| `device_constraints` | `technology_region_constraint` | `technology` | `—` |
| `technology_intersection` | `technology_region_constraint` | `technology` | `—` |
| `assignment_rules` | `operating_or_assignment_policy` | `orchestration` | `—` |
| `simulation_constraints` | `simulation_constraint` | `simulation` | `—` |

## Compiler Scope

The generic compiler receives only linear equalities, scaled equalities, and linear sums. Independent-variable declarations, dependency groups, technology filtering, simulation rules, and nonlinear topology-specific relations remain owned by their corresponding subsystems.

## Gate 4A Conclusion

The two-stage design intent has been decomposed into explicit subsystem responsibilities. Gate 4B may now compile only the generated `compiler_constraints.json` records against canonical region bindings.
