#!/usr/bin/env python3
from __future__ import annotations
import importlib.util
from pathlib import Path

_SRC = Path(__file__).with_name("run_folded_balanced_current_derived.py")
_spec = importlib.util.spec_from_file_location("_folded_teacher_impl", _SRC)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)

DEFAULT_PLAN = _mod.DEFAULT_PLAN
read_yaml = _mod.load_yaml
write_yaml = _mod.save_yaml
build_A = _mod.build_A
build_B = _mod.build_B
build_C = _mod.build_C
