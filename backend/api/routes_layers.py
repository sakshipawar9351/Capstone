"""
Derived rasters as images — FR-1.13 and FR-1.14.

The analysis has produced slope, roughness, slip, hazard, risk and cost since
the beginning, and none of it has ever been visible. A route drawn without them
asks to be trusted; a route drawn over the cost surface that produced it can be
argued with. That is the whole difference between a demonstration and a tool.

Each layer is rendered server-side into a PNG rather than shipped as an array
for the browser to colour. A full site AOI is 2.25 M cells — 18 MB as float64
JSON, against roughly 200 KB as an 8-bit image — and the colour mapping is a
scientific choice that belongs with the data, not with whichever client happens
to be drawing it.

Colour is chosen per quantity, not by taste
-------------------------------------------
* **Hazard** uses the five class colours already defined in ``config``, so the
  map, the legend and the planner cannot disagree about what "marginal" means.
* **Slope, risk, slip** run green-amber-red, because they share one meaning:
  higher is worse. The ramp is keyed to the *rover's own limits* rather than to
  the data range, so a gentle region looks gentle instead of being stretched to
  full scale.
* **Elevation** uses a neutral relief ramp keyed to the region's own range,
  because "high" has no absolute meaning on the Moon.
* **Hillshade** is greyscale, and is the only layer that is a rendering rather
  than a measurement.

Every response carries the numeric range it was scaled over in its headers, so
a reader can always recover the value behind a colour.
"""

from __future__ import annotations

import io

import numpy as np
from fastapi import APIRouter, HTTPException, Query, Response

from ..analysis.hazard import HAZARD_CLASSES
from ..analysis.terrain import hillshade
from ..config import API_PREFIX, DEFAULT_RISK_AVERSION, ROVER_PROFILES
from ..core.aoi import AOIUnavailable, plan_aoi
from ..planning.service import analyse_aoi

router = APIRouter(prefix=API_PREFIX, tags=["layers"])

LAYERS = ("elevation", "hillshade", "slope", "roughness", "slip",
          "hazard", "risk", "cost")

#: green -> amber -> red. Shared by every "higher is worse" quantity so they can
#: be read against one another without relearning the key each time.
_RISK_RAMP = np.array([
    (53, 196, 138), (156, 204, 79), (233, 196, 106),
    (224, 122, 90), (193, 53, 43),
], dtype=np.float64)

#: Neutral relief: deep blue-grey through to pale. Deliberately not a rainbow —
#: a hue ramp invents boundaries the terrain does not have.
_RELIEF_RAMP = np.array([
    (26, 35, 51), (52, 78, 104), (110, 130, 148),
    (178, 188, 196), (238, 240, 243),
], dtype=np.float64)

#: Hillshade is the one layer rendered rather than measured, and it is grey.
_SHADE_RAMP = np.array([(0, 0, 0), (255, 255, 255)], dtype=np.float64)


def _hex(ramp: np.ndarray) -> list[str]:
    return ["#%02x%02x%02x" % tuple(int(v) for v in stop) for stop in ramp]


#: Which ramp each layer is actually drawn with. Published with the catalogue so
#: a client can print the correct key beneath each picture. Getting this from
#: the same constant the renderer uses is the point: a legend maintained
#: separately drifts, and a legend showing colours the image does not contain is
#: worse than no legend at all.
_LAYER_RAMPS = {
    "elevation": _RELIEF_RAMP, "hillshade": _SHADE_RAMP,
    "slope": _RISK_RAMP, "roughness": _RISK_RAMP, "slip": _RISK_RAMP,
    "risk": _RISK_RAMP, "cost": _RISK_RAMP,
    "hazard": None,          # categorical — its key is the class table
}


def _apply_ramp(norm: np.ndarray, ramp: np.ndarray) -> np.ndarray:
    """Map 0-1 onto a colour ramp with linear interpolation between stops."""
    n = np.clip(np.nan_to_num(norm, nan=0.0), 0.0, 1.0)
    pos = n * (len(ramp) - 1)
    lo = np.floor(pos).astype(np.int32)
    hi = np.minimum(lo + 1, len(ramp) - 1)
    f = (pos - lo)[..., None]
    return (ramp[lo] * (1 - f) + ramp[hi] * f).astype(np.uint8)


