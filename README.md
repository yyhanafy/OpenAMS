# OpenAMS

OpenAMS is a topology-aware and technology-aware framework for analog and
mixed-signal design synthesis, simulation, and optimization.

This repository is a clean architectural rebuild. The previous MVP is retained
separately as a frozen reference implementation.

The first development objective is a generic DC assignment synthesis pipeline:

1. validate canonical metadata;
2. extract a circuit graph from SPICE;
3. compile topology and design intent into generic constraints;
4. synthesize physically consistent device and node assignments;
5. query transistor behavior through a backend-independent technology API;
6. verify complete assignments using ngspice;
7. invoke optimization only for assignments containing unresolved ranges.

See:

    docs/architecture/REBUILD_PRINCIPLES.md
