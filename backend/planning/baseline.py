r"""
The scientific control: routes planned on terrain alone, frozen.

Steps 6-8 of this project add a learned crater and boulder detector, fuse its
output into the cost surface, and claim the resulting traverses are safer. That
claim is only meaningful against a control, and a control is only a control if
nothing about it moves afterwards.

Why this has to be recorded before the detector exists
------------------------------------------------------
The comparison measures one variable: whether detected hazards were fused. If
the posting also changes between the two runs, the measured difference is a
mixture of the detector and the data, and no later analysis can separate them.
Measured at the Apollo sites, going from 473.8 m to 29.6 m moves p99 slope by a
factor of 2.7 to 5.5 — far larger than any plausible effect of a detector. A
baseline recorded at one posting and compared against a treatment at another
would be reporting the resampling and calling it a result.

So the posting is pinned here, in the record itself, and :func:`verify`
refuses a comparison whose conditions no longer match.

What is frozen
--------------
Everything that could change the answer: the region, the endpoints, the rover,
the regolith model, the algorithm set, and the source and cell size that came
back. Each case carries a SHA-256 over its conditions, so a later run can
*prove* it faced the same problem rather than asserting it.

What is deliberately not frozen is the route itself. If a code change alters a
baseline route, that is a finding — storing the geometry is how it gets
noticed rather than absorbed.
"""

from __future__ import annotations

import hashlib
import json
import platform
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..config import PROJECT_ROOT
from ..core.aoi import plan_aoi
from .service import DEFAULT_ALGORITHMS, plan_traverse

__all__ = ["BaselineCase", "CASES", "record", "load", "verify", "BASELINE_PATH"]

#: Where the frozen record lives. In the repository, not the cache: this is a
#: result, not a derived artefact, and it must survive a cache wipe.
BASELINE_PATH = PROJECT_ROOT / "docs" / "results" / "baseline_terrain_only.json"

#: The posting every baseline case is pinned to.
#:
#: Streamed LOLA at 1024 ppd is the finest validated source covering the whole
#: Moon, and its 89 m crater detection floor sits below the Robbins
#: catalogue's 1,000 m completeness limit — which is the entire reason a
#: learned detector can contribute anything. A baseline at 473.8 m would leave
#: the detector nothing to find that a CSV does not already contain, and the
#: experiment would return zero by construction.
PINNED_SOURCE = "ldem_1024"


