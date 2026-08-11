# SKY130 ICCAD-2023 LDO1 benchmark reference

This folder points to the published LDO1 benchmark from Chris Zonghao Li et al., ICCAD 2023.

## Why this LDO

LDO1 is the paper's simple "vanilla" topology: a five-transistor differential-pair error amplifier, PMOS pass transistor, feedback resistor/capacitor, load-current source, and decoupling capacitor. The complete transistor-level ngspice netlist and analysis scripts are published by the authors.

## Original source files

After cloning `ChrisZonghaoLi/sky130_ldo_rl`, use:

- `python/simulations/ldo_tb.spice` - complete LDO1 transistor-level ngspice deck.
- `python/simulations/ldo_tb_analysis.spice` - loop gain, DC, load regulation, PSRR and OP analyses.
- `python/simulations/ldo_tb_vars.spice` - one checked-in sizing/operating point.
- `python/ldo.py` - simulation environment and metric extraction.
- `python/ckt_graphs.py` - LDO1 graph and specification definitions.

## Run

From this folder:

```bash
./run_original_benchmark.sh
```

The wrapper clones the original repository if needed and changes only the authors' machine-specific absolute include paths to relative paths. It does not alter the LDO circuit.

## Published benchmark

See `benchmark_spec.yaml` for the target specifications and the paper's published optimized LDO1 component values and measured results.

Important: the paper explicitly reports that optimized LDO1 does **not** meet every target. That makes the published numbers useful as reproduction/reference data; the target table should not be misrepresented as a fully passing design.

## Schematic

`LDO1_schematic_from_ICCAD2023.png` is a crop of Fig. 2(a) from the authors' published ICCAD 2023 paper, included here only as the requested circuit reference.
