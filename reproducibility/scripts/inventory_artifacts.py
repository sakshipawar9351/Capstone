#!/usr/bin/env python3
"""Inventory repository files with SHA-256; file presence is not scientific validation."""
from __future__ import annotations
import argparse, hashlib, json, platform, subprocess, sys
from pathlib import Path

EXTENSIONS = {
    "detector_checkpoint": {".pt", ".pth", ".ckpt", ".safetensors", ".onnx"},
    "prediction_or_metrics": {".csv", ".json", ".npz", ".npy", ".parquet"},
    "tile_manifest": {".csv", ".json", ".txt"},
    "benchmark_logs": {".csv", ".json", ".log", ".txt"},
}
KEYWORDS = {
    "detector_checkpoint": ("checkpoint", "best", "last", "model", "unet", "resnet"),
    "prediction_or_metrics": ("prediction", "pred", "metric", "evaluation", "result", "output"),
    "tile_manifest": ("manifest", "tile", "split", "dataset"),
    "benchmark_logs": ("benchmark", "planner", "run", "result", "log"),
}

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def git_value(root: Path, *args: str):
    try:
        return subprocess.check_output(["git", "-C", str(root), *args],
            stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    root = Path(args.root).resolve()
    if not root.is_dir():
        ap.error(f"not a directory: {root}")
    inventory = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.parts or "__pycache__" in path.parts:
            continue
        try:
            inventory.append({"path": str(path.relative_to(root)),
                "size_bytes": path.stat().st_size, "sha256": sha256(path)})
        except OSError:
            continue
    candidates = {}
    for category, extensions in EXTENSIONS.items():
        candidates[category] = [item["path"] for item in inventory
            if Path(item["path"]).suffix.lower() in extensions
            and any(word in Path(item["path"]).name.lower() for word in KEYWORDS[category])]
    report = {"root": str(root), "python": sys.version, "platform": platform.platform(),
        "git_commit": git_value(root, "rev-parse", "HEAD"),
        "git_status_porcelain": git_value(root, "status", "--porcelain"),
        "file_count": len(inventory), "files": inventory,
        "candidate_artifacts_by_category": candidates,
        "presence_only_checks": {key: bool(value) for key, value in candidates.items()},
        "warning": "File presence and hashes do not prove that an artifact matches a paper claim."}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(out), "file_count": len(inventory),
        "presence_only_checks": report["presence_only_checks"]}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
