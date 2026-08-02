from __future__ import annotations

import numpy as np

TARGET_NAMES = ("id_abs_a", "gm_s", "gds_s", "vdsat_abs_v", "vth_abs_v")


def physical_targets(encoded: np.ndarray) -> np.ndarray:
    encoded = np.asarray(encoded, dtype=np.float64)
    result = encoded.copy()
    result[:, :3] = np.exp(result[:, :3])
    return result


def regression_metrics(truth_encoded: np.ndarray, prediction_encoded: np.ndarray) -> dict[str, dict[str, float]]:
    truth, pred = physical_targets(truth_encoded), physical_targets(prediction_encoded)
    result: dict[str, dict[str, float]] = {}
    for i, name in enumerate(TARGET_NAMES):
        abs_err = np.abs(pred[:, i] - truth[:, i])
        denom = np.maximum(np.abs(truth[:, i]), 1e-30 if i < 3 else 1e-9)
        rel = abs_err / denom
        result[name] = {
            "mae": float(abs_err.mean()), "median_relative_error": float(np.median(rel)),
            "p95_relative_error": float(np.quantile(rel, 0.95)),
            "max_relative_error": float(rel.max()), "rmse": float(np.sqrt(np.mean((pred[:, i]-truth[:, i])**2))),
        }
        if i < 3:
            result[name]["median_log10_error"] = float(np.median(np.abs(np.log10(pred[:, i]) - np.log10(truth[:, i]))))
            result[name]["p95_log10_error"] = float(np.quantile(np.abs(np.log10(pred[:, i]) - np.log10(truth[:, i])), .95))
    return result
