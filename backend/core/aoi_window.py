"""
Reading an AOI into a square-celled raster, anywhere on the Moon.

``aoi.py`` decides *what* region to analyse and refuses what the data cannot
support. This module does the I/O — and one transformation that everything
downstream depends on.

Why resample at all
-------------------
The stored products are projected for global convenience, not for the region in
hand. Simple-cylindrical cells shrink east-west as cos(phi), so at 60 deg a cell
is half as wide as it is tall and near a pole it collapses altogether; polar
stereographic is square near its own pole and unusable elsewhere. Feeding either
straight into the analysis breaks the assumptions the whole chain rests on: that
a slope is rise over run, that a diagonal step is sqrt(2) cells, that one number
describes the size of a cell.

So each AOI is resampled onto a grid in an azimuthal equidistant projection
centred on itself (``projection.py``). The result is square cells of a known
size, identical in behaviour whether the region sits on the equator, at 60 deg,
or on the pole itself — and whether the bytes came from a cylindrical or a
stereographic product. One code path, one geometry, the whole Moon selectable.

The cost is a resampling step and a small, bounded distortion, both reported:
``scale_error`` states the worst tangential stretch across the region, which is
0.0006 % for a site AOI and 2.8 % across a 700 km survey.

Sampling
--------
Bilinear, because nearest-neighbour on a resampled DEM produces stair-steps that
the slope operator would faithfully report as terrain that is not there. Cells
whose source is missing stay ``NaN`` and are treated as impassable downstream
rather than interpolated over.
"""

from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..config import CACHE_DIR, MAX_AOI_CELLS, dataset_path
from . import selenographic as sel
from .aoi import AOI
from .polar import open_polar
from .projection import LocalProjection, max_scale_error
from .raster import get_dem

__all__ = ["AOIWindow", "read_aoi", "cache_stats", "POLAR_SOUTH_FILES"]

POLAR_SOUTH_FILES = ("polar", "dem", "ldem_875s_10m_float")

#: Rows resampled per pass, to bound peak memory on a full-budget AOI.
_BLOCK_ROWS = 256

#: Source cells of margin read around the region, so bilinear sampling at the
#: edge always has its four neighbours.
_MARGIN = 4

_BUDGET_SLACK = 1.15

#: One lock per window identity, so concurrent readers of the same region
#: collapse into a single build instead of racing.
#:
#: The region page opens eight layer requests, a mesh and an analysis at once.
#: On a cold streamed region every one of them would otherwise stream the same
#: bytes from PDS independently — 45 s each, ten times the traffic, for one
#: answer. With the lock the first builds and caches while the rest wait and
#: then hit the cache. It also keeps the project a considerate client of a
#: shared public archive, which matters: hammering PDS across four scripts is
#: exactly what got these requests refused earlier.
_build_locks: dict[str, threading.Lock] = {}
_build_locks_guard = threading.Lock()


def _build_lock(key: str) -> threading.Lock:
    with _build_locks_guard:
        lk = _build_locks.get(key)
        if lk is None:
            lk = _build_locks[key] = threading.Lock()
        return lk


def _guard_budget(rows: int, cols: int, aoi: AOI) -> None:
    """Enforce the absolute cell budget at the point of allocation.

    ``plan_aoi`` already caps a region, so a properly planned AOI never trips
    this. It exists because the budget must be enforced where memory is
    actually taken, not only where it is promised: an AOI constructed by hand,
    replayed from an old cache entry, or built by a future code path that
    forgets the cap would otherwise allocate whatever it liked.

    Deliberately *not* measured against the AOI's own declared size — that
    would be circular, since the declaration is what gets allocated.
    """
    cells = rows * cols
    allowed = int(MAX_AOI_CELLS * _BUDGET_SLACK)
    if cells > allowed:
        raise ValueError(
            f"Reading this AOI would allocate {cells:,} cells, past the "
            f"{allowed:,} authorised ({MAX_AOI_CELLS:,} budget + slack). "
            f"The region declares {aoi.rows}x{aoi.cols}; refusing rather than "
            "allocating.")