def _render(layer: str, tm, win, rover) -> tuple[np.ndarray, float, float, str]:
    """Return RGB, the low and high values it was scaled over, and the unit."""
    if layer == "elevation":
        z = win.elevation
        lo, hi = float(np.nanmin(z)), float(np.nanmax(z))
        span = max(hi - lo, 1e-9)
        return _apply_ramp((z - lo) / span, _RELIEF_RAMP), lo, hi, "m"

    if layer == "hillshade":
        h = hillshade(tm.slope_deg, tm.aspect_deg)
        g = (np.clip(np.nan_to_num(h, nan=0.0), 0, 1) * 255).astype(np.uint8)
        return np.repeat(g[..., None], 3, axis=2), 0.0, 1.0, "relative"

    if layer == "hazard":
        rgb = np.zeros((*tm.hazard.shape, 3), dtype=np.uint8)
        for h in HAZARD_CLASSES:
            c = h.colour.lstrip("#")
            rgb[tm.hazard == h.code] = [int(c[i:i + 2], 16) for i in (0, 2, 4)]
        return rgb, 0.0, float(len(HAZARD_CLASSES) - 1), "class"

    if layer == "slope":
        # Scaled to the rover's tip-over limit, not to the data. A region whose
        # steepest cell is 4 deg should look flat, not fully saturated.
        hi = float(rover.tip_over_slope_deg)
        return _apply_ramp(tm.slope_deg / hi, _RISK_RAMP), 0.0, hi, "deg"

    if layer == "roughness":
        hi = float(rover.ground_clearance_m * 8.0)
        return _apply_ramp(tm.roughness_m / hi, _RISK_RAMP), 0.0, hi, "m"

    if layer == "slip":
        return _apply_ramp(tm.slip / 0.6, _RISK_RAMP), 0.0, 0.6, "fraction"

    if layer == "risk":
        return _apply_ramp(tm.risk, _RISK_RAMP), 0.0, 1.0, "0-1"

    # cost — log-scaled, because risk multiplies it and a linear ramp then
    # spends its whole range on a few impassable-adjacent cells.
    c = tm.cost_s.copy()
    finite = np.isfinite(c)
    if not finite.any():
        raise HTTPException(422, "the whole region is impassable to this rover")
    lo, hi = float(c[finite].min()), float(c[finite].max())
    lg = np.log(np.clip(c, lo, hi)) if hi > lo else np.zeros_like(c)
    span = max(np.log(hi) - np.log(lo), 1e-9) if hi > lo else 1.0
    rgb = _apply_ramp((lg - np.log(lo)) / span, _RISK_RAMP)
    # Impassable is not "very expensive" — it is a different kind of answer, so
    # it gets the hazard palette's own impassable colour rather than the top of
    # a continuous ramp.
    imp = HAZARD_CLASSES[-1].colour.lstrip("#")
    rgb[~finite] = [int(imp[i:i + 2], 16) for i in (0, 2, 4)]
    return rgb, lo, hi, "s/cell"


@router.get("/aoi/layer")
def aoi_layer(
    south: float = Query(..., ge=-90, le=90),
    north: float = Query(..., ge=-90, le=90),
    west: float = Query(...),
    east: float = Query(...),
    layer: str = Query("hazard"),
    rover: str = Query("viper"),
    soil: str = Query("nominal", pattern="^(nominal|weak)$"),
    risk_aversion: float = Query(DEFAULT_RISK_AVERSION, ge=0.0, le=20.0),
    source: str | None = Query(None),
    finest: bool = Query(False),
) -> Response:
    """One derived layer of a region, as a PNG."""
    if layer not in LAYERS:
        raise HTTPException(422, f"unknown layer {layer!r}; have {list(LAYERS)}")
    if rover not in ROVER_PROFILES:
        raise HTTPException(422, f"unknown rover {rover!r}")

    try:
        aoi = plan_aoi(south, north, west, east, source=source, finest=finest)
    except AOIUnavailable as e:
        raise HTTPException(422, str(e)) from e

    ana = analyse_aoi(aoi, rover=rover, soil=soil, risk_aversion=risk_aversion)
    rgb, lo, hi, unit = _render(layer, ana.tmap, ana.window, ROVER_PROFILES[rover])

    # Cells with no elevation are not zero-valued terrain; they are unknown, and
    # colouring them like data would invent ground that was never measured.
    if layer != "hazard":
        rgb[~ana.tmap.valid] = (20, 22, 26)

    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(rgb, mode="RGB").save(buf, format="PNG", optimize=True)

    return Response(
        content=buf.getvalue(), media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=600",
            "X-Layer": layer,
            "X-Range-Low": f"{lo:.6g}",
            "X-Range-High": f"{hi:.6g}",
            "X-Unit": unit,
            "X-Cell-M": f"{aoi.cell_m:.3f}",
            "X-Shape": f"{aoi.rows}x{aoi.cols}",
            "X-Source": aoi.source.product_id,
            "X-Bounds": f"{aoi.south},{aoi.north},{aoi.west},{aoi.east}",
        },
    )


_NOTES = {
    "elevation": "Metres above the 1737.4 km sphere, scaled to this region.",
    "hillshade": "Horn slope/aspect lit from 315 deg. A rendering, not a measurement.",
    "slope": "Scaled to the rover's tip-over limit, not to the data range.",
    "roughness": ("Detrended: the residual about the best-fit plane, so a smooth "
                  "ramp reads as smooth."),
    "slip": ("From the Bekker/Janosi-Hanamoto model, scaled to the 60 % abort "
             "threshold."),
    "hazard": "Worse of the geometric and traction verdicts.",
    "risk": ("1-(1-r_grade)(1-r_rough); correlated terms reduced by max, not "
             "multiplied."),
    "cost": ("Seconds per cell, log-scaled. Impassable shown in the hazard "
             "palette."),
}

_LABELS = {"elevation": "Elevation", "hillshade": "Hillshade", "slope": "Slope",
           "roughness": "Roughness", "slip": "Wheel slip",
           "hazard": "Hazard class", "risk": "Risk", "cost": "Cost surface"}


@router.get("/aoi/layers")
def layer_catalogue() -> dict:
    """What can be rendered, and how each is coloured.

    The ramp travels with each layer rather than being published once as a
    house style, because they are not all drawn the same way: elevation uses a
    neutral relief ramp, hillshade is grey, and hazard has no ramp at all. A
    client that printed one key under every picture would be captioning three
    of the eight with colours that never appear in them.
    """
    return {
        "layers": [
            {"key": k, "label": _LABELS[k], "note": _NOTES[k],
             "ramp": None if _LAYER_RAMPS[k] is None else _hex(_LAYER_RAMPS[k]),
             "categorical": _LAYER_RAMPS[k] is None}
            for k in LAYERS
        ],
        "hazard_classes": [
            {"key": h.key, "label": h.label, "colour": h.colour, "meaning": h.meaning}
            for h in HAZARD_CLASSES
        ],
        "risk_ramp": _hex(_RISK_RAMP),
    }
