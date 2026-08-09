"""
LunarSerpent — HTTP service.

Serves the globe client and exposes the scientific layers over a small JSON API.

Design notes
------------
* Data endpoints are declared with ``def`` rather than ``async def``.  The work
  they do is CPU-bound NumPy over memory-mapped arrays; FastAPI runs sync
  handlers in a worker thread, so this keeps the event loop free without any
  explicit thread management.
* Basemap tiles are proxied rather than fetched directly by the browser.  The
  upstream WMTS service does not guarantee CORS headers, and proxying also lets
  the service cache tiles on disk and honour a byte budget.
* Every payload that carries a physical quantity also carries the provenance of
  that quantity (source, resolution, baseline), because a number without its
  scale is not a scientific result.
"""

from __future__ import annotations

import io
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import (
    API_PREFIX,
    BASEMAP_LAYERS,
    CRATER_CLASSES,
    DEFAULT_BASEMAP,
    DEFAULT_DEM,
    DEM_PRODUCTS,
    FRONTEND_DIR,
    G_MOON,
    POLAR_CYLINDRICAL_LIMIT_DEG,
    R_MOON_M,
    REFERENCE_FRAME,
    ROVER_PROFILES,
    TILE_CACHE_DIR,
    dataset_path,
)
from .core import selenographic as sg

