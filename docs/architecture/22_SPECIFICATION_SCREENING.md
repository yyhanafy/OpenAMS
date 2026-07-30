# Explicit specification screening

## Purpose

This layer evaluates explicit design specifications against backend-neutral raw
simulation measurements.

```text
RawSimulationCaseResult
        +
SpecificationRule[]
        ↓
SpecificationScreeningEngine
        ↓
CaseScreeningResult
        ├── pass
        ├── fail
        └── unknown
```

The raw simulation result remains attached to the screening record and is never
mutated or replaced.

## Rule model

A specification rule names:

- the analysis;
- the measurement;
- the comparison operator;
- a threshold or range;
- an optional tolerance;
- whether the rule is required;
- an optional unit and description.

Example:

```python
SpecificationRule(
    name="minimum_phase_margin",
    measurement="phase_margin_deg",
    analysis="ac",
    operator=ComparisonOperator.GREATER_THAN_OR_EQUAL,
    threshold=60.0,
    unit="deg",
)
```

## Supported comparisons

```text
>
>=
<
<=
==
between_inclusive
outside_inclusive
```

All comparisons may use a non-negative tolerance.

## Outcomes

Each rule produces exactly one outcome:

```text
pass
fail
unknown
```

`unknown` is used when a required measurement is missing, malformed,
unavailable, or its analysis is absent.

An optional unavailable measurement does not block the case from passing.

## Case aggregation

Case aggregation is deterministic:

1. Any explicit rule failure makes the case fail.
2. Otherwise, any required unknown result makes the case unknown.
3. Otherwise, failed simulator execution makes the case unknown.
4. Otherwise, the case passes.

Failure has priority over unknown because a known specification violation
already proves the candidate unacceptable.

## Separation of responsibilities

This layer does not:

- parse simulator artifacts;
- infer measurements;
- rerun simulations;
- modify assignments;
- rank passing designs;
- optimize design variables;
- decide which topology to use.

It only evaluates declared rules against declared raw measurements.

## Batch summary

`ScreeningSummary` reports:

- total cases;
- passed cases;
- failed cases;
- unknown cases;
- complete per-case rule outcomes.

This provides the first explicit specification-screening boundary in the clean
OpenAMS pipeline.

## Next slice

The next layer should implement a simulation orchestration workflow that joins:

```text
SimulationRunRequest
    → simulator adapter
    → raw parser
    → specification screening
```

while preserving each intermediate artifact and allowing the parser and
screening engine to remain independently testable.