@dataclass
class AOIWindow:
    """An AOI's elevation on a local square grid, plus the mapping back."""

    aoi: AOI
    elevation: np.ndarray          # (rows, cols) float64, metres; NaN where absent
    cell_m: float                  # square, exact by construction
    projection: LocalProjection
    product_id: str
    source_kind: str               # projection the bytes came from
    scale_error: float             # worst tangential stretch across the region
    covered: float                 # fraction of cells the source could supply

    @property
    def shape(self) -> tuple[int, int]:
        return self.elevation.shape

    # -- coordinates -----------------------------------------------------

    def _xy(self, row, col):
        rows, cols = self.shape
        x = (np.asarray(col, dtype=np.float64) - (cols - 1) / 2.0) * self.cell_m
        y = ((rows - 1) / 2.0 - np.asarray(row, dtype=np.float64)) * self.cell_m
        return x, y

    def latlon_of(self, row, col):
        lat, lon = self.projection.inverse(*self._xy(row, col))
        return float(lat), float(lon)

    def rowcol_of(self, lat: float, lon: float):
        x, y = self.projection.forward(lat, lon)
        rows, cols = self.shape
        col = int(round(float(x) / self.cell_m + (cols - 1) / 2.0))
        row = int(round((rows - 1) / 2.0 - float(y) / self.cell_m))
        if 0 <= row < rows and 0 <= col < cols:
            return row, col
        return None

    def contains(self, lat: float, lon: float) -> bool:
        return self.rowcol_of(lat, lon) is not None

    # -- reporting -------------------------------------------------------

    def stats(self) -> dict:
        e = self.elevation[np.isfinite(self.elevation)]
        base = {
            "shape": list(self.shape),
            "cell_m": round(self.cell_m, 3),
            "product_id": self.product_id,
            "source_kind": self.source_kind,
            "resampled_to": "azimuthal equidistant, centred on the AOI",
            "centre": {"lat": round(self.projection.lat0, 6),
                       "lon": round(self.projection.lon0, 6)},
            "scale_error_pct": round(self.scale_error * 100, 5),
            "covered_fraction": round(self.covered, 5),
        }
        if e.size == 0:
            return {**base, "valid": 0}
        return {
            **base,
            "valid": int(e.size),
            "valid_fraction": round(float(e.size / self.elevation.size), 5),
            "min_m": round(float(e.min()), 2),
            "max_m": round(float(e.max()), 2),
            "mean_m": round(float(e.mean()), 2),
            "relief_m": round(float(e.max() - e.min()), 2),
        }


# ---------------------------------------------------------------------------
# Source adapters — lat/lon to fractional source indices, and a block reader
# ---------------------------------------------------------------------------

class _PolarSource:
    kind = "polar_stereographic"

    def __init__(self):
        img = dataset_path(*(POLAR_SOUTH_FILES[:-1]
                             + (POLAR_SOUTH_FILES[-1] + ".img",)))
        lbl = dataset_path(*(POLAR_SOUTH_FILES[:-1]
                             + (POLAR_SOUTH_FILES[-1] + ".lbl",)))
        if img is None or lbl is None:
            raise FileNotFoundError(
                "The 10 m south polar DEM is not present. Site-tier analysis "
                "needs it; fetch with scripts/fetch_polar.py --download.")
        self.dem = open_polar(img, lbl)
        self.grid = self.dem.grid
        self.height, self.width = self.grid.height, self.grid.width
        self.product_id = self.dem.meta["product_id"]
        self.wraps = False

    def rowcol(self, lat, lon):
        return self.grid.latlon_to_rowcol(lat, lon)

    def read(self, r0, r1, c0, c1) -> np.ndarray:
        raw = np.array(self.dem._data[r0:r1, c0:c1])
        out = self.dem._to_metres(raw)
        out[raw < -1e30] = np.nan            # LOLA's gap sentinel
        return out


