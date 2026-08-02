# Deterministic dependency constructor

The independent space is `(I5, W1, Vout)`. Remaining degrees of freedom that are not uniquely fixed by circuit equations are explicit design-intent policy values, not hidden scans. The pilot records `N1=0.60 V` and `Vbias=0.60 V` in every assignment.

The constructor uses only scalar local solves for `VGS1`, `W3`, `N2`, `W5`, `Iout`, `W6`, and `W7`.
