from __future__ import annotations

from openams.validation.generic_ngspice_ac import (
    extract_ac_metrics,
    interpolate,
    safe_rel_error,
)


def test_interpolate() -> None:
    assert interpolate(10.0, 20.0, 0.25) == 12.5


def test_relative_error() -> None:
    assert safe_rel_error(11.0, 10.0) == 0.1


def test_extract_ac_metrics() -> None:
    rows = [
        (1.0, 60.0, -90.0),
        (1e6, 10.0, -120.0),
        (1e7, -10.0, -150.0),
    ]
    result = extract_ac_metrics(rows)
    assert result["gain_db"] == 60.0
    assert result["ugb_hz"] is not None
    assert result["phase_margin_deg"] is not None


from openams.validation.generic_ngspice_ac import (
    inject_control_block,
    render_template,
)


def test_render_template_rejects_unresolved() -> None:
    import pytest
    from openams.validation.generic_ngspice_ac import ValidationError
    with pytest.raises(ValidationError):
        render_template(".include {source_netlist}", {})


def test_control_is_before_final_end() -> None:
    deck = "* demo\n.end\n"
    rendered = inject_control_block(
        deck,
        ac_start_hz=1.0,
        ac_stop_hz=1e6,
        points_per_decade=10,
    )
    assert rendered.count(".end\n") == 1
    assert rendered.index(".control") < rendered.rindex(".end")
