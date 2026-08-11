#!/usr/bin/env python3
from pathlib import Path
import shutil

ROOT = Path.home() / "AMS-Tutorial" / "openams"
ENGINE = ROOT / "src/openams/validation/ngspice_witness.py"

def main():
    if not ENGINE.is_file():
        raise SystemExit(f"missing: {ENGINE}")

    s = ENGINE.read_text(encoding="utf-8")
    bak = ENGINE.with_suffix(".py.before_ascii_raw_parser_fix.bak")
    shutil.copy2(ENGINE, bak)

    start = s.find("def _parse_ac_raw(")
    end = s.find("\n\ndef _build_deck", start)
    if start < 0 or end < 0:
        raise RuntimeError("could not locate _parse_ac_raw()")

    replacement = '''def _parse_ac_raw(path: Path, output_name: str) -> dict[str, float]:
    if not path.exists() or path.stat().st_size == 0:
        return {}

    lines = path.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines()

    nvars = None
    npoints = None
    var_start = None
    value_start = None

    for i, line in enumerate(lines):
        text = line.strip()
        low = text.lower()

        if low.startswith("no. variables:"):
            nvars = int(text.split(":", 1)[1].strip())
        elif low.startswith("no. points:"):
            npoints = int(text.split(":", 1)[1].strip())
        elif text == "Variables:":
            var_start = i + 1
        elif text == "Values:":
            value_start = i + 1
            break

    if not nvars or not npoints or var_start is None or value_start is None:
        return {}

    names = []
    for line in lines[var_start:var_start + nvars]:
        tokens = line.split()
        if len(tokens) < 2:
            return {}
        names.append(tokens[1].strip().lower())

    try:
        fi = names.index("frequency")
    except ValueError:
        return {}

    wanted = str(output_name).strip().lower()
    try:
        oi = names.index(wanted)
    except ValueError:
        return {}

    def parse_complex_line(text: str) -> complex:
        text = text.strip()

        # First line of each point may start with the integer point index.
        parts = text.split(None, 1)
        payload = parts[-1] if len(parts) > 1 else parts[0]

        if "," in payload:
            real_text, imag_text = payload.split(",", 1)
            return complex(float(real_text), float(imag_text))

        return complex(float(payload), 0.0)

    data = []
    cursor = value_start

    for _ in range(npoints):
        point = []

        while cursor < len(lines) and len(point) < nvars:
            text = lines[cursor].strip()
            cursor += 1

            if not text:
                continue

            try:
                value = parse_complex_line(text)
            except Exception:
                continue

            point.append(value)

        if len(point) == nvars:
            data.append(point)

    if not data:
        return {}

    arr = np.asarray(data, dtype=complex)

    freq = np.real(arr[:, fi])
    out = arr[:, oi]

    valid = (
        np.isfinite(freq)
        & (freq > 0)
        & np.isfinite(np.real(out))
        & np.isfinite(np.imag(out))
    )

    freq = freq[valid]
    out = out[valid]

    if len(freq) < 2:
        return {}

    order = np.argsort(freq)
    freq = freq[order]
    out = out[order]

    magnitude = np.abs(out)
    gain_db = 20.0 * np.log10(np.maximum(magnitude, 1e-300))
    phase_deg = np.rad2deg(np.unwrap(np.angle(out)))

    result = {
        "ac_gain_db": float(gain_db[0]),
        "ac_phase_low_frequency_deg": float(phase_deg[0]),
    }

    bw_target = gain_db[0] - 3.0
    for i in range(len(freq) - 1):
        if gain_db[i] >= bw_target and gain_db[i + 1] <= bw_target:
            y0, y1 = gain_db[i], gain_db[i + 1]
            alpha = (bw_target - y0) / (y1 - y0) if y1 != y0 else 0.0
            logf = np.log10(freq[i]) + alpha * (
                np.log10(freq[i + 1]) - np.log10(freq[i])
            )
            result["ac_bandwidth_3db_hz"] = float(10 ** logf)
            break

    crossing = None
    for i in range(len(freq) - 1):
        if gain_db[i] >= 0.0 and gain_db[i + 1] <= 0.0:
            crossing = i
            break

    if crossing is not None:
        i = crossing
        y0, y1 = gain_db[i], gain_db[i + 1]
        alpha = (0.0 - y0) / (y1 - y0) if y1 != y0 else 0.0

        logf = np.log10(freq[i]) + alpha * (
            np.log10(freq[i + 1]) - np.log10(freq[i])
        )

        phase_cross = phase_deg[i] + alpha * (
            phase_deg[i + 1] - phase_deg[i]
        )

        result["ac_ugb_hz"] = float(10 ** logf)
        result["ac_phase_at_ugb_deg"] = float(phase_cross)
        result["ac_phase_margin_deg"] = float(180.0 + phase_cross)

    return result
'''

    s = s[:start] + replacement + s[end:]

    old_fields = '    fields += ["max_abs_voltage_delta_v", "dc_validation_status", "ac_gain_db", "ac_ugb_hz", "ac_phase_margin_deg", "validation_status"]'
    new_fields = '''    fields += [
        "max_abs_voltage_delta_v",
        "dc_validation_status",
        "ac_gain_db",
        "ac_bandwidth_3db_hz",
        "ac_phase_low_frequency_deg",
        "ac_ugb_hz",
        "ac_phase_at_ugb_deg",
        "ac_phase_margin_deg",
        "validation_status",
    ]'''
    if old_fields in s:
        s = s.replace(old_fields, new_fields, 1)

    ENGINE.write_text(s, encoding="utf-8")

    print("backup:", bak)
    print("patched:", ENGINE)
    print("fix: ASCII raw complex-value parsing")
    print("AC metrics: gain, BW, UGB, absolute phase, PM")

if __name__ == "__main__":
    main()