app = FastAPI(
    title="LunarSerpent",
    description="Lunar surface analysis and rover traverse planning.",
    version="0.4.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Lazily-initialised singletons
#
# Neither the DEM nor the crater index is opened at import time: the service
# must start even when the Drive is unmounted or the index has not been built,
# reporting the gap rather than refusing to run (SRD SR-D2).
# ---------------------------------------------------------------------------

_dem = None
_dem_error: str | None = None
_index = None
_index_error: str | None = None
_names = None
_names_error: str | None = None


def get_dem_source():
    global _dem, _dem_error
    if _dem is None and _dem_error is None:
        try:
            from .core.raster import get_dem

            _dem = get_dem(DEFAULT_DEM)
        except Exception as exc:  # noqa: BLE001
            _dem_error = str(exc)
    if _dem is None:
        raise HTTPException(503, f"Elevation source unavailable: {_dem_error}")
    return _dem


def get_index():
    global _index, _index_error
    if _index is None and _index_error is None:
        try:
            from .data.catalog_robbins import load_index

            _index = load_index()
        except Exception as exc:  # noqa: BLE001
            _index_error = str(exc)
    if _index is None:
        raise HTTPException(503, f"Crater catalogue unavailable: {_index_error}")
    return _index


def get_names():
    global _names, _names_error
    if _names is None and _names_error is None:
        try:
            from .data.nomenclature import load_index

            _names = load_index()
        except Exception as exc:  # noqa: BLE001
            _names_error = str(exc)
    if _names is None:
        raise HTTPException(503, f"Nomenclature unavailable: {_names_error}")
    return _names


def _validate_latlon(lat: float, lon: float) -> tuple[float, float]:
    if not (-90.0 <= lat <= 90.0):
        raise HTTPException(422, f"latitude {lat} outside [-90, 90]")
    return lat, lon % 360.0


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


@app.get(f"{API_PREFIX}/meta/health")
def health() -> dict:
    """Component availability. Never fails — reporting a gap is the point."""
    status = {}

    try:
        dem = get_dem_source()
        status["elevation"] = {
            "ok": True,
            "product": dem.spec.product_id if hasattr(dem, "spec") else DEFAULT_DEM,
            "remote": getattr(dem, "is_remote", False),
        }
    except HTTPException as exc:
        status["elevation"] = {"ok": False, "detail": exc.detail}

    try:
        idx = get_index()
        status["craters"] = {"ok": True, "count": len(idx)}
    except HTTPException as exc:
        status["craters"] = {"ok": False, "detail": exc.detail}

    try:
        nm = get_names()
        status["nomenclature"] = {
            "ok": True, "count": len(nm),
            "named_craters": nm.meta.get("by_kind", {}).get("crater", 0),
        }
    except HTTPException as exc:
        status["nomenclature"] = {"ok": False, "detail": exc.detail}

    return {
        "service": "LunarSerpent",
        "version": app.version,
        "reference_frame": REFERENCE_FRAME,
        "moon_radius_m": R_MOON_M,
        "surface_gravity_ms2": G_MOON,
        "components": status,
    }


@app.get(f"{API_PREFIX}/meta/layers")
def layers() -> dict:
    """Basemaps and derived layers offered to the client."""
    return {
        "basemaps": [
            {
                "key": tl.key,
                "title": tl.title,
                "max_zoom": tl.max_zoom,
                "native_m_px": tl.native_m_px,
                "description": tl.description,
                "credit": tl.credit,
            }
            for tl in BASEMAP_LAYERS.values()
        ],
        "default_basemap": DEFAULT_BASEMAP,
        "offline_fallback": dataset_path(*("moon_texture", "moon_texture.jpg")) is not None,
        "crater_classes": [
            {
                "key": c.key,
                "label": c.label,
                "min_km": c.min_km,
                "max_km": None if c.max_km == float("inf") else c.max_km,
                "colour": c.colour,
                "basis": c.basis,
            }
            for c in CRATER_CLASSES
        ],
        "rovers": [
            {
                "key": r.key,
                "name": r.name,
                "nominal_speed_ms": r.nominal_speed_ms,
                "max_slope_deg": r.max_slope_deg,
                "ground_clearance_m": r.ground_clearance_m,
            }
            for r in ROVER_PROFILES.values()
        ],
        "dem_products": [
            {"key": k, "ppd": p.ppd, "scale_m_px": p.scale_m_px}
            for k, p in DEM_PRODUCTS.items()
        ],
    }


# ---------------------------------------------------------------------------
# Basemap tiles
# ---------------------------------------------------------------------------

_session = requests.Session()
_session.headers["User-Agent"] = "LunarSerpent/0.4 (capstone research)"


def _fetch_tile(layer_key: str, z: int, y: int, x: int) -> bytes | None:
    """Fetch one WMTS tile, using the on-disk cache when possible."""
    tl = BASEMAP_LAYERS[layer_key]
    cache = TILE_CACHE_DIR / layer_key / str(z) / str(y)
    fp = cache / f"{x}.{tl.ext}"
    if fp.exists():
        return fp.read_bytes()

    url = tl.url_template.format(z=z, y=y, x=x)
    try:
        r = _session.get(url, timeout=30)
    except requests.RequestException:
        return None
    if r.status_code != 200 or not r.content:
        return None

    cache.mkdir(parents=True, exist_ok=True)
    try:
        fp.write_bytes(r.content)
    except OSError:
        pass
    return r.content


@app.get(f"{API_PREFIX}/tiles/{{layer}}/{{z}}/{{y}}/{{x}}")
def tile(layer: str, z: int, y: int, x: int) -> Response:
    """Proxy a single basemap tile."""
    if layer not in BASEMAP_LAYERS:
        raise HTTPException(404, f"unknown layer '{layer}'")
    data = _fetch_tile(layer, z, y, x)
    if data is None:
        raise HTTPException(502, "upstream tile unavailable")
    return Response(
        content=data,
        media_type=f"image/{BASEMAP_LAYERS[layer].ext.replace('jpg', 'jpeg')}",
        headers={"Cache-Control": "public, max-age=604800"},
    )


@app.get(f"{API_PREFIX}/texture/{{layer}}")
def global_texture(layer: str, z: int = Query(3, ge=0, le=5)) -> Response:
    """A single equirectangular texture for the whole Moon.

    The WMTS grid at level ``z`` is ``2^(z+1)`` columns by ``2^z`` rows, which
    is exactly the 2:1 aspect an equirectangular sphere map needs — so the
    stitched mosaic maps onto the globe's UV parameterisation with no
    reprojection.  The result is cached, since it is identical for every client.
    """
    from PIL import Image

    if layer not in BASEMAP_LAYERS:
        raise HTTPException(404, f"unknown layer '{layer}'")
    tl = BASEMAP_LAYERS[layer]
    z = min(z, tl.max_zoom)

    out = TILE_CACHE_DIR / f"texture_{layer}_z{z}.jpg"
    if out.exists():
        return FileResponse(out, media_type="image/jpeg",
                            headers={"Cache-Control": "public, max-age=604800"})

    ncols, nrows = 2 ** (z + 1), 2 ** z

    probe = _fetch_tile(layer, z, 0, 0)
    if probe is None:
        raise HTTPException(502, "upstream basemap unavailable")
    tw, th = Image.open(io.BytesIO(probe)).size

    canvas = Image.new("RGB", (ncols * tw, nrows * th), (0, 0, 0))

    jobs = [(yy, xx) for yy in range(nrows) for xx in range(ncols)]
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = pool.map(lambda j: (j, _fetch_tile(layer, z, j[0], j[1])), jobs)
        for (yy, xx), blob in results:
            if not blob:
                continue
            try:
                canvas.paste(Image.open(io.BytesIO(blob)).convert("RGB"),
                             (xx * tw, yy * th))
            except Exception:  # noqa: BLE001 — a bad tile must not kill the mosaic
                continue

    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, "JPEG", quality=88, optimize=True)
    return FileResponse(out, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=604800"})


# ---------------------------------------------------------------------------
# Craters
# ---------------------------------------------------------------------------


@app.get(f"{API_PREFIX}/mosaic/{{layer}}")
def region_mosaic(
    layer: str,
    south: float = Query(..., ge=-90, le=90),
    north: float = Query(..., ge=-90, le=90),
    west: float = Query(...),
    east: float = Query(...),
    z: int = Query(6, ge=0, le=8),
    max_tiles: int = Query(320, ge=4, le=1024),
) -> Response:
    """High-resolution mosaic covering one lat/lon window.

    This is what gives the globe its detail when zoomed in.  A single global
    texture cannot: at the deepest level the whole Moon is 131 072 x 65 536
    pixels (~1.5 GB of tiles), far beyond both a WebGL texture limit and any
    sane download.  Requesting only the visible window keeps the transfer to a
    few hundred kilobytes while delivering the full 83 m/px the WAC mosaic has.

    The returned image is snapped outward to whole tile boundaries, and the
    bounds actually covered are reported in ``X-Bounds-*`` headers so the client
    can place the patch exactly rather than assuming it got what it asked for.
    """
    from PIL import Image

    if layer not in BASEMAP_LAYERS:
        raise HTTPException(404, f"unknown layer '{layer}'")
    if south >= north:
        raise HTTPException(422, "south must be less than north")

    tl = BASEMAP_LAYERS[layer]
    z = min(z, tl.max_zoom)

    # Reduce the zoom until the request fits the tile budget.  Degrading
    # resolution is the right failure mode here; refusing to draw is not.
    while z > 0:
        cols, rows = 2 ** (z + 1), 2 ** z
        x0 = math.floor(west / 360.0 * cols)
        x1 = math.floor((east - 1e-9) / 360.0 * cols)
        y0 = max(0, math.floor((90.0 - north) / 180.0 * rows))
        y1 = min(rows - 1, math.floor((90.0 - south - 1e-9) / 180.0 * rows))
        nx, ny = (x1 - x0 + 1), (y1 - y0 + 1)
        if nx * ny <= max_tiles:
            break
        z -= 1
    else:
        cols, rows = 2, 1
        x0 = x1 = y0 = y1 = 0
        nx = ny = 1

    probe = _fetch_tile(layer, z, y0, x0 % cols)
    if probe is None:
        raise HTTPException(502, "upstream basemap unavailable")
    tw, th = Image.open(io.BytesIO(probe)).size

    canvas = Image.new("RGB", (nx * tw, ny * th), (12, 12, 14))

    jobs = [(yy, xx) for yy in range(y0, y1 + 1) for xx in range(x0, x1 + 1)]
    with ThreadPoolExecutor(max_workers=16) as pool:
        # ``xx % cols`` lets a window straddle the 0/360 seam without breaking.
        fetched = pool.map(
            lambda j: (j, _fetch_tile(layer, z, j[0], j[1] % cols)), jobs
        )
        for (yy, xx), blob in fetched:
            if not blob:
                continue
            try:
                canvas.paste(
                    Image.open(io.BytesIO(blob)).convert("RGB"),
                    ((xx - x0) * tw, (yy - y0) * th),
                )
            except Exception:  # noqa: BLE001 — one bad tile must not void the patch
                continue

    buf = io.BytesIO()
    canvas.save(buf, "JPEG", quality=86, optimize=True)

    return Response(
        content=buf.getvalue(),
        media_type="image/jpeg",
        headers={
            "Cache-Control": "public, max-age=604800",
            "X-Bounds-West": f"{x0 / cols * 360.0:.9f}",
            "X-Bounds-East": f"{(x1 + 1) / cols * 360.0:.9f}",
            "X-Bounds-North": f"{90.0 - y0 / rows * 180.0:.9f}",
            "X-Bounds-South": f"{90.0 - (y1 + 1) / rows * 180.0:.9f}",
            "X-Zoom": str(z),
            "X-Tiles": str(nx * ny),
            "X-Metres-Per-Pixel": f"{2 * math.pi * R_MOON_M / (cols * tw):.2f}",
            "Access-Control-Expose-Headers":
                "X-Bounds-West,X-Bounds-East,X-Bounds-North,X-Bounds-South,"
                "X-Zoom,X-Tiles,X-Metres-Per-Pixel",
        },
    )


@app.get(f"{API_PREFIX}/craters/bbox")
def craters_bbox(
    south: float = Query(..., ge=-90, le=90),
    north: float = Query(..., ge=-90, le=90),
    west: float = 0.0,
    east: float = 360.0,
    min_diameter_km: float = Query(0.0, ge=0.0),
    limit: int = Query(2000, ge=1, le=20000),
) -> dict:
    """Craters in a bounding box, largest first.

    The index is sorted by descending diameter, so truncating at ``limit``
    returns the most *significant* craters in view rather than an arbitrary
    subset — the correct behaviour when the globe is zoomed out.
    """
    if south >= north:
        raise HTTPException(422, "south must be less than north")
    idx = get_index()
    t0 = time.perf_counter()
    hits = idx.query_bbox(south, north, west, east,
                          min_diameter_km=min_diameter_km, limit=limit)
    total = idx.count_bbox(south, north, west, east,
                           min_diameter_km=min_diameter_km)
    return {
        "count": len(hits),
        "total_matching": total,
        "truncated": total > len(hits),
        "query_ms": round((time.perf_counter() - t0) * 1000, 2),
        "source": "Robbins (2019), doi:10.1029/2018JE005592",
        "craters": [c.to_dict() for c in hits],
    }


@app.get(f"{API_PREFIX}/craters/largest")
def craters_largest(n: int = Query(200, ge=1, le=5000)) -> dict:
    idx = get_index()
    return {
        "count": n,
        "source": "Robbins (2019), doi:10.1029/2018JE005592",
        "craters": [c.to_dict() for c in idx.largest(n)],
    }


def _with_names(craters: list) -> list[dict]:
    """Attach official IAU names to measured catalogue entries.

    Robbins supplies the measurement, the gazetteer supplies the name; neither
    alone lets the interface say "Tycho, 85 km deep". Craters with no match keep
    their catalogue ID, which is the honest answer — most lunar craters have
    never been named.
    """
    out = []
    try:
        names = get_names()
    except HTTPException:
        names = None

    for c in craters:
        d = c.to_dict()
        if names is not None:
            hit = names.match_crater(c.lat, c.lon, c.diameter_km)
            if hit is not None:
                d["name"] = hit.name
                d["name_origin"] = hit.origin
                d["name_url"] = hit.url
                d["approval_year"] = hit.approval_year
        d["label"] = d.get("name") or d["id"]
        d["named"] = "name" in d
        out.append(d)
    return out


@app.get(f"{API_PREFIX}/craters/at")
def craters_at(lat: float, lon: float) -> dict:
    """Craters enclosing a point, plus the nearest catalogue centre.

    A point on the Moon typically lies inside several nested craters — a small
    one superposed on a larger one, inside an ancient basin. They are returned
    smallest-first because the smallest is the structure that governs the local
    terrain, while the largest records the oldest event.
    """
    lat, lon = _validate_latlon(lat, lon)
    idx = get_index()
    enclosing = idx.containing(lat, lon)
    nearest = idx.nearest(lat, lon)
    return {
        "query": {"lat": lat, "lon": lon},
        "enclosing": _with_names(enclosing[:10]),
        "nearest": _with_names([nearest])[0] if nearest else None,
        "source": "Robbins (2019), doi:10.1029/2018JE005592",
        "names_source": "IAU Gazetteer of Planetary Nomenclature",
    }


@app.get(f"{API_PREFIX}/craters/landmarks")
def craters_landmarks(n: int = Query(60, ge=1, le=400)) -> dict:
    """The most prominent *named* craters, largest first.

    This is the answer to "where is Tycho?" — a curated entry point into
    1.3 million anonymous catalogue rows.
    """
    names = get_names()
    feats = names.query(kinds={"crater"}, limit=n)
    return {
        "count": len(feats),
        "source": names.meta["citation"],
        "craters": [f.to_dict() for f in feats],
    }


# ---------------------------------------------------------------------------
# Named features (IAU Gazetteer)
# ---------------------------------------------------------------------------


@app.get(f"{API_PREFIX}/features/named")
def features_named(
    south: float = Query(-90.0, ge=-90, le=90),
    north: float = Query(90.0, ge=-90, le=90),
    west: float = 0.0,
    east: float = 360.0,
    min_diameter_km: float = Query(0.0, ge=0.0),
    kinds: str | None = Query(None, description="comma-separated kind filter"),
    limit: int = Query(400, ge=1, le=4000),
) -> dict:
    """Officially named features in a window, largest first.

    This is what puts real names on the globe.  Robbins supplies 1.3 million
    crater *measurements*; only these ~9 000 features carry names the IAU has
    actually approved.
    """
    idx = get_names()
    kindset = {k.strip() for k in kinds.split(",")} if kinds else None
    t0 = time.perf_counter()
    hits = idx.query(south=south, north=north, west=west, east=east,
                     min_diameter_km=min_diameter_km, kinds=kindset,
                     limit=limit)
    return {
        "count": len(hits),
        "query_ms": round((time.perf_counter() - t0) * 1000, 2),
        "source": idx.meta["citation"],
        "features": [f.to_dict() for f in hits],
    }


@app.get(f"{API_PREFIX}/discover")
def discover() -> dict:
    """Curated places worth visiting, grouped by theme.

    The gazetteer holds 9 086 names and the crater catalogue 1.3 million rows.
    Both are research assets and neither is a usable starting point, because
    nothing in the data marks Tycho as more interesting than ``Tycho ZE``.
    This endpoint supplies that missing editorial layer while keeping every
    coordinate, diameter and etymology sourced from the gazetteer itself.
    """
    from .data import discover as disc

    idx = get_names()
    cats = disc.build(idx)
    return {
        "categories": cats,
        "total": sum(c["count"] for c in cats),
        "source": idx.meta["citation"],
        "visibility_basis": (
            "Synchronous rotation places the sub-Earth point near 0° longitude; "
            f"optical libration shifts the visible limb by about ±{disc.LIBRATION_DEG:.0f}°."
        ),
    }


@app.get(f"{API_PREFIX}/meta/cesium")
def cesium_config() -> dict:
    """Configuration for the Cesium ion terrain view.

    Served rather than hard-coded in JavaScript so the token can be replaced
    through the environment without editing frontend source.
    """
    from .config import (
        CESIUM_ATTRIBUTION,
        CESIUM_ION_TOKEN,
        CESIUM_MOON_ASSET,
        CESIUM_VERSION,
    )

    return {
        "token": CESIUM_ION_TOKEN,
        "asset": CESIUM_MOON_ASSET,
        "version": CESIUM_VERSION,
        "attribution": CESIUM_ATTRIBUTION,
        "reference_frame": REFERENCE_FRAME,
        "radius_m": R_MOON_M,
    }


@app.get(f"{API_PREFIX}/discoveries")
def discoveries(category: str | None = None, status: str | None = None) -> dict:
    """Major scientific discoveries about the Moon, with provenance.

    Each entry names the mission and instrument that established it, cites the
    primary publication, and declares a confidence status — ``established``,
    ``evolving`` or ``contested``.  That last distinction is the point: several
    widely-repeated claims about the Moon are still genuinely open, and a system
    that presents them all with equal certainty is misinforming its reader.
    """
    from .data import discoveries as dx

    items = list(dx.DISCOVERIES)
    if category:
        items = [d for d in items if d.category == category]
    if status:
        items = [d for d in items if d.status == status]

    return {
        "count": len(items),
        "categories": list(dx.CATEGORIES),
        "statistics": dx.statistics(),
        "discoveries": [d.to_dict() for d in items],
    }


@app.get(f"{API_PREFIX}/missions")
def missions(
    country: str | None = None,
    kind: str | None = None,
    outcome: str | None = None,
) -> dict:
    """Every spacecraft that has reached the lunar surface.

    Covers deliberate impacts, failed landings that struck the Moon, soft
    landings, rovers, sample returns and crewed missions.  Each entry declares
    how well its coordinates are known — ``measured`` from LROC imagery of the
    hardware itself, ``reported`` by the operating agency, or ``approximate``
    where only a target region is established.  Several historic sites were
    mislocated by kilometres until LRO photographed them, so presenting all
    three tiers as equally certain would be misleading.
    """
    from .data import missions as mx

    items = list(mx.MISSIONS)
    if country:
        items = [m for m in items if m.country.casefold() == country.casefold()]
    if kind:
        items = [m for m in items if m.kind == kind]
    if outcome:
        items = [m for m in items if m.outcome == outcome]

    return {
        "count": len(items),
        "statistics": mx.statistics(),
        "countries": mx.countries(),
        "missions": [m.to_dict() for m in items],
        "coordinate_source": (
            "Wagner et al. (2017) Icarus 283, 92–103, "
            "doi:10.1016/j.icarus.2016.05.011 — LRO-measured positions of "
            "anthropogenic features; agency reports for recent missions."
        ),
    }


@app.get(f"{API_PREFIX}/missions/{{key}}")
def mission_detail(key: str) -> dict:
    """One mission in full."""
    from .data import missions as mx

    m = mx.by_key(key)
    if m is None:
        raise HTTPException(404, f"No mission '{key}'")
    out = m.to_dict()

    # Pair the landing site with the terrain it sits on, when measurable.
    if m.lat is not None:
        try:
            dem = get_dem_source()
            out["terrain"] = {
                "elevation_m": round(float(dem.elevation_at(m.lat, m.lon)), 1),
                "source": "LOLA LDEM_16 (Smith et al. 2010)",
            }
        except Exception:  # noqa: BLE001 — terrain is a bonus, not the point
            pass
    return out


@app.get(f"{API_PREFIX}/features/search")
def features_search(q: str, limit: int = Query(20, ge=1, le=100)) -> dict:
    """Name search, prefix matches first."""
    idx = get_names()
    return {
        "query": q,
        "results": [f.to_dict() for f in idx.search(q, limit=limit)],
        "source": idx.meta["citation"],
    }


@app.get(f"{API_PREFIX}/features/kinds")
def features_kinds() -> dict:
    from .data.nomenclature import KIND_STYLE

    idx = get_names()
    counts = idx.meta.get("by_kind", {})
    return {
        "kinds": [
            {"key": k, "label": v["label"], "colour": v["colour"],
             "count": counts.get(k, 0)}
            for k, v in KIND_STYLE.items() if counts.get(k, 0) > 0
        ],
        "total": len(idx),
    }


@app.get(f"{API_PREFIX}/features/analyse")
def features_analyse(
    name: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    diameter_km: float | None = None,
) -> dict:
    """Full scientific characterisation of one feature.

    Accepts either an official ``name`` or an explicit ``lat``/``lon``/
    ``diameter_km``.  Returns measured morphometry from LOLA topography beside
    the values predicted by Pike's published scaling laws, so the reader can
    judge whether the feature is fresh, degraded or infilled — rather than being
    handed a bare number with no context.
    """
    from .analysis.morphometry import analyse_crater

    feature = None
    if name:
        idx = get_names()
        feature = idx.by_name(name)
        if feature is None:
            matches = idx.search(name, limit=5)
            raise HTTPException(
                404,
                f"No IAU feature named '{name}'." +
                (f" Did you mean: {', '.join(m.name for m in matches)}?"
                 if matches else ""),
            )
        lat, lon, diameter_km = feature.lat, feature.lon, feature.diameter_km

    if lat is None or lon is None:
        raise HTTPException(422, "provide either 'name' or 'lat' and 'lon'")
    lat, lon = _validate_latlon(lat, lon)

    if not diameter_km or diameter_km <= 0:
        # Fall back to the nearest catalogued crater's diameter.
        near = get_index().nearest(lat, lon)
        if near is None:
            raise HTTPException(422, "diameter_km required and not inferable")
        diameter_km = near.diameter_km

    dem = get_dem_source()
    try:
        m = analyse_crater(dem, lat, lon, diameter_km)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    out = m.to_dict()
    if feature is not None:
        out["identity"] = feature.to_dict()
    return out


# ---------------------------------------------------------------------------
# Terrain
# ---------------------------------------------------------------------------


@app.get(f"{API_PREFIX}/terrain/point")
def terrain_point(lat: float, lon: float) -> dict:
    """Elevation and local geometry at one coordinate.

    Slope is reported together with the baseline over which it was measured.
    Slope is a scale-dependent quantity: a gradient computed over a 1.9 km cell
    is not the gradient a rover wheel experiences over 5 m, and reporting one as
    the other would be scientifically wrong (FORMULAS.md §3.2).
    """
    lat, lon = _validate_latlon(lat, lon)
    dem = get_dem_source()

    elev = float(dem.elevation_at(lat, lon))
    dx, dy = sg.cell_size_m(lat, dem.width, dem.height)

    out = {
        "lat": round(lat, 5),
        "lon": round(lon, 5),
        "elevation_m": round(elev, 2),
        "radius_m": round(R_MOON_M + elev, 2),
        "source": "LOLA LDEM_16 (Smith et al. 2010)",
        "resolution_m_px": round(dem.baseline_m, 2),
        "cell_size_m": {"east_west": round(float(dx), 2),
                        "north_south": round(float(dy), 2)},
    }

    if abs(lat) > POLAR_CYLINDRICAL_LIMIT_DEG:
        out["warning"] = (
            f"Above {POLAR_CYLINDRICAL_LIMIT_DEG}° latitude the simple-cylindrical "
            "grid degenerates (east-west cell size approaches zero). Slope and "
            "azimuth from this grid are not trustworthy here; a polar "
            "stereographic product is required."
        )
    return out


@app.get(f"{API_PREFIX}/terrain/window")
def terrain_window(
    south: float = Query(..., ge=-90, le=90),
    north: float = Query(..., ge=-90, le=90),
    west: float = 0.0,
    east: float = 360.0,
    max_cells: int = Query(400_000, ge=1000, le=2_000_000),
) -> dict:
    """Summary statistics for a rectangular region."""
    if south >= north:
        raise HTTPException(422, "south must be less than north")
    dem = get_dem_source()
    win = dem.window(south, north, west, east)
    if win.data.size > max_cells:
        raise HTTPException(
            413,
            f"region covers {win.data.size} cells, above the {max_cells} limit; "
            "request a smaller area",
        )
    return {
        "bounds": {"south": south, "north": north, "west": west, "east": east},
        "shape": list(win.shape),
        "stats": win.stats(),
        "source": "LOLA LDEM_16 (Smith et al. 2010)",
        "resolution_m_px": round(dem.baseline_m, 2),
    }


# ---------------------------------------------------------------------------
# Geodesy helper — used by the client for the measure tool
# ---------------------------------------------------------------------------


@app.get(f"{API_PREFIX}/terrain/grid")
def terrain_grid(
    south: float = Query(..., ge=-90, le=90),
    north: float = Query(..., ge=-90, le=90),
    west: float = Query(...),
    east: float = Query(...),
    width: int = Query(129, ge=8, le=513),
    height: int = Query(129, ge=8, le=513),
) -> Response:
    """Elevation resampled onto a regular lat/lon lattice.

    Returned as raw little-endian ``float32``, row-major, **north row first**
    and **west column first**, with ``width x height`` samples covering the
    requested bounds *inclusive of its edges*.

    That layout is not arbitrary: it is exactly the vertex order of a
    ``THREE.SphereGeometry`` patch built with matching segment counts, so the
    client can displace vertex *i* by sample *i* with no interpolation, no
    transposition and no off-by-one — the two grids are the same lattice.

    Raw bytes rather than JSON because a 129x129 grid is 66 KB binary against
    roughly 400 KB of decimal text, and this is fetched on every camera move.
    """
    import numpy as np
    from scipy.ndimage import map_coordinates

    if south >= north:
        raise HTTPException(422, "south must be less than north")

    dem = get_dem_source()

    # Read a slightly padded window so bilinear sampling at the edges has
    # neighbours on both sides rather than clamping.
    pad_lat = (north - south) / max(height - 1, 1)
    pad_lon = (east - west) / max(width - 1, 1)
    win = dem.window(
        max(south - pad_lat, -89.999), min(north + pad_lat, 89.999),
        west - pad_lon, east + pad_lon,
    )
    z = np.asarray(win.elevation, dtype=np.float32)

    # Target lattice, edges inclusive.
    lats = np.linspace(north, south, height, dtype=np.float64)
    lons = np.linspace(west, east, width, dtype=np.float64)

    # Map target coordinates into window pixel space.
    wlats = win.latitudes()
    wlons = win.longitudes()
    rows = np.interp(lats, wlats[::-1], np.arange(z.shape[0])[::-1])

    # Longitude needs unwrapping before interpolation when the window straddles
    # the 0/360 seam, or np.interp sees a non-monotonic axis and returns junk.
    wl = np.unwrap(np.radians(wlons)) * 180.0 / np.pi
    tl = np.asarray(lons, dtype=np.float64)
    tl = wl[0] + ((tl - wl[0] + 180.0) % 360.0 - 180.0)
    cols = np.interp(tl, wl, np.arange(z.shape[1]))

    rr, cc = np.meshgrid(rows, cols, indexing="ij")
    grid = map_coordinates(z, [rr, cc], order=1, mode="nearest").astype("<f4")

    finite = grid[np.isfinite(grid)]
    return Response(
        content=grid.tobytes(),
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "public, max-age=3600",
            "X-Width": str(width),
            "X-Height": str(height),
            "X-South": f"{south:.9f}",
            "X-North": f"{north:.9f}",
            "X-West": f"{west:.9f}",
            "X-East": f"{east:.9f}",
            "X-Min-M": f"{float(finite.min()) if finite.size else 0:.2f}",
            "X-Max-M": f"{float(finite.max()) if finite.size else 0:.2f}",
            "X-Resolution-M-Px": f"{dem.baseline_m:.2f}",
            "X-Source": "LOLA LDEM_16 (Smith et al. 2010)",
            "Access-Control-Expose-Headers":
                "X-Width,X-Height,X-South,X-North,X-West,X-East,"
                "X-Min-M,X-Max-M,X-Resolution-M-Px,X-Source",
        },
    )


