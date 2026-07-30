# OpenAMS Constraint Model

## Status

This document defines the production boundary for explicit design constraints.

## Responsibility

`openams.constraints` represents relationships that must hold among named
circuit quantities.

It owns:

- scalar bounds;
- equality and inequality relations;
- ratios;
- algebraic expressions;
- named constraint sets;
- structural validation;
- dependency inspection.

It does not own:

- numerical solving;
- technology lookup;
- topology inference;
- simulation;
- candidate generation;
- optimization;
- specification scoring.

## Design principle

A constraint states **what must hold**, not **how to make it hold**.

For example:

```text
W_M1 = W_M2
I_M6 = I_M7
W_M6 / W_M4 = 2 * W_M7 / W_M5
0.5 <= VOUT <= 2.0
```

These relationships are immutable declarations. Later layers decide whether to
substitute, enumerate, solve, optimize, or verify them.

## Canonical expression tree

Expressions use a small immutable tree:

- `Symbol(name)`
- `Constant(value)`
- `UnaryExpression(operator, operand)`
- `BinaryExpression(operator, left, right)`

Supported operators:

- unary: `+`, `-`
- binary: `+`, `-`, `*`, `/`, `**`

The expression tree deliberately excludes function calls, assignment, indexing,
attribute access, and arbitrary Python evaluation.

## Constraint types

- `RelationConstraint`: `lhs <op> rhs`
- `BoundConstraint`: optional lower and upper bound on one symbol
- `RatioConstraint`: `numerator = ratio * denominator`
- `ConstraintSet`: named immutable collection

Supported relation operators:

```text
==
!=
<
<=
>
>=
```

## Identity and provenance

Every constraint has:

- a non-empty identifier;
- an optional human-readable description;
- immutable provenance metadata.

Constraint identifiers are unique within a `ConstraintSet`.

## Validation

Construction rejects:

- empty identifiers or symbol names;
- unsupported operators;
- non-finite constants;
- division by literal zero;
- contradictory literal bounds;
- duplicate constraint identifiers;
- empty constraint sets when explicitly disallowed.

Validation is structural. It does not attempt symbolic satisfiability.

## Dependency inspection

The package can return the symbols referenced by:

- one expression;
- one constraint;
- an entire constraint set.

This information is intended for the later planning layer.

## Parsing policy

This slice does not parse free-form equations or execute Python expressions.
Metadata normalization should construct these objects explicitly.

A restricted equation parser may be added later only if its grammar is defined
independently of Python syntax.

## Dependency boundary

`openams.constraints` may depend on:

- `openams.model`
- `openams.metadata`
- `openams.topology`

The initial implementation is self-contained and imports none of them. It
communicates through stable names rather than owning circuit objects.
