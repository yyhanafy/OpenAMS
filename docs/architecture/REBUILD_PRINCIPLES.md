# OpenAMS Rebuild Principles

## Objective

Build a simple, topology-generic OpenAMS implementation without compromising
the useful functionality demonstrated by the archived MVP.

The archived repository is a reference implementation and source of proven
functions, tests, algorithms, and examples. It is not the architecture of the
new implementation.

Archive location:

    ../MVP_archive_July_30

## Governing principles

1. Prefer the simplest design that preserves required functionality.
2. Maintain one canonical execution path.
3. Keep topology-specific knowledge out of the Python synthesis core.
4. Derive circuit structure from the netlist, topology graph, and metadata.
5. Separate circuit reasoning from transistor-model implementation.
6. Access transistor behavior through one technology query interface.
7. Generate fully resolved assignments before simulation whenever possible.
8. Send only unresolved assignments to optimization.
9. Reuse old code selectively, one function or object at a time.
10. Do not preserve interfaces solely for backward compatibility.
11. Validate genericity using at least two materially different topologies.
12. Do not remove archived functionality until its useful behavior is
    represented by the new implementation or deliberately rejected.

## Canonical pipeline

    Netlist
      + specifications
      + design intent
      + design rules
      + simulation configuration
      + active technology model
                |
                v
        Metadata validation
                |
                v
        Topology extraction
                |
                v
        Generic constraint compilation
                |
                v
        DC assignment synthesis
                |
          +-----+------+
          |            |
          v            v
    fully resolved   unresolved ranges
          |            |
          v            v
    direct simulation optimization
          |            |
          +-----+------+
                |
                v
        DC/AC/transient verification
                |
                v
        Specification screening

## Core boundaries

- Topology answers: What is connected to what?
- Design intent answers: What circuit relationships are intended?
- Design rules answer: What values and relationships are allowed?
- Constraints answer: What equations and inequalities must hold?
- Synthesis answers: Which DC assignments satisfy those constraints?
- Technology answers: How does a device behave in this process?
- Simulation answers: Does the candidate work in the reference simulator?
- Optimization answers: Which unresolved candidate best meets the objectives?

## Prohibited core assumptions

Production synthesis code must not depend on:

- specific transistor names such as M1 through M7;
- left-stage, right-stage, or second-stage hard coding;
- a particular op-amp family;
- direct CSV table access;
- fixed branch structures;
- topology-specific output columns;
- mandatory executable-contract generation.

## Initial scope

The first implementation will generate physically consistent DC candidate
assignments from topology, intent, rules, operating conditions, and a technology
model.

The initial implementation will deliberately postpone advanced optimization,
automatic analog-function recognition, AC surrogate modeling, post-layout
optimization, and mixed-signal behavioral modeling until the DC synthesis
foundation is correct.
