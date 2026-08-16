# Gate 4A Constraint Classification Report

## Summary

- **Status:** PASS
- **Classified items:** 32
- **Linear compiler constraints:** 5
- **Topology heuristics excluded from compiler:** second_stage_size_relation

## Classification

| ID | Category | Owner | Compiler expression |
|---|---|---|---|
| `balanced_input_left` | `linear_compiler_constraint` | `synthesis.constraint_compiler` | `device.M1.current == device.M5.current / 2.0` |
| `balanced_input_right` | `linear_compiler_constraint` | `synthesis.constraint_compiler` | `device.M2.current == device.M5.current / 2.0` |
| `active_load_left` | `linear_compiler_constraint` | `synthesis.constraint_compiler` | `device.M3.current == device.M1.current` |
| `active_load_right` | `linear_compiler_constraint` | `synthesis.constraint_compiler` | `device.M4.current == device.M2.current` |
| `output_node_kcl` | `linear_compiler_constraint` | `synthesis.constraint_compiler` | `device.M6.current == device.M7.current` |
| `second_stage_size_relation` | `topology_heuristic` | `topology_specific_synthesis_adapter` | `—` |
| `i_m5_a` | `synthesis_parameter` | `synthesis_parameterization` | `—` |
| `w_m1_um` | `synthesis_parameter` | `synthesis_parameterization` | `—` |
| `i_m1_a` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `i_m2_a` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `i_m3_a` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `i_m4_a` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `i_m6_a` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `i_m7_a` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `w_m2_um` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `w_m3_um` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `w_m4_um` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `w_m5_um` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `w_m6_um` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `w_m7_um` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `vtail_v` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `n1_v` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `n2_v` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `vbias_v` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `vout_v` | `dependent_quantity_declaration` | `synthesis_adapter_or_emitter` | `—` |
| `input_bias_network` | `dependency_group` | `hierarchical_synthesis_workflow` | `—` |
| `output_stage` | `dependency_group` | `hierarchical_synthesis_workflow` | `—` |
| `operating_conditions` | `operating_or_assignment_policy` | `orchestration` | `—` |
| `device_constraints` | `technology_region_constraint` | `technology` | `—` |
| `technology_intersection` | `technology_region_constraint` | `technology` | `—` |
| `assignment_rules` | `operating_or_assignment_policy` | `orchestration` | `—` |
| `simulation_constraints` | `simulation_constraint` | `simulation` | `—` |

## Compiler Scope

The generic compiler receives only linear equalities, scaled equalities, and linear sums. Independent-variable declarations, dependency groups, technology filtering, simulation rules, and nonlinear topology-specific relations remain owned by their corresponding subsystems.

## Gate 4A Conclusion

The two-stage design intent has been decomposed into explicit subsystem responsibilities. Gate 4B may now compile only the generated `compiler_constraints.json` records against canonical region bindings.