@dataclass(frozen=True)
class BaselineCase:
    """One control traverse: a region, two endpoints, and a vehicle."""

    key: str
    label: str
    why: str
    south: float
    north: float
    west: float
    east: float
    start: tuple[float, float]
    goal: tuple[float, float]
    rover: str = "viper"
    soil: str = "nominal"

    def conditions(self) -> dict:
        """Everything that defines the problem, for hashing."""
        return {
            "key": self.key,
            "bounds": [self.south, self.north, self.west, self.east],
            "start": list(self.start), "goal": list(self.goal),
            "rover": self.rover, "soil": self.soil,
            "source": PINNED_SOURCE,
            "algorithms": list(DEFAULT_ALGORITHMS),
        }

    def fingerprint(self) -> str:
        raw = json.dumps(self.conditions(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


#: The control set.
#:
#: Five regions rather than one, because a single traverse cannot distinguish a
#: real effect from a lucky region. Three sit on ground a mission actually
#: crossed, so the control is anchored to reality as well as to itself; two are
#: chosen for terrain character — one deliberately gentle, one deliberately
#: rough — so a detector that only helps on hard ground can be seen to do so.
CASES: tuple[BaselineCase, ...] = (
    BaselineCase(
        key="apollo17_taurus_littrow",
        label="Apollo 17, Taurus-Littrow",
        why=("Ground truth: the crew drove 35.7 km here, so the terrain is "
             "known drivable. Also the site where a 473.8 m posting reports "
             "3.01 deg maximum slope on ground that holds 27.14 deg."),
        south=20.13, north=20.25, west=30.71, east=30.83,
        start=(20.16, 30.74), goal=(20.23, 30.81),
    ),
    BaselineCase(
        key="apollo15_hadley",
        label="Apollo 15, Hadley-Apennine",
        why=("Ground truth, and the roughest of the crewed sites: p99 slope "
             "28.8 deg at 29.6 m. Hadley Rille gives a real obstacle to route "
             "around rather than a statistical one."),
        south=26.08, north=26.20, west=3.58, east=3.70,
        start=(26.11, 3.61), goal=(26.18, 3.68),
    ),
    BaselineCase(
        key="luna21_lunokhod2",
        label="Luna 21 / Lunokhod 2, Le Monnier",
        why=("The longest traverse ever driven off Earth at 39 km, and a "
             "non-crewed vehicle — a different mission profile against which "
             "to check the cost model."),
        south=25.94, north=26.06, west=30.35, east=30.47,
        start=(25.97, 30.38), goal=(26.03, 30.44),
    ),
    BaselineCase(
        key="mare_smooth",
        label="Mare Tranquillitatis, smooth",
        why=("Deliberately gentle mare. A detector should change little here; "
             "if it changes a lot, it is finding things that are not there."),
        south=8.20, north=8.32, west=31.30, east=31.42,
        start=(8.23, 31.33), goal=(8.29, 31.39),
    ),
    BaselineCase(
        key="highland_rough",
        label="Southern highlands, rough",
        why=("Cratered highland terrain, the case a hazard-aware planner "
             "exists for. If fusing detections helps anywhere, here."),
        south=-43.06, north=-42.94, west=348.20, east=348.32,
        start=(-43.03, 348.23), goal=(-42.97, 348.29),
    ),
)


@dataclass
class BaselineRun:
    case: str
    fingerprint: str
    ok: bool
    reason: str = ""
    cell_m: float | None = None
    product_id: str | None = None
    certification: str | None = None
    recommended: str | None = None
    cost_s: float | None = None
    distance_m: float | None = None
    waypoints: int | None = None
    slope_p99: float | None = None
    slope_max: float | None = None
    passable_fraction: float | None = None
    route_lat: list = field(default_factory=list)
    route_lon: list = field(default_factory=list)
    algorithms: list = field(default_factory=list)
    seconds: float = 0.0


def _run(case: BaselineCase) -> BaselineRun:
    t0 = time.perf_counter()
    try:
        aoi = plan_aoi(case.south, case.north, case.west, case.east,
                       source=PINNED_SOURCE)
        res = plan_traverse(aoi, case.start, case.goal,
                            rover=case.rover, soil=case.soil)
    except Exception as e:                                   # noqa: BLE001
        return BaselineRun(case=case.key, fingerprint=case.fingerprint(),
                           ok=False, reason=f"{type(e).__name__}: {e}",
                           seconds=time.perf_counter() - t0)

    route = res.get("route")
    if route is None:
        return BaselineRun(case=case.key, fingerprint=case.fingerprint(),
                           ok=False, reason="no algorithm found a route",
                           seconds=time.perf_counter() - t0)

    t = res["traversability"]
    rec = res["recommended"]
    best = next((a for a in res["algorithms"]
                 if a.get("key") == rec.get("key")), {})
    dist = route["profile"]["distance_m"][-1]
    return BaselineRun(
        case=case.key, fingerprint=case.fingerprint(), ok=True,
        cell_m=aoi.cell_m, product_id=aoi.source.product_id,
        certification=res["certification"], recommended=rec.get("algorithm"),
        cost_s=best.get("cost_s"), distance_m=dist,
        waypoints=route["waypoints"],
        slope_p99=t["slope_deg"]["p99"], slope_max=t["slope_deg"]["max"],
        passable_fraction=t["passable_fraction"],
        # The geometry, so a later run can be compared cell by cell rather than
        # only by summary statistics.
        route_lat=route["lat"], route_lon=route["lon"],
        algorithms=[{"key": a.get("key"), "found": a["found"],
                     "cost_s": a.get("cost_s"), "cost_ratio": a.get("cost_ratio"),
                     "nodes_expanded": a.get("nodes_expanded")}
                    for a in res["algorithms"]],
        seconds=time.perf_counter() - t0,
    )


def record(path: Path = BASELINE_PATH, *, cases=CASES) -> dict:
    """Plan every control case on terrain alone and write the frozen record."""
    runs = [_run(c) for c in cases]
    doc = {
        "what": ("Terrain-only control traverses. No detected craters or "
                 "boulders are fused into the cost surface; this is the "
                 "'before' against which Steps 6-8 are measured."),
        "recorded_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pinned_source": PINNED_SOURCE,
        "algorithms": list(DEFAULT_ALGORITHMS),
        "python": platform.python_version(),
        "cases": [{**asdict(c), "start": list(c.start), "goal": list(c.goal),
                   "fingerprint": c.fingerprint()} for c in cases],
        "runs": [asdict(r) for r in runs],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc


def load(path: Path = BASELINE_PATH) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def verify(path: Path = BASELINE_PATH, *, cases=CASES) -> list[str]:
    """Problems that would make a later comparison invalid. Empty is good."""
    doc = load(path)
    if doc is None:
        return ["no baseline has been recorded"]

    problems: list[str] = []
    if doc.get("pinned_source") != PINNED_SOURCE:
        problems.append(
            f"baseline was recorded on {doc.get('pinned_source')!r} but the "
            f"pin is now {PINNED_SOURCE!r}; a comparison across postings "
            "measures the data, not the detector")

    stored = {c["key"]: c["fingerprint"] for c in doc.get("cases", [])}
    for c in cases:
        if c.key not in stored:
            problems.append(f"case {c.key!r} is not in the baseline")
        elif stored[c.key] != c.fingerprint():
            problems.append(
                f"case {c.key!r} has changed since it was recorded "
                f"({stored[c.key]} -> {c.fingerprint()}); the control no "
                "longer describes the same problem")
    for r in doc.get("runs", []):
        if not r.get("ok"):
            problems.append(f"case {r['case']!r} has no recorded route: "
                            f"{r.get('reason')}")
        elif not (r.get("cell_m") or 0) > 0:
            problems.append(f"case {r['case']!r} recorded no cell size")
    return problems


# ---------------------------------------------------------------------------
# Self-test / recorder
# ---------------------------------------------------------------------------

def _main() -> int:
    import sys

    if "--record" in sys.argv:
        print("\nRecording the terrain-only control. Each case streams "
              f"{PINNED_SOURCE} and plans with "
              f"{len(DEFAULT_ALGORITHMS)} algorithms.\n")
        doc = record()
        print(f"  {'case':<28} {'cell':>8} {'route':>9} {'cost':>10} "
              f"{'p99 slope':>10} {'time':>7}")
        print("  " + "-" * 78)
        for r in doc["runs"]:
            if not r["ok"]:
                print(f"  {r['case']:<28} FAILED  {r['reason'][:40]}")
                continue
            print(f"  {r['case']:<28} {r['cell_m']:>6.1f}m "
                  f"{r['distance_m']/1000:>7.2f}km {r['cost_s']:>9.0f}s "
                  f"{r['slope_p99']:>9.2f}° {r['seconds']:>6.0f}s")
        print(f"\n  written to {BASELINE_PATH}")

    npass = nfail = 0

    def check(name, ok, detail=""):
        nonlocal npass, nfail
        if ok:
            npass += 1
            print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
        else:
            nfail += 1
            print(f"  FAIL  {name}   {detail}")

    print("\nThe control is recorded, complete and unchanged\n")

    doc = load()
    if doc is None:
        print("  no baseline recorded yet — run with --record")
        return 0

    problems = verify()
    check("the frozen record still describes today's cases",
          not problems, "; ".join(problems[:2]) if problems else
          f"{len(CASES)} cases, fingerprints match")
    check("every case is pinned to one posting",
          all(abs((r.get("cell_m") or 0) - 29.612646898583478) < 1e-6
              for r in doc["runs"] if r["ok"]),
          f"{doc['pinned_source']} — a mixed-posting control is not a control")
    check("the detector has room to contribute at this posting",
          all((r.get("cell_m") or 1e9) * 3 < 1000 for r in doc["runs"] if r["ok"]),
          "crater floor below the Robbins catalogue's 1,000 m limit")
    check("every case produced a route",
          all(r["ok"] for r in doc["runs"]),
          f"{sum(r['ok'] for r in doc['runs'])}/{len(doc['runs'])}")
    check("routes carry their full geometry, not just summaries",
          all(len(r["route_lat"]) > 10 for r in doc["runs"] if r["ok"]),
          "so a later route can be compared cell by cell")
    check("the control is terrain-only",
          "No detected craters or boulders" in doc["what"],
          "fusing anything into this would destroy the comparison")

    print(f"\n{npass} passed, {nfail} failed")
    return 1 if nfail else 0


if __name__ == "__main__":
    raise SystemExit(_main())
