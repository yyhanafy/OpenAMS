# OpenAMS Topology Model

## Status

This document defines the first production topology-extraction boundary.

## Responsibility

`openams.topology` converts flat SPICE syntax into immutable OpenAMS circuit
connectivity.

It answers only:

- which devices exist;
- which nodes exist;
- which canonical terminal connects to each node;
- which model name and literal instance parameters were written.

It does not infer:

- differential pairs;
- current mirrors;
- circuit stages;
- current branches;
- KCL equations;
- independent variables;
- operating regions;
- technology behavior.

Those meanings belong to later layers.

## Initial supported elements

| SPICE prefix | OpenAMS kind | Canonical terminals |
|---|---|---|
| `M` | `mos` | drain, gate, source, bulk |
| `R` | `resistor` | positive, negative |
| `C` | `capacitor` | positive, negative |
| `V` | `voltage_source` | positive, negative |
| `I` | `current_source` | positive, negative |
| `X` | `mos` only when four-node MOS-like instance | drain, gate, source, bulk |

The initial implementation is intentionally flat. `.subckt` definitions and
hierarchical expansion are rejected rather than guessed.

## SPICE normalization

Parsing performs only syntax normalization:

- logical lines join leading `+` continuations;
- blank lines and full-line comments are ignored;
- inline `$` comments are removed outside quotes;
- element names are preserved;
- node names are preserved;
- parameter keys are normalized to lowercase;
- engineering-suffix numbers are converted to SI floats;
- nonnumeric parameter expressions remain strings;
- raw independent-source tails are preserved as a `value` parameter.

The ground node is stored using the SPICE name `0`.

## MOS subcircuit instances

SKY130 primitive devices are commonly written as `X` instances. The initial
parser accepts an `X` line as a MOS device only when:

1. exactly four node tokens precede the model token; and
2. the model token contains one of: `nfet`, `pfet`, `nmos`, `pmos`, `mos`.

Arbitrary subcircuit instances are rejected. Their terminal semantics cannot be
known without parsing the corresponding `.subckt` declaration.

## Public API

```python
from openams.topology import (
    parse_spice_circuit,
    parse_spice_file,
    connected_devices,
    connected_terminals,
    device,
    node,
)
```

`parse_spice_circuit` accepts text and returns the canonical immutable
`openams.model.Circuit`.

`parse_spice_file` is deliberately not provided. Filesystem reading belongs to
`openams.io`; callers read text there and pass the text to topology.

## Error policy

Topology raises a specific exception for:

- unsupported directives that change hierarchy;
- malformed element lines;
- duplicate device names;
- invalid terminal counts;
- unsupported elements;
- arbitrary subcircuit instances.

Unknown simulation-control directives beginning with `.` are ignored only when
they do not alter topology.

## Acceptance criteria

This slice is accepted when it can represent flat two-stage op-amp and
folded-cascode device connectivity without adding topology-specific concepts.
