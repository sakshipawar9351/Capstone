#!/usr/bin/env python3
"""Synthetic smoke tests for the validators only; this is not LunarSerpent experiment evidence."""
from __future__ import annotations
import csv, json, subprocess, sys, tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]

def run(script: str, *args: str) -> None:
    subprocess.run([sys.executable, str(BASE / "reproducibility" / "scripts" / script), *args],
                   check=True, cwd=BASE, capture_output=True, text=True)

def main() -> int:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        predictions = root / "predictions.csv"
        with predictions.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["tile_id","prediction_id","matched_catalog_id","confidence","split","checkpoint_sha256"])
            writer.writerow(["tile1","pred1","cat1","0.9","test","fake-hash-for-synthetic-test"])
            writer.writerow(["tile1","pred2","","0.8","test","fake-hash-for-synthetic-test"])
        metrics = root / "metrics.json"
        run("evaluate_crater_predictions.py", "--predictions", str(predictions),
            "--catalog-count", "2", "--out", str(metrics))
        report = json.loads(metrics.read_text(encoding="utf-8"))
        assert report["valid_for_metric_calculation"] is True
        assert (report["TP"], report["FP"], report["FN"]) == (1, 1, 1)
        assert (report["precision"], report["recall"], report["f1"]) == (0.5, 0.5, 0.5)

        fusion = root / "fusion.json"
        fusion.write_text(json.dumps({"sites":[{"site_id":"synthetic","input_hashes":{"dem_sha256":"synthetic"},
            "control":{"route":[[0,0],[1,1]],"route_cost":3,"config_hash":"control-config"},
            "treatment":{"route":[[0,0],[1,1]],"route_cost":4,"config_hash":"treatment-config"}}]}), encoding="utf-8")
        fusion_out = root / "fusion_out.json"
        run("compare_fusion_routes.py", "--input", str(fusion), "--out", str(fusion_out))
        fr = json.loads(fusion_out.read_text(encoding="utf-8"))
        assert fr["all_routes_identical"] is True
        assert fr["sites"][0]["relative_cost_change_pct"] > 33

        planner_csv = root / "planner_runs.csv"
        with planner_csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["source_commit","site_id","dem_id","dem_sha256","start","goal","planner","seed","run_index","success","path_cost","expanded_nodes","path_length_m","runtime_ms","config_sha256"])
            writer.writerow(["synthetic-commit","site","dem","synthetic-dem-sha","0,0","1,1","astar","0","0","true","5.0","12","4.0","2.5","synthetic-config-sha"])
        planner_out = root / "planner_audit.json"
        run("validate_planner_logs.py", "--csv", str(planner_csv), "--out", str(planner_out))
        pr = json.loads(planner_out.read_text(encoding="utf-8"))
        assert pr["valid_basic_log_structure"] is True and pr["row_count"] == 1

    print("PASS: reproducibility validators pass synthetic fixtures only; no scientific result was generated.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