class _CylindricalSource:
    kind = "simple_cylindrical"

    def __init__(self, key: str):
        self.src = get_dem(key)
        self.width, self.height = self.src.width, self.src.height
        self.product_id = self.src.spec.product_id
        self.wraps = True                    # longitude is periodic

    def rowcol(self, lat, lon):
        return sel.latlon_to_rowcol(lat, lon, self.width, self.height)

    def read(self, r0, r1, c0, c1) -> np.ndarray:
        r0, r1 = max(0, r0), min(self.height, r1)
        cols = np.arange(c0, c1) % self.width          # seam-safe
        if cols.size == 0 or r1 <= r0:
            return np.zeros((0, 0), dtype=np.float64)
        if cols[0] <= cols[-1]:
            dn = self.src._read(r0, r1 - r0, int(cols[0]), cols.size)
        else:                                          # the block spans 0/360
            split = int(np.argmax(np.diff(cols) < 0)) + 1
            left = self.src._read(r0, r1 - r0, int(cols[0]), split)
            right = self.src._read(r0, r1 - r0, 0, cols.size - split)
            dn = np.hstack([left, right])
        return np.asarray(self.src.spec.to_metres(dn), dtype=np.float64)


class _NACDtmSource:
    """An LROC NAC stereo DTM strip, presented like any other source.

    Bounded rather than global, so `wraps` is False: a region that runs off the
    edge gets NaN there instead of silently sampling the far side of the Moon.
    """

    kind = "nac_dtm"

    def __init__(self, spec):
        from .nac_dtm import open_nac_dtm

        path = dataset_path(*spec.files)
        if path is None:
            raise FileNotFoundError(
                f"{spec.product_id} is not on disk. It is a 146 MB LROC "
                "product; fetch it before selecting this source.")
        self.dtm = open_nac_dtm(path)
        self.height, self.width = self.dtm.shape
        self.product_id = self.dtm.product_id
        self.wraps = False

    def rowcol(self, lat, lon):
        return self.dtm.latlon_to_rowcol(lat, lon)

    def read(self, r0, r1, c0, c1):
        return self.dtm.read(r0, r1, c0, c1)


