#!/usr/bin/env python3
"""Audit evidence required to reproduce LunarSerpent manuscript experiments.

This is a submission gate, not a model evaluator. It deliberately does not infer
scientific metrics from source code or substitute one sensor modality for another.

Usage:
    python scripts/audit_manuscript_artifacts.py
    python scripts/audit_manuscript_artifacts.py --artifact-root "G:/My Drive/LunarSerpent_models"
    python scripts/audit_manuscript_artifacts.py --output docs/results/manuscript_artifact_audit.json

Exit code 0 means no configured blockers were detected. Exit code 1 means one or
more required artifacts are missing or the tracked notebook modality conflicts
with the LOLA-DEM experiment described in the manuscript.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODEL_EXTENSIONS = {".pt", ".pth", ".ckpt", ".onnx", ".safetensors"}
RESULT_EXTENSIONS = {".json", ".csv", ".jsonl", ".yaml", ".yml"}
EXCLUDED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"}


def files_under(path: Path) -> list[Path]:
    """Return files below path, excluding common generated/environment trees."""
    if not path.exists():
        return []
    found: list[Path] = []
    for current, directories, filenames in os.walk(path):
        current_path = Path(current)
        directories[:] = [name for name in directories if name not in EXCLUDED_DIRS and name not in {"cache", "tmp", "temp"}]
        for name in filenames:
            found.append(current_path / name)
    return found


def text_of_notebook(path: Path) -> tuple[str, int, int]:
    """Return notebook source and executed-cell/output counts without executing it."""
    data = json.loads(path.read_text(encoding="utf-8"))
    source: list[str] = []
    executed = outputs = 0
    for cell in data.get("cells", []):
        source.extend(cell.get("source", []))
        if cell.get("cell_type") == "code":
            if cell.get("execution_count") is not None:
                executed += 1
            if cell.get("outputs"):
                outputs += 1
    return "\n".join(source), executed, outputs


def finding(level: str, code: str, message: str) -> dict[str, str]:
    return {"level": level, "code": code, "message": message}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=ROOT,
        help="Root to search for local/external model and evaluation artifacts (default: repository).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON report path. Parent directories are created if needed.",
    )
    args = parser.parse_args()

    artifact_root = args.artifact_root.expanduser().resolve()
    repo_files = files_under(ROOT)
    artifact_files = files_under(artifact_root)
    findings: list[dict[str, str]] = []
    evidence: dict[str, Any] = {
        "repository": str(ROOT),
        "artifact_root": str(artifact_root),
        "repository_files_scanned": len(repo_files),
        "artifact_files_scanned": len(artifact_files),
    }

    checkpoints = sorted({
        str(p) for p in artifact_files if p.suffix.lower() in MODEL_EXTENSIONS
    })
    evidence["model_checkpoints"] = checkpoints
    if not checkpoints:
        findings.append(finding(
            "BLOCKER", "MODEL_CHECKPOINT_MISSING",
            "No model checkpoint was found under the artifact root. A paper detector score must be tied to the exact weights used.",
        ))

    # The current checked-in U-Net notebook states the optical experiment's
    # modality/resolution. This is intentionally not taken as evidence of a LOLA
    # DEM model, even if the model architecture happens to match.
    notebook_path = ROOT / "notebooks" / "train_crater_unet_colab.ipynb"
    if notebook_path.exists():
        try:
            notebook_source, executed, outputs = text_of_notebook(notebook_path)
            mentions_kaguya = "Kaguya" in notebook_source or "kaguya" in notebook_source
            mentions_lola = "LOLA" in notebook_source or "lola" in notebook_source
            evidence["unet_notebook"] = {
                "path": str(notebook_path.relative_to(ROOT)),
                "mentions_kaguya": mentions_kaguya,
                "mentions_lola": mentions_lola,
                "executed_code_cells": executed,
                "cells_with_saved_outputs": outputs,
            }
            if mentions_kaguya and not mentions_lola:
                findings.append(finding(
                    "BLOCKER", "NOTEBOOK_MODALITY_MISMATCH",
                    "The checked-in U-Net notebook refers to Kaguya imagery but not LOLA. It cannot substantiate a LOLA-DEM experiment without a separate matching training/evaluation artifact.",
                ))
            if executed == 0 or outputs == 0:
                findings.append(finding(
                    "BLOCKER", "NOTEBOOK_HAS_NO_EXECUTION_EVIDENCE",
                    "The checked-in U-Net notebook has no saved executed code outputs; source cells alone do not establish the reported metrics.",
                ))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            findings.append(finding(
                "BLOCKER", "NOTEBOOK_UNREADABLE",
                f"Could not parse the U-Net notebook: {exc}",
            ))
    else:
        findings.append(finding(
            "BLOCKER", "TRAINING_NOTEBOOK_MISSING",
            "The expected U-Net training notebook is not present in this repository snapshot.",
        ))

    filenames = [p for p in artifact_files if p.suffix.lower() in RESULT_EXTENSIONS]
    evaluation_files = sorted(
        str(p) for p in filenames
        if any(token in p.name.lower() for token in (
            "evaluation", "eval_metrics", "prediction_metrics", "detector_metrics",
            "split_manifest", "run_manifest", "model_card",
        ))
    )
    evidence["evaluation_and_provenance_files"] = evaluation_files
    if not evaluation_files:
        findings.append(finding(
            "BLOCKER", "EVALUATION_PROVENANCE_MISSING",
            "No recognisable evaluation/provenance manifest (metrics, split manifest, run manifest, or model card) was found under the artifact root.",
        ))

    fusion_files = sorted(
        str(p) for p in filenames
        if "fusion" in p.name.lower() and "baseline_terrain_only" not in p.name.lower()
    )
    evidence["fusion_result_files"] = fusion_files
    if not fusion_files:
        findings.append(finding(
            "BLOCKER", "FUSION_RESULTS_MISSING",
            "No crater-fusion result artifact was found. The terrain-only baseline is not evidence for a fusion treatment.",
        ))

    baseline = ROOT / "docs" / "results" / "baseline_terrain_only.json"
    evidence["terrain_only_baseline_present"] = baseline.exists()
    if baseline.exists():
        try:
            baseline_data = json.loads(baseline.read_text(encoding="utf-8"))
            cases = baseline_data.get("cases", baseline_data.get("results", []))
            evidence["terrain_only_baseline_case_count"] = len(cases) if isinstance(cases, list) else None
        except (OSError, json.JSONDecodeError) as exc:
            findings.append(finding(
                "WARNING", "BASELINE_JSON_UNREADABLE",
                f"The terrain-only baseline could not be parsed: {exc}",
            ))

    blockers = sum(item["level"] == "BLOCKER" for item in findings)
    report: dict[str, Any] = {
        "audit_schema": "lunarserpent-manuscript-artifact-audit-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": "Repository/artifact-presence and provenance checks only; no model evaluation is performed.",
        "submission_gate": "BLOCKED" if blockers else "NO_CONFIGURED_BLOCKERS_FOUND",
        "blocker_count": blockers,
        "evidence": evidence,
        "findings": findings,
    }

    print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.output:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nWrote report: {output}")
    return 1 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
