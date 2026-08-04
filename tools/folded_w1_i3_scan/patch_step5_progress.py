#!/usr/bin/env python3
from pathlib import Path
import sys
path = Path(sys.argv[1] if len(sys.argv) > 1 else 'src/openams/synthesis/generic_complete_step5.py')
text = path.read_text()
if 'OPENAMS_STEP5_PROGRESS_EVERY' in text:
    print('[PASS] progress already present')
    raise SystemExit(0)
text = text.replace('import math\n', 'import math\nimport os\nimport time\n', 1)
old = '''    assignments: list[dict[str, Any]] = []
    rejection_counts: Counter[str] = Counter()
    for combination_index, combination in enumerate(combinations):
'''
new = '''    assignments: list[dict[str, Any]] = []
    rejection_counts: Counter[str] = Counter()
    progress_every = max(1, int(os.environ.get("OPENAMS_STEP5_PROGRESS_EVERY", "25")))
    progress_file = os.environ.get("OPENAMS_STEP5_PROGRESS_FILE")
    progress_start = time.perf_counter()
    successful_points = 0
    for combination_index, combination in enumerate(combinations):
'''
if old not in text:
    raise SystemExit('[FAIL] progress loop marker not found')
text = text.replace(old, new, 1)
old2 = '''        if not point_solutions:
            rejection_counts.update(point_failures)
            continue
        for local_index, assignment in enumerate(point_solutions):
'''
new2 = '''        if not point_solutions:
            rejection_counts.update(point_failures)
        else:
            successful_points += 1
        for local_index, assignment in enumerate(point_solutions):
'''
if old2 not in text:
    raise SystemExit('[FAIL] solution marker not found')
text = text.replace(old2, new2, 1)
old3 = '''        if max_assignments is not None and len(assignments) >= max_assignments:
            break
    flush_provider = getattr(provider, "flush", None)
'''
new3 = '''        processed = combination_index + 1
        if processed == 1 or processed % progress_every == 0 or processed == len(combinations):
            elapsed = time.perf_counter() - progress_start
            payload = {
                "processed_independent_points": processed,
                "total_independent_points": len(combinations),
                "remaining_independent_points": len(combinations) - processed,
                "completion_percent": 100.0 * processed / len(combinations),
                "successful_independent_points": successful_points,
                "complete_assignments": len(assignments),
                "provider_queries": int(getattr(provider, "query_count", 0)),
                "fallback_requests": int(getattr(provider, "fallback_request_count", 0)),
                "fallback_results": int(getattr(provider, "fallback_result_count", 0)),
                "elapsed_s": elapsed,
                "throughput_points_per_s": processed / max(elapsed, 1e-12),
            }
            print(
                f"[PROGRESS] {processed}/{len(combinations)} "
                f"({payload['completion_percent']:.2f}%) "
                f"successful={successful_points} assignments={len(assignments)} "
                f"queries={payload['provider_queries']} "
                f"fallback={payload['fallback_requests']}/{payload['fallback_results']} "
                f"elapsed_s={elapsed:.1f}",
                flush=True,
            )
            if progress_file:
                progress_path = Path(progress_file)
                progress_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = progress_path.with_suffix(progress_path.suffix + '.tmp')
                tmp.write_text(json.dumps(payload, indent=2) + '\\n')
                tmp.replace(progress_path)
        if max_assignments is not None and len(assignments) >= max_assignments:
            break
    flush_provider = getattr(provider, "flush", None)
'''
if old3 not in text:
    raise SystemExit('[FAIL] loop tail marker not found')
text = text.replace(old3, new3, 1)
backup = path.with_suffix(path.suffix + '.before_progress_reporting')
if not backup.exists():
    backup.write_text(path.read_text())
path.write_text(text)
print(f'[PASS] patched {path}')
