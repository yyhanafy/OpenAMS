from pathlib import Path


def test_unified_driver_contains_both_dispatch_paths():
    text = Path("tools/validation/run_coarse_independent_ac_scan.py").read_text()
    assert '"--compiled-model"' in text
    assert "run_generic_compiled_scan" in text
    assert "run_coarse_independent_ac_scan_two_stage_legacy" in text