class _TiledRemoteSource:
    """A tiled archive presented as one virtual global grid.

    ``ldem_1024`` is 144 separate 900 MB files. Rather than teach the resampler
    about tiles, this pretends to be a single 368640 x 184320 raster: row and
    column addressing is the ordinary cylindrical mapping at the product's
    pixels-per-degree, and :meth:`read` works out which tiles a block spans,
    pulls the needed byte ranges from each, and stitches the result.

    So the AOI machinery above is unchanged — it cannot tell a tiled remote
    product from a local file, which is the point.
    """

    kind = "simple_cylindrical"

    def __init__(self, spec):
        from .raster import RasterSpec, _RemoteRaster

        self.scheme = spec.tiles
        self.product_id = spec.product_id
        self.width = 360 * self.scheme.ppd
        self.height = 180 * self.scheme.ppd
        self.wraps = True
        self._RasterSpec = RasterSpec
        self._Remote = _RemoteRaster
        self._readers: dict[str, object] = {}

    def rowcol(self, lat, lon):
        """Grid indices for a coordinate, with the product's own registration
        correction applied.

        ``ldem_1024`` sits 3.47 cells west of the final LOLA GDR — measured by
        exact 16x16 nesting against LDEM_64, and traced to the archive rather
        than to this reader. Correcting here rather than in :meth:`read` is
        deliberate: this is the one place a coordinate becomes an index, so
        every caller gets the corrected answer, while ``read`` stays a literal
        "give me these cells" primitive that the validation test can use to
        re-measure the offset independently of the correction.
        """
        row, col = sel.latlon_to_rowcol(lat, lon, self.width, self.height)
        return row, col + self.scheme.col_offset_cells

    def _reader(self, lat: float, lon: float):
        """One range-reading client per tile, kept for the session."""
        name = self.scheme.tile_name(lat, lon)
        r = self._readers.get(name)
        if r is None:
            s = self.scheme
            spec = self._RasterSpec(
                product_id=name.upper(), width=s.tile_cols, height=s.tile_rows,
                dtype=s.dtype, scaling_factor=s.scaling_factor,
                offset=s.offset_m,
            )
            r = self._Remote(self.scheme.url(lat, lon), spec)
            self._readers[name] = r
        return r

    def read(self, r0, r1, c0, c1) -> np.ndarray:
        s = self.scheme
        r0, r1 = max(0, r0), min(self.height, r1)
        if r1 <= r0 or c1 <= c0:
            return np.zeros((0, 0), dtype=np.float64)

        out = np.full((r1 - r0, c1 - c0), np.nan, dtype=np.float64)
        tile_r, tile_c = s.tile_rows, s.tile_cols

        # Walk the tiles the requested block touches. Columns are taken modulo
        # the grid width so a block spanning the 0/360 seam is not a special
        # case — it simply lands in the tile on the other side.
        rr = r0
        while rr < r1:
            lat = 90.0 - (rr + 0.5) / s.ppd
            band_r0 = (rr // tile_r) * tile_r
            r_end = min(r1, band_r0 + tile_r)

            cc = c0
            while cc < c1:
                gcol = cc % self.width
                lon = (gcol + 0.5) / s.ppd
                band_c0 = (gcol // tile_c) * tile_c
                take = min(c1 - cc, band_c0 + tile_c - gcol)

                dn = self._reader(lat, lon).read_block(
                    rr - band_r0, r_end - rr, gcol - band_c0, take)
                out[rr - r0:r_end - r0, cc - c0:cc - c0 + take] = (
                    np.asarray(dn, dtype=np.float64) * s.scaling_factor + s.offset_m)
                cc += take
            rr = r_end
        return out


def _open_source(aoi: AOI):
    if aoi.source.kind == "nac_dtm":
        return _NACDtmSource(aoi.source)
    if aoi.source.polar:
        return _PolarSource()
    if aoi.source.streamed:
        return _TiledRemoteSource(aoi.source)
    return _CylindricalSource(aoi.source.key)


# ---------------------------------------------------------------------------
# Resampling
# ---------------------------------------------------------------------------

def _bilinear(block: np.ndarray, rows: np.ndarray, cols: np.ndarray) -> np.ndarray:
    """Sample ``block`` at fractional indices, NaN outside it."""
    h, w = block.shape
    r0 = np.floor(rows).astype(np.int64)
    c0 = np.floor(cols).astype(np.int64)
    fr = rows - r0
    fc = cols - c0

    ok = (r0 >= 0) & (c0 >= 0) & (r0 + 1 < h) & (c0 + 1 < w)
    r0c = np.clip(r0, 0, max(h - 2, 0))
    c0c = np.clip(c0, 0, max(w - 2, 0))

    v00 = block[r0c, c0c]
    v01 = block[r0c, c0c + 1]
    v10 = block[r0c + 1, c0c]
    v11 = block[r0c + 1, c0c + 1]
    top = v00 * (1 - fc) + v01 * fc
    bot = v10 * (1 - fc) + v11 * fc
    out = top * (1 - fr) + bot * fr
    return np.where(ok, out, np.nan)


# ---------------------------------------------------------------------------
# Window cache
#
# Caches the *resampled answer*, not the source. A 15 km AOI at 30 m is about
# 1 MB as float32, against 900 MB for the tile it came from — so keeping the
# result costs roughly a thousandth of keeping the input, and a region already
# looked at reopens instantly instead of being streamed again.
#
# Only slow reads are cached. A local memmap is already fast enough that
# storing its output would spend disk to save nothing; a streamed region is
# seconds to minutes, and that is worth a megabyte.
# ---------------------------------------------------------------------------

_CACHE_DIR = CACHE_DIR / "aoi"
_CACHE_MAX_BYTES = 256 * 1024 * 1024
#: Reads faster than this are not worth storing.
_CACHE_MIN_SECONDS = 1.5


def _cache_files(key: str, halo: int = 0) -> tuple[Path, Path]:
    """Cache paths for a window.

    The halo is part of the identity, not a detail. A haloed window is a
    genuinely different array — larger by two cells on each side — so keying
    without it either collides or, as happened here, quietly never matches.

    This was a real defect rather than a missed optimisation. The cache was
    consulted only when ``halo == 0``, and ``analyse_aoi`` always reads with
    ``halo=1``, so the one caller that does the expensive work never hit it.
    With a local product that cost a second nobody noticed; with a streamed
    one it cost 45 s *per layer*, and the region page asks for eight.
    """
    suffix = f"{key}" if halo == 0 else f"{key}_h{halo}"
    return _CACHE_DIR / f"{suffix}.npy", _CACHE_DIR / f"{suffix}.json"


def _cache_load(aoi: AOI, halo: int = 0) -> AOIWindow | None:
    npy, meta = _cache_files(aoi.key, halo)
    if not (npy.exists() and meta.exists()):
        return None
    try:
        m = json.loads(meta.read_text(encoding="utf-8"))
        elev = np.load(npy).astype(np.float64)
        if list(elev.shape) != [aoi.rows + 2 * halo, aoi.cols + 2 * halo]:
            return None            # the plan changed under a stale entry
        npy.touch()                # mtime is the LRU clock
        lat0, lon0 = aoi.centre
        return AOIWindow(
            aoi=aoi, elevation=elev, cell_m=float(m["cell_m"]),
            projection=LocalProjection(lat0, lon0),
            product_id=m["product_id"], source_kind=m["source_kind"],
            scale_error=float(m["scale_error"]), covered=float(m["covered"]),
        )
    except Exception:              # noqa: BLE001 - a bad entry is not an error
        return None


def _cache_save(win: AOIWindow, seconds: float, halo: int = 0) -> None:
    if seconds < _CACHE_MIN_SECONDS:
        return
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        npy, meta = _cache_files(win.aoi.key, halo)
        # float32 halves the file and still resolves elevation to under a
        # millimetre over the Moon's +/-10 km range.
        np.save(npy, win.elevation.astype(np.float32))
        meta.write_text(json.dumps({
            "cell_m": win.cell_m, "product_id": win.product_id,
            "source_kind": win.source_kind, "scale_error": win.scale_error,
            "covered": win.covered, "seconds_to_build": round(seconds, 2),
            "bounds": [win.aoi.south, win.aoi.north, win.aoi.west, win.aoi.east],
        }), encoding="utf-8")
        _cache_evict()
    except Exception:              # noqa: BLE001 - caching must never fail a read
        pass


def _cache_evict() -> None:
    """Drop least-recently-used entries once over budget."""
    files = sorted(_CACHE_DIR.glob("*.npy"), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in files)
    while total > _CACHE_MAX_BYTES and files:
        victim = files.pop(0)
        total -= victim.stat().st_size
        victim.unlink(missing_ok=True)
        victim.with_suffix(".json").unlink(missing_ok=True)


def cache_stats() -> dict:
    if not _CACHE_DIR.exists():
        return {"entries": 0, "bytes": 0, "cap_bytes": _CACHE_MAX_BYTES}
    files = list(_CACHE_DIR.glob("*.npy"))
    return {
        "entries": len(files),
        "bytes": sum(p.stat().st_size for p in files),
        "cap_bytes": _CACHE_MAX_BYTES,
    }


def read_aoi(aoi: AOI, *, use_cache: bool = True, halo: int = 0) -> AOIWindow:
    """Cut an AOI out of its source and resample it onto a local square grid.

    ``halo`` adds a margin of extra cells on every side, keeping the centre
    fixed. Differentiation needs it: a 3x3 operator at the edge of a window has
    no outside neighbour, so ``mode="nearest"`` duplicates the border column and
    the measured gradient comes out halved. Computing on a haloed window and
    trimming afterwards gives the true slope right to the region's own edge.
    """
    if use_cache:
        hit = _cache_load(aoi, halo)
        if hit is not None:
            return hit
        # Serialise identical builds. Re-check the cache inside the lock: the
        # thread that held it before us has just filled it, and the whole point
        # is that the others read rather than repeat the work.
        with _build_lock(f"{aoi.key}_h{halo}"):
            hit = _cache_load(aoi, halo)
            if hit is not None:
                return hit
            return _build_window(aoi, halo, use_cache)
    return _build_window(aoi, halo, use_cache)


def _build_window(aoi: AOI, halo: int, use_cache: bool) -> AOIWindow:
    """Actually cut and resample the region. Callers go through `read_aoi`."""
    t_start = time.perf_counter()
    rows, cols = aoi.rows + 2 * halo, aoi.cols + 2 * halo
    _guard_budget(rows, cols, aoi)

    lat0, lon0 = aoi.centre
    proj = LocalProjection(lat0, lon0)
    cell = aoi.cell_m
    src = _open_source(aoi)

    # Target grid coordinates, north-up and west-left.
    xs = (np.arange(cols, dtype=np.float64) - (cols - 1) / 2.0) * cell
    ys = ((rows - 1) / 2.0 - np.arange(rows, dtype=np.float64)) * cell

    # One coarse pass to find which part of the source is needed, so the block
    # is read once rather than per target block.
    cr = np.linspace(0, rows - 1, min(rows, 64)).astype(np.int64)
    cc = np.linspace(0, cols - 1, min(cols, 64)).astype(np.int64)
    gx, gy = np.meshgrid(xs[cc], ys[cr])
    plat, plon = proj.inverse(gx, gy)
    prow, pcol = src.rowcol(plat, plon)
    r0 = int(math.floor(np.nanmin(prow))) - _MARGIN
    r1 = int(math.ceil(np.nanmax(prow))) + _MARGIN
    c0 = int(math.floor(np.nanmin(pcol))) - _MARGIN
    c1 = int(math.ceil(np.nanmax(pcol))) + _MARGIN
    if not src.wraps:
        r0, c0 = max(0, r0), max(0, c0)
        r1, c1 = min(src.height, r1), min(src.width, c1)
    else:
        r0, r1 = max(0, r0), min(src.height, r1)
    if r1 <= r0 or c1 <= c0:
        raise ValueError("the AOI falls outside the source grid")

    block = src.read(r0, r1, c0, c1)
    if block.size == 0:
        raise ValueError("the source supplied no data for this AOI")

    out = np.empty((rows, cols), dtype=np.float64)
    for b0 in range(0, rows, _BLOCK_ROWS):
        b1 = min(rows, b0 + _BLOCK_ROWS)
        gx, gy = np.meshgrid(xs, ys[b0:b1])
        la, lo = proj.inverse(gx, gy)
        sr, sc = src.rowcol(la, lo)
        if src.wraps:
            # Unwrap columns onto the block's own frame, seam included.
            sc = (np.asarray(sc) - c0) % src.width
        else:
            sc = np.asarray(sc) - c0
        out[b0:b1] = _bilinear(block, np.asarray(sr) - r0, sc)

    covered = float(np.isfinite(out).mean())
    if covered == 0.0:
        # An all-NaN window is not a result. It meant the request landed
        # somewhere the source has nothing, and returning it silently let a
        # malformed box produce a full analysis of no data at all.
        raise ValueError(
            f"{src.product_id} supplied no data anywhere in this region "
            f"({aoi.south:.3f}..{aoi.north:.3f} lat, {aoi.west:.3f}.."
            f"{aoi.east:.3f} lon). Check the bounds, or choose a source that "
            "covers it.")
    half_diag = 0.5 * math.hypot(rows * cell, cols * cell)

    win = AOIWindow(
        aoi=aoi, elevation=out, cell_m=float(cell), projection=proj,
        product_id=src.product_id, source_kind=src.kind,
        scale_error=max_scale_error(half_diag), covered=covered,
    )
    if use_cache:
        _cache_save(win, time.perf_counter() - t_start, halo)
    return win


def trim_halo(arr: np.ndarray, halo: int) -> np.ndarray:
    """Drop the margin a haloed window was computed with."""
    return arr if halo <= 0 else arr[halo:-halo, halo:-halo]


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def _self_test() -> int:
    from .aoi import Tier, plan_aoi

    npass = nfail = 0

    def check(name, ok, detail=""):
        nonlocal npass, nfail
        if ok:
            npass += 1
            print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
        else:
            nfail += 1
            print(f"  FAIL  {name}   {detail}")

    print("\nAny region on the Moon can be read\n")
    sites = [
        ("Mare Imbrium",     32.0, 33.0, -18.0, -17.0),
        ("equator",          -0.5,  0.5, 100.0, 101.0),
        ("Tycho",           -44.0, -43.0, -11.5, -10.5),
        ("far side",         10.0, 11.0, 180.0, 181.0),
        ("high north 80N",   79.5, 80.5,  40.0,  41.0),
    ]
    for name, s, n, w, e in sites:
        aoi = plan_aoi(s, n, w, e, tier=Tier.SURVEY)
        win = read_aoi(aoi)
        st = win.stats()
        ok = st.get("valid_fraction", 0) > 0.99
        check(f"{name:<16} {st['shape']} @ {st['cell_m']:.0f} m",
              ok, f"relief {st.get('relief_m', 0):.0f} m, "
                  f"scale err {st['scale_error_pct']:.4f}%")

    print("\nCells are square everywhere, which is the point\n")
    for name, s, n, w, e in [("equator", -0.5, 0.5, 100.0, 101.0),
                             ("60 north", 59.5, 60.5, 20.0, 21.0),
                             ("south pole", -89.9, -89.3, 0.0, 90.0)]:
        aoi = plan_aoi(s, n, w, e, tier=Tier.SURVEY)
        win = read_aoi(aoi)
        # A step east and a step north must be the same ground distance.
        la0, lo0 = win.latlon_of(win.shape[0] // 2, win.shape[1] // 2)
        la_e, lo_e = win.latlon_of(win.shape[0] // 2, win.shape[1] // 2 + 1)
        la_n, lo_n = win.latlon_of(win.shape[0] // 2 - 1, win.shape[1] // 2)
        d_e = float(sel.haversine_distance(la0, lo0, la_e, lo_e))
        d_n = float(sel.haversine_distance(la0, lo0, la_n, lo_n))
        check(f"{name:<12} one cell east == one cell north",
              abs(d_e - d_n) / win.cell_m < 0.01,
              f"east {d_e:.1f} m, north {d_n:.1f} m, cell {win.cell_m:.1f} m")

    print("\nCoordinates round-trip\n")
    aoi = plan_aoi(-89.50, -89.42, 218.0, 226.0, tier=Tier.SITE)
    win = read_aoi(aoi)
    rows, cols = win.shape
    worst = 0
    for r, c in [(0, 0), (0, cols-1), (rows-1, 0), (rows-1, cols-1),
                 (rows//2, cols//2), (rows//3, cols//4)]:
        back = win.rowcol_of(*win.latlon_of(r, c))
        if back is None:
            check(f"cell ({r},{c}) round-trips", False, "fell outside")
            break
        worst = max(worst, abs(back[0]-r), abs(back[1]-c))
    else:
        check("every sampled cell round-trips to itself", worst == 0,
              f"worst error {worst} cells")

    print("\nThe polar site AOI still reads correctly\n")
    st = win.stats()
    print(f"    {st['product_id']} -> {st['shape']} @ {st['cell_m']:.0f} m, "
          f"relief {st['relief_m']:.0f} m")
    check("the polar product supplied it", "875S" in st["product_id"])
    check("coverage is complete", st["covered_fraction"] > 0.99,
          f"{st['covered_fraction']*100:.2f}%")
    check("relief is physical", 100 < st["relief_m"] < 6000)
    check("site-tier distortion is negligible", st["scale_error_pct"] < 0.001,
          f"{st['scale_error_pct']:.5f}%")

    print("\nThe seam and the poles are ordinary places\n")
    seam = read_aoi(plan_aoi(-1.0, 1.0, 359.0, 361.0, tier=Tier.SURVEY))
    check("an AOI spanning 0/360 reads without a gap",
          seam.stats()["valid_fraction"] > 0.99,
          f"{seam.stats()['valid_fraction']*100:.2f}% valid across the seam")
    check("its cells are still square",
          abs(seam.cell_m - seam.aoi.cell_m) < 1e-9)

    print("\nThe window cache stores answers, not sources\n")
    import shutil
    shutil.rmtree(_CACHE_DIR, ignore_errors=True)

    # A streamed region is the case the cache exists for: slow to build, and
    # about a thousandth the size of the 900 MB tile it came from.
    stream_aoi = plan_aoi(19.98, 20.02, 30.48, 30.52, source="ldem_1024")
    t0 = time.perf_counter()
    w1 = read_aoi(stream_aoi)
    cold = time.perf_counter() - t0
    t0 = time.perf_counter()
    w2 = read_aoi(stream_aoi)
    warm = time.perf_counter() - t0
    cs = cache_stats()
    print(f"    streamed {w1.shape} @ {w1.cell_m:.1f} m")
    print(f"    cold {cold:.2f}s -> warm {warm:.3f}s   "
          f"cache {cs['entries']} entry, {cs['bytes']/1024:.0f} KB")

    check("a slow read is cached", cs["entries"] == 1, f"{cs['entries']} entries")
    check("the second read is much faster", warm < cold / 3,
          f"{cold:.2f}s -> {warm:.3f}s")
    check("the cached window is identical, not approximate",
          bool(np.allclose(w1.elevation, w2.elevation, equal_nan=True)),
          "float32 resolves elevation to under a millimetre")
    check("coordinates still round-trip from cache",
          w2.rowcol_of(*w2.latlon_of(3, 4)) == (3, 4))
    check("the cache is far smaller than the source tile",
          cs["bytes"] < 5 * 1024 * 1024,
          f"{cs['bytes']/1024:.0f} KB against a 900 MB tile")

    # A local memmap is already fast; storing its output would spend disk to
    # save nothing measurable.
    before = cache_stats()["entries"]
    read_aoi(plan_aoi(-89.50, -89.42, 218.0, 226.0))
    check("a fast local read is not cached",
          cache_stats()["entries"] == before,
          "the cache is for slow reads, not for every read")

    check("a cap is declared so it cannot grow without bound",
          cs["cap_bytes"] >= 64 * 1024 * 1024,
          f"{cs['cap_bytes']/1048576:.0f} MB, least-recently-used evicted first")

    print("\nBudget is still enforced\n")
    import dataclasses
    big = plan_aoi(-89.9, -87.6, 0.0, 359.9, tier=Tier.SURVEY,
                   source="polar_south")
    try:
        read_aoi(dataclasses.replace(big, decimation=1, rows=20000, cols=20000))
        check("an over-budget read is refused", False, "it allocated")
    except ValueError as ex:
        check("an over-budget read is refused, not allocated",
              "authorised" in str(ex), str(ex)[:66] + "…")
    check("a legitimately planned AOI never trips the guard",
          read_aoi(big).elevation.size <= MAX_AOI_CELLS,
          f"{big.rows}x{big.cols} at {big.decimation}x decimation")

    print(f"\n{npass} passed, {nfail} failed")
    return 1 if nfail else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
