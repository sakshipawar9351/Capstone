#!/usr/bin/env python3
"""Calculate object-level precision/recall/F1 from a frozen one-to-one match export."""
from __future__ import annotations
import argparse, csv, hashlib, json
from collections import Counter
from pathlib import Path

REQUIRED = {"tile_id", "prediction_id", "matched_catalog_id", "split", "checkpoint_sha256"}

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--predictions", required=True)
    ap.add_argument("--catalog-count", type=int, required=True,
        help="Reference-object count in this exact frozen test set")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    if args.catalog_count < 0:
        ap.error("--catalog-count cannot be negative")
    source = Path(args.predictions)
    with source.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows, columns = list(reader), set(reader.fieldnames or [])
    if not rows:
        raise SystemExit("ERROR: prediction CSV is empty")
    missing = REQUIRED - columns
    if missing:
        raise SystemExit(f"ERROR: missing columns: {sorted(missing)}")
    non_test = [i + 2 for i, row in enumerate(rows)
        if row["split"].strip().lower() != "test"]
    pred_ids = [row["prediction_id"].strip() for row in rows]
    duplicate_predictions = sorted(k for k, v in Counter(pred_ids).items() if k and v > 1)
    matches = [row["matched_catalog_id"].strip() for row in rows
        if row["matched_catalog_id"].strip()]
    duplicate_matches = sorted(k for k, v in Counter(matches).items() if v > 1)
    checkpoints = sorted({row["checkpoint_sha256"].strip() for row in rows})
    empty_ids = [i + 2 for i, row in enumerate(rows) if not row["prediction_id"].strip()]
    empty_checkpoints = [i + 2 for i, row in enumerate(rows)
        if not row["checkpoint_sha256"].strip()]
    errors = []
    if non_test: errors.append(f"non-test rows at CSV lines {non_test[:20]}")
    if duplicate_predictions: errors.append(f"duplicate prediction IDs: {duplicate_predictions[:20]}")
    if duplicate_matches: errors.append(f"duplicate catalogue matches: {duplicate_matches[:20]}")
    if len(checkpoints) != 1 or not checkpoints or checkpoints == [""]:
        errors.append(f"expected one non-empty checkpoint SHA, got {checkpoints}")
    if empty_ids: errors.append(f"empty prediction IDs at CSV lines {empty_ids[:20]}")
    if empty_checkpoints: errors.append(f"empty checkpoint hashes at CSV lines {empty_checkpoints[:20]}")
    tp = len(matches)
    fp = len(rows) - tp
    fn = args.catalog_count - tp
    if fn < 0: errors.append(f"matched predictions ({tp}) exceed reference count ({args.catalog_count})")
    valid = not errors
    precision = tp / (tp + fp) if valid and tp + fp else (0.0 if valid else None)
    recall = tp / (tp + fn) if valid and tp + fn else (0.0 if valid else None)
    f1 = 2 * precision * recall / (precision + recall) if valid and precision + recall else (0.0 if valid else None)
    report = {"input_csv": str(source),
        "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "reference_catalog_count": args.catalog_count, "prediction_rows": len(rows),
        "unique_prediction_ids": len(set(pred_ids)), "matched_predictions": len(matches),
        "duplicate_prediction_ids": duplicate_predictions, "duplicate_catalog_matches": duplicate_matches,
        "non_test_rows_1based_csv_line_numbers": non_test,
        "checkpoint_sha256_values": checkpoints, "valid_for_metric_calculation": valid,
        "errors": errors, "TP": tp if valid else None, "FP": fp if valid else None,
        "FN": fn if valid else None, "precision": precision, "recall": recall, "f1": f1,
        "warning": "This validates exported match records only; it does not validate the matching algorithm, catalogue subset, split independence, or scientific validity."}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in
        ("valid_for_metric_calculation", "TP", "FP", "FN", "precision", "recall", "f1", "errors")}, indent=2))
    return 0 if valid else 2

if __name__ == "__main__":
    raise SystemExit(main())
