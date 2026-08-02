# OpenAMS Continuous-Synthesis Reset

This package removes the abandoned global least-squares experiment and installs
a small dependency-ordered executor.

Removed after backup:
- the eight-variable MLP least-squares solver;
- residual diagnostic scripts;
- the obsolete continuous pilot wrapper;
- temporary diagnostic/pilot outputs.

Preserved:
- dense MLP checkpoints;
- `ml_surrogate`;
- `ml_continuous_oracle.py`;
- adaptive caching;
- generic contracts and topology solver;
- ngspice validation evidence;
- dense characterization datasets.

Apply:

```bash
cd ~/AMS-Tutorial/openams
unzip -o ~/Downloads/OpenAMS_Remove_Least_Squares_Experiment.zip
chmod +x scripts/cleanup_obsolete_mlp_least_squares.sh
bash scripts/cleanup_obsolete_mlp_least_squares.sh
source .venv-openams/bin/activate
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
pytest -q tests/synthesis/test_continuous_dependency_executor.py
```
