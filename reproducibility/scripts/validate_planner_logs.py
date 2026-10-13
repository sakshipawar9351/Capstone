#!/usr/bin/env python3
"""Validate structure/basic consistency of run-level planner logs, not path optimality."""
from __future__ import annotations
import argparse, csv, hashlib, json, math
from pathlib import Path

REQUIRED = {
    "source_commit", "site_id", "dem_id", "dem_sha256", "start", "goal", "planner",
    "seed", "run_index", "success", "path_cost", "expanded_nodes", "path_length_m",
    "runtime_ms", "config_sha256",
}

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    source = Path(args.csv)
    with source.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows, columns = list(reader), set(reader.fieldnames or [])
    if not rows:
        raise SystemExit("ERROR: planner-run CSV is empty")
    missing = REQUIRED - columns
    if missing:
        raise SystemExit(f"ERROR: missing columns {sorted(missing)}")
    errors, seen = [], set()
    for line, row in enumerate(rows, start=2):
        key = (row["site_id"], row["planner"], row["seed"], row["run_index"])
        if key in seen:
            errors.append(f"line {line}: duplicate site/planner/seed/run_index {key}")
        seen.add(key)
        success = row["success"].strip().lower()
        if success not in {"true", "false", "1", "0", "yes", "no"}:
            errors.append(f"line {line}: invalid success value {row['success']!r}")
        numeric = {}
        for column in ("path_cost", "expanded_nodes", "path_length_m", "runtime_ms"):
            try:
                numeric[column] = float(row[column])
            except (TypeError, ValueError):
                errors.append(f"line {line}: {column} is not numeric")
                continue
            if not math.isfinite(numeric[column]) or numeric[column] < 0:
                errors.append(f"line {line}: {column} is negative or non-finite")
        if success in {"true", "1", "yes"} and numeric.get("path_cost", 0) <= 0:
            errors.append(f"line {line}: successful path has nonpositive path_cost")
        for column in ("source_commit", "dem_sha256", "config_sha256", "site_id",
                       "dem_id", "planner", "start", "goal"):
            if not row[column].strip():
                errors.append(f"line {line}: {column} is empty")
    groups = {}
    for row in rows:
        groups.setdefault((row["site_id"], row["planner"]), []).append(row)
    report = {"input_csv": str(source),
        "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "row_count": len(rows), "site_count": len({row["site_id"] for row in rows}),
        "planners": sorted({row["planner"] for row in rows}), "errors": errors,
        "runs_per_site_planner": {"|".join(key): len(value) for key, value in sorted(groups.items())},
        "valid_basic_log_structure": not errors,
        "warning": "Passing this validator is not proof of algorithm correctness or a fair comparison; inputs and configuration must match."}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"row_count": report["row_count"],
        "valid_basic_log_structure": report["valid_basic_log_structure"],
        "errors": errors[:10], "output": str(out)}, indent=2))
    return 0 if not errors else 2

if __name__ == "__main__":
    raise SystemExit(main())