@app.get(f"{API_PREFIX}/geodesy/distance")
def geodesy_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> dict:
    """Exact surface distance between two points.

    On a sphere the great circle *is* the geodesic, so this is exact rather
    than an approximation (FORMULAS.md §2.1).
    """
    d = float(sg.haversine_distance(lat1, lon1, lat2, lon2))
    return {
        "from": {"lat": lat1, "lon": lon1 % 360.0},
        "to": {"lat": lat2, "lon": lon2 % 360.0},
        "distance_m": round(d, 2),
        "distance_km": round(d / 1000.0, 4),
        "initial_bearing_deg": round(float(sg.initial_bearing(lat1, lon1, lat2, lon2)), 4),
        "method": "haversine on sphere R = 1737400 m (exact geodesic)",
    }


# ---------------------------------------------------------------------------
# Static client
# ---------------------------------------------------------------------------

def _asset_version() -> str:
    """A token that changes whenever any frontend source file changes.

    Derived from the modification times of the files the page links to, so it
    is stable across reloads and changes the instant one is edited.
    """
    import hashlib

    h = hashlib.sha1()
    for p in sorted(FRONTEND_DIR.rglob("*")):
        if p.suffix in (".css", ".js") and p.is_file():
            h.update(f"{p.name}:{p.stat().st_mtime_ns}".encode())
    return h.hexdigest()[:10]


