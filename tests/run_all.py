"""
LunarSerpent — full verification run.

Executes every suite in order and reports a single verdict.  Suites that need a
running server are detected and skipped with a clear message rather than
failing, so this can be run against a cold checkout.

    python tests/run_all.py            # everything
    python tests/run_all.py --offline  # only suites that need no server

Everything runs from the project directory on D:; nothing is written outside it.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: (label, target, needs_server).  Module targets run with -m so relative
#: imports inside the package resolve correctly.
SUITES: list[tuple[str, list[str], bool]] = [
    ("selenographic core",      ["-m", "backend.core.selenographic"], False),
    ("PDS3 reader",             ["-m", "backend.core.pds"],           False),
    ("raster access",           ["-m", "backend.core.raster"],        False),
    ("NAC stereo DTM (2 m)",    ["-m", "backend.core.nac_dtm"],       False),
    ("local projection",        ["-m", "backend.core.projection"],    False),
    ("area of interest",        ["-m", "backend.core.aoi"],           False),
    ("background jobs",         ["-m", "backend.core.jobs"],          False),
    ("AOI window reader",       ["-m", "backend.core.aoi_window"],    False),
    ("crater catalogue",        ["-m", "backend.data.catalog_robbins"], False),
    ("IAU nomenclature",        ["-m", "backend.data.nomenclature"],  False),
    ("per-region data catalogue", ["-m", "backend.data.trek_catalog"], False),
    ("crater training tiles",   ["-m", "backend.ml.dataset"],          False),
    ("terrain derivatives",     ["-m", "backend.analysis.terrain"],   False),
    ("crater morphometry",      ["-m", "backend.analysis.morphometry"], False),
    ("terramechanics",          ["-m", "backend.analysis.terramechanics"], False),
    ("traversability + slip",   ["-m", "backend.analysis.hazard"],    False),
    ("ground truth (11 driven sites)", ["-m", "backend.analysis.ground_truth"], False),
    ("frozen baseline control", ["-m", "backend.planning.baseline"], False),
    ("path metrics",            ["-m", "backend.planning.metrics"],   False),
    ("path planners",           ["tests/test_planners.py"],           False),
    ("planning service",        ["tests/test_plan_service.py"],       False),
    ("planning API",            ["tests/test_plan_api.py"],           False),
    ("layer rendering API",     ["tests/test_layers_api.py"],         False),
    ("region surface mesh",     ["tests/test_terrain3d_api.py"],      False),
    ("tile cache budget",       ["tests/test_tile_cache.py"],         False),
    ("Cesium datum vs LOLA",    ["tests/test_cesium_datum.py"],       False),
    ("Cesium terrain tiles",    ["tests/test_terrain_tile.py"],       False),
    ("cross-product registration", ["tests/test_registration.py"],    False),
    ("polar DEM",               ["tests/test_polar_dem.py"],          False),
    ("hazard on real terrain",  ["tests/test_hazard_real.py"],        False),
    ("polar traverse end-to-end", ["tests/test_traverse_polar.py"],   False),
    ("catalogue join",          ["tests/test_catalogue_join.py"],     False),
    ("data resolution",         ["tests/test_data_resolution.py"],    False),
    ("documentation audit",     ["tests/audit_docs.py"],              False),
    # Static, fast, and previously never run by anything — an audit nobody
    # invokes catches nothing. It reads the HTML and JS for unwired controls,
    # dead element ids and renderer parity, which the browser suite cannot see.
    ("frontend audit",          ["tests/audit_frontend.py"],          False),
    ("API smoke",               ["tests/test_api_smoke.py"],          True),
    ("named features + morphometry", ["tests/test_features.py"],      True),
    ("terrain grid",            ["tests/test_terrain_grid.py"],       True),
    ("tile level-of-detail",    ["tests/test_tile_lod.py"],           True),
    ("frontend in a browser",   ["tests/test_browser.py"],            True),
]


def server_up() -> bool:
    try:
        import requests

        requests.get("http://127.0.0.1:8765/api/v1/meta/health", timeout=3)
        return True
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    offline = "--offline" in sys.argv
    live = False if offline else server_up()

    if not offline and not live:
        print("NOTE  server not reachable on 127.0.0.1:8765 — API suites will "
              "be skipped.\n      start it with:  python -m uvicorn "
              "backend.main:app --port 8765\n")

    print(f"{'SUITE':<34}{'RESULT':>10}{'TIME':>9}")
    print("-" * 53)

    passed = failed = skipped = 0
    failures: list[str] = []
    t_start = time.time()

    for label, target, needs_server in SUITES:
        if needs_server and not live:
            print(f"{label:<34}{'SKIP':>10}{'—':>9}")
            skipped += 1
            continue

        t0 = time.time()
        proc = subprocess.run(
            [sys.executable, *target],
            cwd=ROOT, capture_output=True, text=True,
        )
        dt = time.time() - t0
        ok = proc.returncode == 0
        print(f"{label:<34}{'PASS' if ok else 'FAIL':>10}{dt:>8.1f}s")
        if ok:
            passed += 1
        else:
            failed += 1
            tail = (proc.stdout + proc.stderr).strip().splitlines()
            failures.append(label + "\n    " + "\n    ".join(tail[-12:]))

    print("-" * 53)
    total = time.time() - t_start
    print(f"{passed} passed, {failed} failed, {skipped} skipped "
          f"in {total:.1f}s")

    if failures:
        print("\n" + "=" * 53)
        print("FAILURES")
        print("=" * 53)
        for f in failures:
            print("\n" + f)

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
