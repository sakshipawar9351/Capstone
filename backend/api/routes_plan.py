"""
HTTP surface for region analysis and traverse planning.

Kept in its own router rather than added to ``main.py``. That module is already
1,027 lines carrying every endpoint the project has; growing it further is how a
service ends up with one file nobody wants to touch. New capability goes here,
and the existing routes can be split out later without this work having to move
again.

Where the work happens
----------------------
Validating a region is fast and its failure modes are the ones a user needs
immediately — a box too large for site tier, a latitude the data does not cover,
a source not on disk. That happens **synchronously**, so a bad request comes
back as a 422 with the reason and the fix rather than as a job that fails ten
seconds later.

Reading and analysing the region is not fast — 3.5 s for a small AOI, minutes
for a full-budget one with every planner. That goes to ``core.jobs``: the caller
gets an id immediately and polls. Deduplication there means two clients opening
the same region share one computation, and a finished region is served from
cache.

So the split is: **refuse quickly, compute slowly, never block.**
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..config import API_PREFIX, DEFAULT_RISK_AVERSION, ROVER_PROFILES
from ..core.aoi import (SITE_MAX_CELL_M, SOURCES, AOIUnavailable,
                        available_tiers, plan_aoi)
from ..core.jobs import default_queue
from ..planning.planners import ALGORITHMS
from ..planning.service import (DEFAULT_ALGORITHMS, FAST_ALGORITHMS,
                                analyse_aoi, plan_traverse)

router = APIRouter(prefix=API_PREFIX, tags=["planning"])


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class Bounds(BaseModel):
    south: float = Field(..., ge=-90, le=90)
    north: float = Field(..., ge=-90, le=90)
    west: float
    east: float
    #: Omit for the best data that covers the region — which is almost always
    #: what is wanted. Pass "survey" only to take a deliberately coarser, faster
    #: look at a region that could support better. There is no "site" demand any
    #: more: asking for detail the data cannot supply used to be an error, and a
    #: missing dataset is not a malformed request.
    tier: str | None = Field(None, pattern="^(survey|site)$")
    source: str | None = None
    #: Widen the search to validated sources that must be streamed. The globe's
    #: preview leaves this off so dragging a box stays instant; the region page
    #: turns it on, because there the caller has committed and the resolution
    #: is worth tens of seconds.
    finest: bool = False


class AnalyseRequest(Bounds):
    rover: str = "viper"
    soil: str = Field("nominal", pattern="^(nominal|weak)$")
    risk_aversion: float = Field(DEFAULT_RISK_AVERSION, ge=0.0, le=20.0)


class PlanRequest(AnalyseRequest):
    start_lat: float = Field(..., ge=-90, le=90)
    start_lon: float
    goal_lat: float = Field(..., ge=-90, le=90)
    goal_lon: float
    #: ``None`` runs the comparison set the selection rationale rests on;
    #: ``["weighted_astar"]`` returns a route in about a second.
    algorithms: list[str] | None = None
    smooth: bool = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _plan_or_422(b: Bounds):
    """Validate a region now, so the caller learns the reason immediately."""
    try:
        return plan_aoi(b.south, b.north, b.west, b.east,
                        tier=b.tier, source=b.source, finest=b.finest)
    except AOIUnavailable as e:
        # 422: the request was well-formed but this region cannot be served as
        # asked. The message carries the fix, so it must reach the client.
        raise HTTPException(status_code=422, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def _check_rover(rover: str) -> None:
    if rover not in ROVER_PROFILES:
        raise HTTPException(
            status_code=422,
            detail=f"unknown rover {rover!r}; have {sorted(ROVER_PROFILES)}")


def _check_algorithms(names: list[str] | None) -> tuple[str, ...] | None:
    if names is None:
        return None
    unknown = [n for n in names if n not in ALGORITHMS]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"unknown algorithm(s) {unknown}; have {sorted(ALGORITHMS)}")
    return tuple(names)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/aoi/preview")
def aoi_preview(
    south: float = Query(..., ge=-90, le=90),
    north: float = Query(..., ge=-90, le=90),
    west: float = Query(...),
    east: float = Query(...),
    tier: str | None = Query(None, pattern="^(survey|site)$"),
    source: str | None = Query(None),
    finest: bool = Query(False),
) -> dict:
    """What a region can support, before committing to analysing it.

    Answers in milliseconds and opens no raster. This is what a user should see
    while dragging a box: the posting they would get, how many cells that is,
    the smallest crater it could measure, and whether it could certify a
    traverse or only choose a corridor.

    ``source`` is accepted here for the same reason it is on the analysis
    routes: a client that will analyse with a named source must be able to
    preview *that* source. Previewing the default and then computing with
    another would describe a region the reader is not about to be shown.
    """
    tiers = available_tiers(south, north, west, east)
    out: dict = {
        "requested": {"south": south, "north": north, "west": west,
                      "east": east, "tier": tier, "source": source,
                      "finest": finest},
        "available_tiers": tiers,
    }
    try:
        aoi = plan_aoi(south, north, west, east, tier=tier, source=source,
                       finest=finest)
        out["aoi"] = aoi.to_dict()
        out["ok"] = True
        # The tier that came back, which may differ from any that was asked for.
        out["resolved_tier"] = aoi.tier.value
    except AOIUnavailable as e:
        # Reached only when nothing covers the region at all — a coarser answer
        # is always preferred to a refusal.
        out["ok"] = False
        out["reason"] = str(e)
    return out


@router.get("/meta/coverage")
def coverage() -> dict:
    """Where high-resolution topography exists on disk, as footprints.

    The Cesium globe draws an ion 3D Tileset whose imagery and geometry are
    baked in at 83 m; it cannot be re-textured from a local DEM without
    generating quantized-mesh terrain, which is a different project. So the
    globe's job here is not to *show* 2 m detail but to say where it is —
    a footprint a user can see, select and open, after which the region page
    renders the real thing.

    Only sources actually present are listed. A footprint drawn over data
    nobody has is an invitation to a 422.
    """
    out = []
    for src in SOURCES.values():
        if src.streamed or not src.available or src.lon_range is None:
            continue
        s0, n0 = src.lat_range
        w0, e0 = src.lon_range
        out.append({
            "key": src.key, "product_id": src.product_id,
            "cell_m": src.cell_m,
            "bounds": {"south": s0, "north": n0, "west": w0, "east": e0},
            "centre": {"lat": (s0 + n0) / 2, "lon": (w0 + e0) / 2},
            "supports_traverse": src.cell_m <= SITE_MAX_CELL_M,
            "note": src.note,
        })
    out.sort(key=lambda d: d["cell_m"])
    return {"sites": out,
            "note": ("Footprints of local high-resolution topography. The "
                     "globe shows where; the region page shows what.")}


@router.get("/aoi/sources")
def aoi_sources(
    south: float = Query(..., ge=-90, le=90),
    north: float = Query(..., ge=-90, le=90),
    west: float = Query(...),
    east: float = Query(...),
) -> dict:
    """What data exists for this region, and what each would cost.

    Coverage on the Moon is not uniform. Two products cover all of it and can
    be streamed; a few dozen cover a fraction of a percent at forty times the
    detail, and only as whole-file downloads of roughly 600 MB.

    Both halves are reported. Showing only what is free to use would hide that
    1.5 m topography exists for this exact spot, and hiding the size would make
    it look free when it is not — the decision to spend disk belongs to the
    person whose disk it is.
    """
    from ..data.trek_catalog import available_for

    return available_for(south, north, west, east)


@router.post("/aoi/analyse", status_code=202)
def submit_analysis(req: AnalyseRequest) -> dict:
    """Derive slope, roughness, slip, hazard, risk and cost for a region."""
    _check_rover(req.rover)
    aoi = _plan_or_422(req)

    key = f"analyse|{aoi.key}|{req.rover}|{req.soil}|{req.risk_aversion}"
    job = default_queue().submit(
        "analyse",
        lambda progress: analyse_aoi(aoi, rover=req.rover, soil=req.soil,
                                     risk_aversion=req.risk_aversion,
                                     progress=progress).to_dict(),
        key=key,
        meta={"aoi": aoi.key, "tier": aoi.tier.value,
              "cell_m": aoi.cell_m, "cells": aoi.cell_count},
    )
    return {"job": job.to_dict(include_result=False), "aoi": aoi.to_dict()}


@router.post("/plan", status_code=202)
def submit_plan(req: PlanRequest) -> dict:
    """Plan a traverse across a region with every requested algorithm."""
    _check_rover(req.rover)
    algorithms = _check_algorithms(req.algorithms)
    aoi = _plan_or_422(req)

    algo_key = ",".join(algorithms or DEFAULT_ALGORITHMS)
    key = (f"plan|{aoi.key}|{req.rover}|{req.soil}|{req.risk_aversion}|"
           f"{req.start_lat:.6f},{req.start_lon:.6f}|"
           f"{req.goal_lat:.6f},{req.goal_lon:.6f}|{algo_key}|{req.smooth}")

    def work(progress):
        return plan_traverse(
            aoi, (req.start_lat, req.start_lon), (req.goal_lat, req.goal_lon),
            rover=req.rover, soil=req.soil, risk_aversion=req.risk_aversion,
            algorithms=algorithms, smooth=req.smooth, progress=progress)

    job = default_queue().submit(
        "plan", work, key=key,
        meta={"aoi": aoi.key, "tier": aoi.tier.value, "cell_m": aoi.cell_m,
              "algorithms": list(algorithms or DEFAULT_ALGORITHMS)},
    )
    return {"job": job.to_dict(include_result=False), "aoi": aoi.to_dict()}


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    """Poll a job. Carries the result once it is done, the reason if it failed."""
    job = default_queue().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no job {job_id!r}")
    return job.to_dict()


@router.get("/jobs")
def list_jobs(limit: int = Query(25, ge=1, le=200)) -> dict:
    q = default_queue()
    return {
        "jobs": [j.to_dict(include_result=False) for j in q.list(limit)],
        "stats": q.stats(),
    }


@router.get("/plan/options")
def plan_options() -> dict:
    """Everything a client needs to build the planning form."""
    return {
        "algorithms": [
            {"key": k, "label": label} for k, (label, _fn) in ALGORITHMS.items()
        ],
        "default_algorithms": list(DEFAULT_ALGORITHMS),
        "fast_algorithms": list(FAST_ALGORITHMS),
        "rovers": [
            {"key": r.key, "name": r.name,
             "max_slope_deg": r.max_slope_deg,
             "tip_over_slope_deg": r.tip_over_slope_deg,
             "nominal_speed_ms": r.nominal_speed_ms}
            for r in ROVER_PROFILES.values()
        ],
        "soils": [
            {"key": "nominal", "label": "Apollo nominal (c=520 Pa, phi=42 deg)"},
            {"key": "weak", "label": "Weak / low-friction bound (c=250 Pa, phi=25 deg)"},
        ],
        "risk_aversion_default": DEFAULT_RISK_AVERSION,
        "tiers": [
            {"key": "survey", "label": "Regional survey",
             "note": "Chooses a corridor. Coarse posting; not a traverse verdict."},
            {"key": "site", "label": "Site analysis",
             "note": "Certifies a rover traverse. Needs 20 m or finer data."},
        ],
    }