@app.get("/")
@app.get("/index.html")
def index() -> Response:
    """Serve the page with versioned asset links.

    `Cache-Control: no-store` on the stylesheet is not sufficient on its own:
    the browser revalidates the *document* on a hard reload, but a linked
    stylesheet can still be served from cache, leaving correct code paired with
    a stale presentation. Stamping a content-derived version onto each link
    makes the URL itself change when the file changes, which no cache can
    defeat — and leaves the URL unchanged when nothing has, so caching still
    works as intended.
    """
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    v = _asset_version()
    html = re.sub(r'(href|src)="((?:css|js)/[^"?]+)"',
                  rf'\1="\2?v={v}"', html)
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate",
                 "X-Asset-Version": v},
    )


@app.middleware("http")
async def no_cache_frontend(request, call_next):
    """Serve frontend source without caching.

    The browser caches CSS and JS aggressively, and a hard reload versions only
    the document — a linked stylesheet keeps its cached copy. During development
    that produces the worst possible failure mode: the code is correct, the
    change is deployed, and the screen still shows the old behaviour, so the
    time goes into debugging something that was already fixed.

    Data responses keep their long cache lifetimes; only the source files that
    change between reloads are exempted.
    """
    response = await call_next(request)
    path = request.url.path
    if path.endswith((".js", ".css", ".html")) or path == "/":
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="client")


@app.exception_handler(404)
def not_found(request, exc):  # noqa: ANN001
    return JSONResponse({"error": "not found", "path": str(request.url.path)}, 404)
