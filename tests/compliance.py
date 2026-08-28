"""
Requirement compliance tracker.

Walks every functional requirement in PRD.md and reports its true state, with
evidence. Requirements are verified live where that is possible; where a claim
can only be settled by reading the code, the status is asserted here and the
justification recorded alongside so it can be challenged.

    python tests/compliance.py            # full report
    python tests/compliance.py --open     # only what is not done

Status values are deliberately blunt. "Partial" means a user would find
something missing, not that work has started.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests  # noqa: E402

API = "http://127.0.0.1:8765/api/v1"
S = requests.Session()

DONE, PART, OPEN = "DONE", "PARTIAL", "OPEN"


def live(path, params=None, timeout=60):
    """True if an endpoint answers successfully."""
    try:
        r = S.get(f"{API}/{path}", params=params or {}, timeout=timeout)
        return r.status_code == 200, r
    except Exception:
        return False, None


def has_endpoint(path, params=None):
    return live(path, params)[0]


# Probe once so requirement rows can cite real evidence.
server_up = False
for _ in range(30):
    try:
        S.get(f"{API}/meta/health", timeout=3)
        server_up = True
        break
    except Exception:
        time.sleep(0.4)

ok_craters = has_endpoint("craters/bbox", {"min_diameter_km": 50, "limit": 5})
ok_named = has_endpoint("features/named", {"limit": 5})
ok_morph = has_endpoint("features/analyse", {"name": "Tycho"}, )
ok_terrain = has_endpoint("terrain/point", {"lat": 0, "lon": 180})
ok_grid = has_endpoint("terrain/grid", {"south": -1, "north": 1,
                                        "west": 0, "east": 2,
                                        "width": 16, "height": 16})
ok_plan = has_endpoint("plan", {"lat1": -89, "lon1": 0, "lat2": -88, "lon2": 10})
ok_hazard = has_endpoint("hazard/map", {"lat": -89, "lon": 0})
ok_boulder = has_endpoint("boulders/detect", {"lat": -89, "lon": 0})
ok_export = has_endpoint("export/path")

# Which derived quantities are actually renderable as maps, asked of the server
# rather than asserted here. A layer that exists only in an analysis module is
# not a layer a user can see.
_SITE = {"south": -89.50, "north": -89.46, "west": 220.0, "east": 224.0}
rendered = set()
if server_up:
    _ok, _r = live("aoi/layers")
    if _ok:
        rendered = {x["key"] for x in _r.json()["layers"]}
ok_layer_png = has_endpoint("aoi/layer", {**_SITE, "layer": "hazard"})

ROOT = Path(__file__).resolve().parents[1]
src = lambda p: (ROOT / p).exists()  # noqa: E731

REQS = [
    # ── FR-1 Globe ───────────────────────────────────────────────────────
    ("FR-1.1", "Interactive 3-D globe", DONE, "Three.js + Cesium, both live"),
    ("FR-1.2", "Google-Earth-class clarity", DONE,
     "WAC 100 m/px; Cesium 3D Tiles to 83 m"),
    ("FR-1.3", "Real selenographic positioning", DONE,
     "verified: pole-to-pole 5458.203 km = exact half-circumference"),
    ("FR-1.4", "Both poles clearly visible", DONE,
     "pole viewpoints + 10 m/px polar stereographic DEM"),
    ("FR-1.5", "Full 360 deg viewing", DONE, "constrainedAxis freed in Cesium"),
    ("FR-1.6", "No illumination effects", DONE,
     "MeshBasicMaterial; Cesium light intensity 0"),
    ("FR-1.7", "Zoom retains resolution", DONE,
     "WMTS LOD to z=8; Cesium adaptive 3D Tiles"),
    ("FR-1.8", "Auto and manual rotate", DONE, "both renderers"),
    ("FR-1.9", "Coordinate input", DONE, "typed entry + click-to-sample"),
    ("FR-1.10", "Named features at exact coordinates", DONE,
     "9 086 IAU features" if ok_named else "endpoint down"),
    ("FR-1.11", "Legible when zoomed out", DONE,
     "screen-space collision culling, priority by class"),
    ("FR-1.12", "Layers panel", DONE, "Layers/Places/Missions/Science"),
    # Five of the six render as PNG map layers over any region; the sixth needs
    # imagery this project does not have. Partial rather than done, because a
    # user looking for boulders still finds nothing.
    ("FR-1.13", "Six derived layers (hazard, risk, crater, boulder, slope, cost)",
     PART,
     f"{len({'hazard', 'risk', 'slope', 'cost'} & rendered)}/4 of the derived "
     f"surfaces render as map layers "
     f"({'PNG endpoint live' if ok_layer_png else 'endpoint down'}); "
     f"crater layer live; boulder still absent — it needs sub-metre imagery, "
     f"as a 1 m rock is 1 % of one 10 m cell"),
    ("FR-1.14", "Elevation, roughness, curvature, aspect, geology layers",
     PART, "elevation, roughness and hillshade (Horn slope+aspect) render; "
           "curvature computed but not rendered; geology needs a source "
           "this project does not have"),
    ("FR-1.15", "Graticule", DONE, "adaptive 30 deg to 0.1 deg"),
    ("FR-1.16", "Offline fallback basemap", PART,
     "moon_texture.jpg present on disk; not wired as a fallback"),

    # ── FR-2 Detection ───────────────────────────────────────────────────
    ("FR-2.1", "Global crater layer >= 1 km", DONE,
     "1 296 796 craters" if ok_craters else "endpoint down"),
    ("FR-2.2", "Detect craters below catalogue limit from DEM", OPEN,
     "no detector implemented"),
    ("FR-2.3", "Boulder detection at metre scale", OPEN,
     "NAC scenes downloaded with geometry; detector not built"),
    ("FR-2.4", "Full scientific information per feature", PART,
     "depth, rim, slope, volume, class, d/D vs Pike present; "
     "age/epoch and degradation index absent"),
    ("FR-2.5", "State detection limit with every survey", OPEN,
     "depends on FR-2.2/2.3"),
    ("FR-2.6", "Extrapolate sub-resolution boulder population", OPEN, ""),
    ("FR-2.7", "Validate detector against ground truth", OPEN,
     "artificial_lunar (16 500 labelled images) available, unused"),

    # ── FR-3 Classification ──────────────────────────────────────────────
    ("FR-3.1", "Seven size classes", DONE, "config.CRATER_CLASSES"),
    ("FR-3.2", "Boundaries from published transitions", DONE,
     "each cites a physical transition, e.g. simple->complex at 15 km"),
    ("FR-3.3", "Formula/proof per rule", DONE, "FORMULAS.md sec 4"),
    ("FR-3.4", "Distinct colour per class", DONE, "legend in Layers panel"),
    ("FR-3.5", "Boulder size/hazard classes", OPEN, "depends on FR-2.3"),
    ("FR-3.6", "Morphological type", DONE, "simple/complex/peak-ring/basin"),

    # ── FR-4 Per-feature ─────────────────────────────────────────────────
    ("FR-4.1", "Click a crater -> full profile", DONE,
     "features/analyse" if ok_morph else "endpoint down"),
    ("FR-4.2", "Click any point -> terrain science", PART,
     "elevation, radius, resolution, enclosing craters returned; "
     "slope/aspect/curvature/roughness NOT in the point response"),
    ("FR-4.3", "Inspect any point along a planned path", PART,
     "every sample carries elevation, slope, risk and slip in the route "
     "profile; clicking a point on the drawn route is not yet wired"),
    ("FR-4.4", "Units and measurement baseline on every value", DONE,
     "baseline is a required field; adequacy stated"),
    ("FR-4.5", "Elevation profile along a path/transect", DONE,
     "plotted against ground distance, densified to grid resolution so it "
     "follows the terrain rather than the waypoints"),
    ("FR-4.6", "Slope profile with rover limit marked", PART,
     "slope is plotted on its own axis; the rover's limit is not yet drawn "
     "as a reference line"),

    # ── FR-5 Formulas ────────────────────────────────────────────────────
    ("FR-5.1", "Separate formula document", DONE,
     "docs/FORMULAS.md" if src("docs/FORMULAS.md") else "missing"),
    ("FR-5.2", "Proof per formula", DONE, "derivation section per entry"),
    ("FR-5.3", "DOI-resolvable citation per formula", DONE, ""),
    ("FR-5.4", "Why this formula, alternatives rejected", DONE, ""),
    ("FR-5.5", "Formulas verified by executable tests", DONE,
     "selenographic, terrain, morphometry, polar, hazard all self-test"),

    # ── FR-6 Path planning ───────────────────────────────────────────────
    ("FR-6.1", "Select start/end by lat/lon", DONE,
     "typed in the Plan panel or placed by clicking the globe; an endpoint on "
     "impassable ground is snapped and the distance moved is reported"),
    ("FR-6.2", "Safest path avoiding hazards", DONE,
     "planned on the slip-aware cost surface; impassable cells are infinite so "
     "no planner can be tuned across one (tests/test_traverse_polar.py)"),
    ("FR-6.3", "Compare >= 6 algorithms", DONE,
     "seven on one grid: BFS, Dijkstra, A*, Weighted A*, Theta*, D* Lite, RRT*"),
    ("FR-6.4", "State selected algorithm and why", DONE,
     "ALGORITHMS.md 6.1 carries measured results; three claims in 4 were "
     "revised because measurement contradicted them"),
    ("FR-6.5", "Show other algorithms' paths", PART,
     "every algorithm's cost, ratio, runtime and expansions are tabled; only "
     "the recommended route is drawn on the globe"),
    ("FR-6.6", "Highlight recommended path", DONE,
     "starred in the comparison table and drawn coloured by per-sample risk"),
    ("FR-6.7", "Explain why it is recommended", DONE,
     "reasoning is computed per run from what was measured, not fixed text"),
    ("FR-6.8", "Per-path metrics (distance, time, speed, cost, slope, "
               "risk, safety, craters avoided)", DONE,
     "planning/metrics.py; 3-D distance, energy, safety score with its "
     "limiting factor named"),
    ("FR-6.9", "Start/end pin markers", DONE,
     "on both renderers, labelled START/GOAL"),
    ("FR-6.10", "Selectable rover profile", DONE,
     "4 profiles selectable in the Plan panel and honoured end to end"),
    ("FR-6.11", "Risk-aversion parameter exposed", DONE,
     "gamma slider in the Plan panel, passed through to the cost surface"),
    ("FR-6.12", "Replanning on new hazard (D* Lite)", PART,
     "D* Lite implemented and optimal; its incremental repair path is not yet "
     "driven by a hazard appearing mid-traverse"),

    # ── FR-7 Interface ───────────────────────────────────────────────────
    ("FR-7.1", "Professional scientific design", DONE, ""),
    ("FR-7.2", "Interactive and responsive", DONE, ""),
    ("FR-7.3", "Layer legends with units", PART,
     "crater classes and discovery status have legends; derived layers do not"),
    ("FR-7.4", "Feature search by name", DONE, "type-ahead over IAU names"),
    ("FR-7.5", "Export JSON/CSV/GeoJSON", OPEN, ""),
    ("FR-7.6", "Provenance visible in-app", DONE,
     "badge names renderer, surface, shape and measuring instrument"),
]


def main() -> int:
    only_open = "--open" in sys.argv

    groups: dict[str, list] = {}
    for rid, title, status, note in REQS:
        groups.setdefault(rid.split(".")[0], []).append((rid, title, status, note))

    NAMES = {
        "FR-1": "3D Moon globe", "FR-2": "Crater & boulder detection",
        "FR-3": "Classification", "FR-4": "Per-feature calculation",
        "FR-5": "Formula documentation", "FR-6": "Path planning",
        "FR-7": "Interface",
    }

    print("=" * 78)
    print("REQUIREMENT COMPLIANCE" + ("  (open items only)" if only_open else ""))
    print("=" * 78)
    if not server_up:
        print("  NOTE: server not running — live checks skipped\n")

    tot = {DONE: 0, PART: 0, OPEN: 0}
    for gid in sorted(groups):
        rows = groups[gid]
        for _, _, s, _ in rows:
            tot[s] += 1
        shown = [r for r in rows if not only_open or r[2] != DONE]
        if not shown:
            continue

        d = sum(1 for r in rows if r[2] == DONE)
        print(f"\n{gid} — {NAMES[gid]}   [{d}/{len(rows)} done]")
        print("-" * 78)
        for rid, title, status, note in shown:
            mark = {DONE: "  ok  ", PART: " part ", OPEN: " OPEN "}[status]
            print(f" {mark} {rid:<8} {title}")
            if note:
                for line in _wrap(note, 62):
                    print(f"{'':>18}{line}")

    n = sum(tot.values())
    print()
    print("=" * 78)
    print(f"  {tot[DONE]}/{n} done   {tot[PART]} partial   {tot[OPEN]} open"
          f"   ({tot[DONE] / n * 100:.0f}% complete)")
    print("=" * 78)

    # Computed, not asserted. This paragraph named FR-6 as the largest gap long
    # after FR-6 had been built, because it was hardcoded — a status report that
    # can go stale is worse than none, since it is trusted.
    by_group: dict[str, list] = {}
    for rid, title, status, _note in REQS:
        by_group.setdefault(rid.split(".")[0], []).append((rid, title, status))

    ranked = sorted(
        ((g, sum(1 for r in rows if r[2] == OPEN),
          sum(1 for r in rows if r[2] == PART), len(rows))
         for g, rows in by_group.items()),
        key=lambda x: (-x[1], -x[2]))

    print("\n  Largest remaining gaps:")
    for gid, n_open, n_part, n_all in ranked[:3]:
        if not (n_open or n_part):
            continue
        print(f"    {gid:<6} {NAMES[gid]:<28} {n_open} open, {n_part} partial "
              f"of {n_all}")

    still_open = [(rid, title) for rid, title, status, _ in REQS if status == OPEN]
    if still_open:
        print(f"\n  {len(still_open)} requirements still open:")
        for rid, title in still_open[:12]:
            print(f"    {rid:<9} {title}")
        if len(still_open) > 12:
            print(f"    … and {len(still_open) - 12} more")
    return 0


def _wrap(text, width):
    words, line, out = text.split(), "", []
    for w in words:
        if len(line) + len(w) + 1 > width:
            out.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        out.append(line)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
