"""
Area of interest — the unit of work everything else belongs to.

Every product this system makes is *about a region*: elevation, slope, hazard,
cost, detections, routes, the report. If the region is only a set of query
parameters, four things go wrong at once — every pan recomputes, results cannot
be cached, the report cannot be reproduced, and nothing can be cited later. So
the region is an object, it is validated before any raster is touched, and it
declares what it can and cannot support.

Two tiers, because one grid cannot answer both questions
--------------------------------------------------------
Measured on identical ground at Connecting Ridge (89.45 S, 222 E):

===================  ==================  ================
quantity             survey (470 m)      site (10 m)
===================  ==================  ================
extent               70 km               15 km
max slope found      33.9 deg            69.0 deg
passable             100.00 %            99.92 %
smallest crater      2.35 km             0.05 km
===================  ==================  ================

The survey grid is not wrong; a 470 m average simply cannot contain a 20 m
scarp. The hazard is still there and the grid cannot hold it. That is why a
coarse pass must never be presented as a traverse verdict, and why a 15 km site
pass must never be used to choose *which* 15 km — it cannot see far enough.

``SURVEY`` answers *where should we go?* and may decimate to fit, because a
regional overview is what was asked for. ``SITE`` answers *can a rover cross
it?* and must never decimate — silently coarsening a traverse analysis would
destroy the only property that makes it worth running. A site request too large
to honour is refused rather than degraded.

Coverage
--------
``polar_south`` is a 152 km square of 10 m polar stereographic data reaching
87.5 S. It is the only source fine enough for ``SITE`` work, so full-pipeline
analysis is currently confined to the south polar region — which is where
Artemis III is going.

The cylindrical products cover the globe but degenerate toward the poles as the
east-west cell collapses with cos(phi); above
``POLAR_CYLINDRICAL_LIMIT_DEG`` they are refused rather than warned about,
because a slope computed there is an artefact of the projection
(``CONTRIBUTIONS.md`` 3.7).
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from ..config import (DEM_PRODUCTS, MAX_AOI_CELLS, POLAR_CYLINDRICAL_LIMIT_DEG,
                      R_MOON_M, dataset_path)
from .projection import LocalProjection, max_scale_error


def _max_half_diag(radius: float = R_MOON_M) -> float:
    """Largest half-diagonal whose projection distortion stays within budget."""
    lo, hi = 0.0, math.pi / 2 * radius
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if max_scale_error(mid, radius) <= MAX_SCALE_ERROR:
            lo = mid
        else:
            hi = mid
    return lo

__all__ = [
    "Tier", "SourceSpec", "SOURCES", "AOI", "AOIUnavailable",
    "available_tiers", "plan_aoi",
]


class Tier(str, Enum):
    """What question the region is being asked."""

    SURVEY = "survey"   # where should we go?      regional, may decimate
    SITE = "site"       # can a rover cross it?    traverse-scale, never decimates


#: Cells needed across a feature before it can be *measured* rather than merely
#: noticed. Below this the radial profile has too few samples for a rim or floor
#: to be located, which is the floor ``morphometry`` already refuses beneath.
CELLS_TO_MEASURE = 5
#: Cells needed before a detector can plausibly find something at all.
CELLS_TO_DETECT = 3
#: Coarsest cell that can still express a rover-scale decision. A 2 m vehicle on
#: a 20 m cell is a tenth of a pixel; beyond this, "traversable" is a statement
#: about landscape, not about driving.
SITE_MAX_CELL_M = 20.0

#: Largest tangential scale error tolerated across a region, as a fraction.
#: Every AOI is analysed on a square grid in an azimuthal equidistant
#: projection, whose perpendicular scale grows as c/sin(c) away from the
#: centre. At a hemisphere that is 57 % — the "square cell" premise the whole
#: analysis rests on has failed long before then, so a region that large is
#: refused rather than silently measured wrong. 10 % corresponds to a radius of
#: about 1,300 km, far beyond any realistic survey.
MAX_SCALE_ERROR = 0.10


@dataclass(frozen=True)
class TileScheme:
    """How a product is cut into tiles, and where those tiles live.

    LOLA publishes its finest global griddings as tiles rather than one file:
    ``ldem_1024`` is 144 pieces of 15 x 30 degrees, 900 MB each, 130 GB in
    total. Holding that is absurd; reading the few megabytes an AOI needs out
    of the right tile over HTTP range requests is not, and the PDS server
    supports it (``Accept-Ranges: bytes``, verified).

    Naming follows the archive's own convention, which switches hemisphere
    letter at the equator: the band from -15 to 0 is ``15s_00s`` while 0 to 15
    is ``00n_15n``.
    """

    ppd: int                    # pixels per degree
    lat_deg: int                # tile height in degrees
    lon_deg: int                # tile width in degrees
    base_url: str
    dtype: str = "<i2"
    scaling_factor: float = 0.5
    offset_m: float = 0.0
    #: Measured registration correction, in cells, added to the column index.
    #: Not a fudge factor: see ``SOURCES["ldem_1024"]`` for how it was obtained
    #: and what it corrects for. Zero for any product that needs none.
    col_offset_cells: float = 0.0

    @property
    def tile_rows(self) -> int:
        return self.lat_deg * self.ppd

    @property
    def tile_cols(self) -> int:
        return self.lon_deg * self.ppd

    def _band(self, lat: float) -> tuple[int, int]:
        i = int(math.floor((lat + 90.0) / self.lat_deg))
        i = min(max(i, 0), 180 // self.lat_deg - 1)
        south = -90 + i * self.lat_deg
        return south, south + self.lat_deg

    @staticmethod
    def _lat_token(deg: int) -> str:
        # 0 is written "00s" in a southern band and "00n" in a northern one,
        # so the token cannot be derived from the value alone.
        return f"{abs(deg):02d}{'s' if deg < 0 else 'n'}"

    def tile_name(self, lat: float, lon: float) -> str:
        south, north = self._band(lat)
        lo = (int(math.floor((lon % 360.0) / self.lon_deg)) * self.lon_deg) % 360
        if north <= 0:                       # wholly southern band
            a, b = f"{abs(south):02d}s", f"{abs(north):02d}s"
        else:
            a, b = self._lat_token(south), self._lat_token(north)
        return f"ldem_{self.ppd}_{a}_{b}_{lo:03d}_{lo + self.lon_deg:03d}"

    def tile_origin(self, lat: float, lon: float) -> tuple[int, int]:
        """Row/column of a tile's top-left corner in the virtual global grid."""
        _south, north = self._band(lat)
        lo = (int(math.floor((lon % 360.0) / self.lon_deg)) * self.lon_deg) % 360
        return int((90 - north) * self.ppd), int(lo * self.ppd)

    def url(self, lat: float, lon: float) -> str:
        return f"{self.base_url}{self.tile_name(lat, lon)}.img"


@dataclass(frozen=True)
class SourceSpec:
    """A DEM product the AOI can be cut from."""

    key: str
    product_id: str
    kind: str                  # 'polar_stereographic' | 'simple_cylindrical'
    cell_m: float
    #: Latitude band the product covers, as (south, north).
    lat_range: tuple[float, float]
    #: Longitude band, as (west, east), for products that do not span the
    #: whole circle. ``None`` means every longitude — true of every global
    #: product, and false of a NAC stereo strip a few kilometres wide.
    #: Path components, relative to a data root, of the file that must exist.
    files: tuple[str, ...]
    note: str
    #: Longitude band, as (west, east), for products that do not span the
    #: whole circle. ``None`` means every longitude — true of every global
    #: product, and false of a NAC stereo strip a few kilometres wide.
    lon_range: tuple[float, float] | None = None
    #: Set for products read remotely, tile by tile, instead of from disk.
    tiles: TileScheme | None = None
    #: Whether this source has been cross-validated against another product.
    #: An unvalidated source may be selected explicitly but is never chosen
    #: automatically, and everything derived from it carries a warning.
    validated: bool = True
    #: Why it is not validated, if it is not.
    caveat: str = ""

    @property
    def polar(self) -> bool:
        return self.kind == "polar_stereographic"

    @property
    def streamed(self) -> bool:
        """Read over the network rather than from disk.

        Streamed sources are finer but far slower — measured at 0.2 MB/s from
        PDS, so a fresh region costs minutes rather than a second. They are
        therefore never selected by default; the caller asks for one knowingly.
        """
        return self.tiles is not None

    @property
    def available(self) -> bool:
        """Whether this product is actually on disk.

        Checked before a source is ever chosen. The readers can fall back to
        HTTP range requests for an absent product, which is a fine capability
        and a terrible default: selecting the finest *registered* source rather
        than the finest *present* one turned a 0.2 s window read into a
        420 s one, over the network, without saying so.
        """
        if self.tiles is not None:
            return True                      # served by the archive on demand
        return dataset_path(*self.files) is not None


#: Ordered finest-first, so resolution selection is a scan rather than a search.
SOURCES: dict[str, SourceSpec] = {
    # Finest first. This one covers 0.0002 % of the Moon and is the only
    # equatorial source that can certify a traverse rather than a corridor:
    # 2 m against a 20 m threshold, on ground Apollo 15 drove 27.9 km across.
    "nac_apollo15": SourceSpec(
        key="nac_apollo15", product_id="NAC_DTM_APOLLO15_E261N0036",
        kind="nac_dtm", cell_m=2.0,
        lat_range=(25.5921918, 26.53608486),
        lon_range=(3.50268023, 3.69012653),
        files=("nac_dtm", "NAC_DTM_APOLLO15_E261N0036.IMG"),
        note=("LROC NAC stereo DTM of the Apollo 15 landing site, 2 m. A "
              "28.6 x 5.1 km strip — the only place in this project where an "
              "equatorial traverse can be certified rather than corridored."),
    ),
    "polar_south": SourceSpec(
        key="polar_south", product_id="LDEM_875S_10M",
        kind="polar_stereographic", cell_m=10.0, lat_range=(-90.0, -87.5),
        files=("polar", "dem", "ldem_875s_10m_float.img"),
        note="152 km square on the south pole; the only site-capable source.",
    ),
    "ldem_1024": SourceSpec(
        key="ldem_1024", product_id="LDEM_1024", kind="simple_cylindrical",
        cell_m=1737400.0 * 2 * math.pi / (1024 * 360), lat_range=(-90.0, 90.0),
        files=(),                            # never on disk; read remotely
        tiles=TileScheme(
            ppd=1024, lat_deg=15, lon_deg=30,
            base_url=("https://pds-geosciences.wustl.edu/lro/"
                      "lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/"
                      "cylindrical/img/"),
            # Measured, not guessed. See the caveat below.
            col_offset_cells=-3.47,
        ),
        note=("Global 1024 ppd in 144 tiles of 900 MB. Streamed over HTTP "
              "range requests — 16x finer than LDEM_64 for no storage, but "
              "minutes rather than seconds per fresh region. Carries a "
              "measured -3.47 cell registration correction in longitude."),
        validated=True,
        caveat=(
            "Registration against LDEM_64 was resolved by exact nesting: 1024 "
            "= 16 x 64 and both products are pixel registered, so one LDEM_64 "
            "cell covers precisely 16x16 LDEM_1024 cells and the two can be "
            "compared by block averaging with no interpolation, projection or "
            "resampling to introduce a bias of its own. Sweeping integer "
            "offsets over five strips from 55S to 36N, near side and far, "
            "gives a longitude offset of -3.47 +- 0.54 cells (-0.0034 deg, "
            "-103 m at the equator) and a latitude offset of +0.54 +- 1.95 "
            "cells, consistent with zero. The offset is constant in cells "
            "rather than in ground metres (spread 0.16 against 0.28), which "
            "makes it a longitude offset. The reader was cleared separately: "
            "at four pixels, bytes fetched by hand from the label's own "
            "projection equations match what it returns, so the offset is in "
            "the archive rather than in this code. The archive says why — its "
            "label states the product is built from *preliminary* LOLA data "
            "interpolated with GMT 'surface' and 'grdblend', whereas LDEM_16 "
            "and LDEM_64 are the final GDR and agree with each other to "
            "+0.83 m. The correction above is applied on read; the residual "
            "uncertainty is +-0.54 cell (+-16 m), half a cell at this "
            "posting. Note also that the statistic which first raised this — "
            "correlating the residual against the terrain gradient — is not "
            "trustworthy in general: run on LDEM_16 against LDEM_64, which "
            "are co-registered, it reports r = +0.28 to +0.31 and implied "
            "shifts of 155 to 268 m. It happened to point the right way here."),
    ),
    "ldem_128": SourceSpec(
        key="ldem_128", product_id="LDEM_128", kind="simple_cylindrical",
        cell_m=DEM_PRODUCTS["ldem_128"].scale_m_px, lat_range=(-90.0, 90.0),
        files=("lola_dem", "LDEM_128.IMG"),
        note="Global 128 ppd.",
    ),
    "ldem_64": SourceSpec(
        key="ldem_64", product_id="LDEM_64", kind="simple_cylindrical",
        cell_m=DEM_PRODUCTS["ldem_64"].scale_m_px, lat_range=(-90.0, 90.0),
        files=("lola_dem", "LDEM_64.IMG"),
        note="Global 64 ppd; the default survey source.",
    ),
    "ldem_16": SourceSpec(
        key="ldem_16", product_id="LDEM_16", kind="simple_cylindrical",
        cell_m=DEM_PRODUCTS["ldem_16"].scale_m_px, lat_range=(-90.0, 90.0),
        files=("lola_dem", "LDEM_16.IMG"),
        note="Global 16 ppd; whole-hemisphere context.",
    ),
}


class AOIUnavailable(Exception):
    """No source can honour the request. Carries the reason, not just a flag."""


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _wrap180(lon: float) -> float:
    return ((lon + 180.0) % 360.0 + 360.0) % 360.0 - 180.0


def _span_m(south: float, north: float, west: float, east: float) -> tuple[float, float]:
    """Ground size of the box, north-south and east-west.

    A lat/lon box is not a rectangle on the ground — it is a wedge that narrows
    toward the pole. East-west is therefore measured at the edge *closest to the
    equator*, which is the widest one, because that edge determines how large a
    raster must be to contain the box.

    Measuring at the poleward edge instead would report the narrowest width and
    understate the request, letting an oversized box slip past the cell budget.
    A 1.9 x 40 degree box at 88-89.9 S is 2 km wide at its poleward edge and
    42 km wide at its equatorward edge; only the second number bounds the work.
    """
    dlat = abs(north - south)
    # Eastward span, not a signed difference. Wrapping to +/-180 would collapse
    # any box wider than a hemisphere — a 359.9 degree request would read as
    # 0.1 degrees and slip past the cell budget by four orders of magnitude.
    dlon = (east - west) % 360.0
    if dlon == 0.0:
        dlon = 360.0                       # west == east means all the way round
    ns = math.radians(dlat) * R_MOON_M
    widest_lat = min(abs(south), abs(north))
    ew = math.radians(dlon) * R_MOON_M * math.cos(math.radians(min(widest_lat, 89.999)))
    return ns, ew


def _lon_span(west: float, east: float) -> float:
    """Eastward span from west to east, in degrees.

    A zero difference means a zero-width box, **not** a full circuit. Treating
    it as 360 turned a user typing the same longitude twice into a request for
    the entire Moon — 1512 x 1417 cells at 5 km, silently, with no complaint.
    A whole-globe region has to be asked for explicitly, and even then it is
    refused for distortion.
    """
    span = (east - west) % 360.0
    return span                      # 0 stays 0; the caller decides what that means


def _local_extent_m(south: float, north: float,
                    west: float, east: float) -> tuple[float, float]:
    """Size of the raster an AOI will actually occupy, in metres.

    Every AOI is analysed on a square grid in an azimuthal equidistant
    projection centred on itself (``aoi_window.py``), so the raster is the
    bounding box of the region *in that projection* — not its ground area and
    not its extent in whatever grid the bytes happen to be stored in.

    Sizing it any other way lets the cell budget approve one thing and the
    reader allocate another: a lat/lon box near a pole is a curved wedge whose
    bounding box is a third larger than the wedge, and a box spanning more than
    a hemisphere is larger still. The perimeter is sampled rather than solved
    because the extreme is often on an edge rather than at a corner.
    """
    span = _lon_span(west, east)
    lat0 = 0.5 * (south + north)
    lon0 = _wrap180(west + span / 2.0)
    proj = LocalProjection(lat0, lon0)

    t = np.linspace(0.0, 1.0, 129)
    lons = west + span * t
    lats = south + (north - south) * t
    peri_lat = np.concatenate([np.full_like(t, south), np.full_like(t, north),
                               lats, lats])
    peri_lon = np.concatenate([lons, lons,
                               np.full_like(t, west), np.full_like(t, east)])
    x, y = proj.forward(peri_lat, peri_lon)

    # A region enclosing a pole has no perimeter extreme in the direction of
    # the pole itself, so include it explicitly.
    if span >= 359.999:
        px, py = proj.forward(np.array([90.0, -90.0]), np.array([0.0, 0.0]))
        x = np.concatenate([x, px])
        y = np.concatenate([y, py])

    return float(np.max(y) - np.min(y)), float(np.max(x) - np.min(x))


# ---------------------------------------------------------------------------
# AOI
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AOI:
    """A validated region, bound to one source at one posting."""

    south: float
    north: float
    west: float
    east: float
    tier: Tier
    source: SourceSpec
    #: Native cells combined into one analysed cell. 1 means full resolution.
    decimation: int
    rows: int
    cols: int
    #: Things that are *wrong or surprising* about this result.
    warnings: tuple[str, ...] = field(default_factory=tuple)
    #: Finer sources that also cover this region. Not warnings — options.
    alternatives: tuple[dict, ...] = field(default_factory=tuple)

    # -- derived ---------------------------------------------------------

    @property
    def cell_m(self) -> float:
        """Ground size of one *analysed* cell, after any decimation."""
        return self.source.cell_m * self.decimation

    @property
    def cell_count(self) -> int:
        return self.rows * self.cols

    @property
    def extent_m(self) -> tuple[float, float]:
        return (self.rows * self.cell_m, self.cols * self.cell_m)

    @property
    def centre(self) -> tuple[float, float]:
        return (0.5 * (self.south + self.north), _wrap180(0.5 * (self.west + self.east)))

    @property
    def key(self) -> str:
        """Stable identity. Two identical requests must produce one cache entry."""
        raw = (f"{self.source.key}|{self.tier.value}|{self.decimation}|"
               f"{self.south:.6f},{self.north:.6f},{self.west:.6f},{self.east:.6f}")
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    # -- honesty ---------------------------------------------------------

    def capability(self) -> dict:
        """What this region can and cannot support, in its own units.

        Reported rather than assumed, so a caller never has to infer the limit
        from the resolution — and so the report can print what was *not*
        possible alongside what was.
        """
        c = self.cell_m
        return {
            "cell_m": round(c, 3),
            "crater_detect_floor_m": round(c * CELLS_TO_DETECT, 1),
            "crater_measure_floor_m": round(c * CELLS_TO_MEASURE, 1),
            "rover_footprint_px": round(2.0 / c, 4),
            "supports_traverse": bool(c <= SITE_MAX_CELL_M),
            "supports_boulders": False,   # needs sub-metre imagery, not a DEM
            "boulder_note": (
                "Boulder detection requires sub-metre imagery; a 1 m rock "
                f"occupies {(1.0 / c) ** 2 * 100:.4f} % of one {c:.0f} m cell "
                "and cannot be recovered from this DEM at any effort."
            ),
        }

    def to_dict(self) -> dict:
        ns, ew = self.extent_m
        return {
            "key": self.key,
            "tier": self.tier.value,
            "bounds": {"south": self.south, "north": self.north,
                       "west": self.west, "east": self.east},
            "centre": {"lat": self.centre[0], "lon": self.centre[1]},
            "source": {"key": self.source.key, "product_id": self.source.product_id,
                       "kind": self.source.kind,
                       "native_cell_m": self.source.cell_m},
            "decimation": self.decimation,
            "cell_m": round(self.cell_m, 3),
            "shape": [self.rows, self.cols],
            "cells": self.cell_count,
            "extent_km": [round(ns / 1000, 3), round(ew / 1000, 3)],
            "capability": self.capability(),
            "warnings": list(self.warnings),
            "alternatives": list(self.alternatives),
        }


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def _covers(src: SourceSpec, south: float, north: float,
            west: float = 0.0, east: float = 360.0) -> bool:
    """Whether a source has data for this latitude band.

    Cylindrical products are no longer refused near the poles. They *are*
    degenerate in their own grid — the east-west cell collapses as cos(phi) —
    but nothing is analysed in that grid any more: an AOI is resampled onto a
    square local grid first, which is the standard remedy for anisotropic
    sampling and restores rise-over-run. The data at high latitude is real; only
    its native gridding was awkward. A warning still names the better product
    where one exists.
    """
    lo, hi = src.lat_range
    if src.polar:
        # Conservative: the stereographic square reaches past its declared
        # latitude in the corners, but requiring the whole box inside the
        # circle of validity keeps every cell real.
        return north <= hi
    if not (lo <= south and north <= hi):
        return False
    if src.lon_range is None:
        return True
    # A bounded product must contain the region in longitude too, and the
    # comparison has to happen on one branch: a strip at 3.5 degE and a region
    # written as 3.5 degE are the same place, but 359 and -1 are as well.
    w, e = src.lon_range
    ws, es = _wrap180(w), _wrap180(e)
    rs, re_ = _wrap180(west), _wrap180(east)
    if es < ws:
        es += 360.0
    if re_ < rs:
        re_ += 360.0
    for shift in (-360.0, 0.0, 360.0):
        if ws <= rs + shift and re_ + shift <= es:
            return True
    return False


def available_tiers(south: float, north: float,
                    west: float, east: float) -> dict[str, list[str]]:
    """Which tiers this box could support, and which sources could serve them.

    Called before any raster is opened, so a user can be told what a region can
    do *before* committing to an analysis.
    """
    out: dict[str, list[str]] = {Tier.SURVEY.value: [], Tier.SITE.value: []}
    for src in SOURCES.values():
        if not (_covers(src, south, north, west, east) and src.available):
            continue
        out[Tier.SURVEY.value].append(src.key)
        if src.cell_m <= SITE_MAX_CELL_M:
            out[Tier.SITE.value].append(src.key)
    return out


def plan_aoi(south: float, north: float, west: float, east: float, *,
             tier: Tier | str | None = None,
             source: str | None = None,
             finest: bool = False,
             max_cells: int = MAX_AOI_CELLS) -> AOI:
    """Bind a region to the best data that actually covers it.

    Resolution is an **outcome, not a precondition**. Earlier this function
    took the tier as a requirement: ask for site tier outside the south pole
    and it refused, because no product finer than 20 m covered the region. That
    made the *absence of data* look like a *malformed request*, and it left
    most of the Moon unusable for no better reason than a threshold.

    The order is now the one the data implies:

        region -> what covers it? -> finest of those -> analyse at that
        -> declare what the result can support

    So this refuses only when nothing covers the region at all. Everything else
    succeeds and reports honestly: :attr:`AOI.tier` and
    :meth:`AOI.capability` are *derived* from the cell size that came back, so
    a 474 m analysis is never mistaken for a traverse certification and a 10 m
    one is never withheld because the caller forgot to ask for it.

    ``finest`` widens the search to validated sources that must be streamed.
    Off by default because a preview has to be instant; on when a caller has
    committed to a region and wants the best data that exists for it, which
    costs tens of seconds and is worth it — a 473.8 m posting understates p99
    slope at the Apollo sites by 2.7 to 5.5 times.

    ``tier`` is now an optional ceiling rather than a demand — pass
    ``Tier.SURVEY`` to deliberately take a coarser, faster look at a region
    that could support better.
    """
    tier = Tier(tier) if (tier is not None and not isinstance(tier, Tier)) else tier
    south, north = float(min(south, north)), float(max(south, north))
    west, east = _wrap180(float(west)), _wrap180(float(east))
    if north - south <= 0:
        raise AOIUnavailable("north must be greater than south")
    if not (-90.0 <= south < north <= 90.0):
        raise AOIUnavailable("latitudes must lie within -90..90")
    if _lon_span(west, east) <= 0.0:
        raise AOIUnavailable(
            f"west and east are the same meridian ({west:.4f}), so the region "
            "has no width. Give an eastward span, or drag a box on the globe.")

    warnings: list[str] = []

    # -- pick a source -------------------------------------------------
    if source is not None:
        if source not in SOURCES:
            raise AOIUnavailable(f"unknown source {source!r}; "
                                 f"have {sorted(SOURCES)}")
        candidates = [SOURCES[source]]
        if not _covers(candidates[0], south, north, west, east):
            raise AOIUnavailable(
                f"{source} does not cover {south:.2f}..{north:.2f} deg latitude")
        if not candidates[0].available:
            raise AOIUnavailable(
                f"{source} ({SOURCES[source].product_id}) is not present on "
                "disk. Fetch it with scripts/fetch_dem.py --download, or let "
                "the planner choose from what is available.")
    else:
        # Finest *present* source, not finest registered: an absent product can
        # still be served over HTTP range requests, which is 2,000x slower and
        # must never be picked by default.
        candidates = [s for s in SOURCES.values()
                      if _covers(s, south, north, west, east) and s.available]
        # A deliberately coarse look is allowed; a demand for detail the data
        # cannot supply is not, because that would be a refusal again.
        if tier is Tier.SURVEY:
            coarse = [s for s in candidates if s.cell_m > SITE_MAX_CELL_M]
            candidates = coarse or candidates
        # Two different questions, so two different answers.
        #
        # Dragging a box on the globe asks "what is here?" and must answer in
        # milliseconds, so only local, validated data is eligible: a streamed
        # source is finer but costs ~45 s, and imposing that on a preview
        # nobody committed to is not an improvement.
        #
        # Opening a region asks "analyse this properly", and there the answer
        # is different. Measured against the Apollo, Lunokhod and Yutu sites,
        # a 473.8 m posting understates p99 slope by 2.7-5.5x and reports
        # terrain as uniformly gentle when it holds slopes past a rover's
        # tip-over limit (see analysis.ground_truth). Coarse data does not
        # merely blur a hazard there, it deletes it — so when the caller has
        # asked for the finest, waiting is the right trade.
        #
        # Unvalidated sources stay ineligible either way: a product whose
        # agreement with the reference is unresolved must be an explicit
        # choice, never a default.
        eligible = [s for s in candidates
                    if s.validated and (finest or not s.streamed)]
        candidates = sorted(eligible or candidates, key=lambda s: s.cell_m)

    if not candidates:
        raise AOIUnavailable(
            f"No data covers {south:.2f}..{north:.2f} deg. Every registered "
            "product either does not reach this latitude or is not present on "
            "disk; fetch one with scripts/fetch_dem.py --download.")

    src = candidates[0]
    # Size the region the way it will actually be cut: every AOI is resampled
    # onto a square grid in a projection centred on itself, so the raster is
    # that projection's bounding box — the same rule for every source.
    ns_m, ew_m = _local_extent_m(south, north, west, east)
    if ns_m <= 0 or ew_m <= 0:
        raise AOIUnavailable("the box has zero extent on the ground")

    # A region too large for its own projection. Azimuthal equidistant stretches
    # as c/sin(c) away from the centre, so beyond roughly 1,300 km radius the
    # square-cell premise every downstream stage depends on has failed. Refused
    # rather than measured wrongly — and this also catches the globe-spanning
    # box, whose perimeter samples all land on one meridian and used to yield a
    # raster one pixel wide without complaint.
    half_diag = 0.5 * math.hypot(ns_m, ew_m)
    err = max_scale_error(half_diag)
    if err > MAX_SCALE_ERROR:
        raise AOIUnavailable(
            f"Region spans {half_diag*2/1000:,.0f} km corner to corner, which "
            f"distorts by {err*100:.0f}% in the projection it would be analysed "
            f"on (limit {MAX_SCALE_ERROR*100:.0f}%). Slope and distance would "
            "not mean the same thing across it. Draw a smaller region — about "
            f"{2*_max_half_diag()/1000:,.0f} km across or less.")

    # -- fit the cell budget -------------------------------------------
    decim = 1
    rows = max(1, int(round(ns_m / src.cell_m)))
    cols = max(1, int(round(ew_m / src.cell_m)))

    if rows * cols > max_cells:
        # Decimate rather than refuse. A box too large for its source's native
        # posting is a normal request, not an error — the honest response is a
        # coarser answer that says it is coarser, which the derived tier and
        # capability then carry through every downstream product.
        decim = math.ceil(math.sqrt((rows * cols) / max_cells))
        rows = max(1, rows // decim)
        cols = max(1, cols // decim)
        native = src.cell_m
        warnings.append(
            f"Region too large for {native:.0f} m at the {max_cells:,} cell "
            f"budget, so it was analysed at {native*decim:.0f} m "
            f"({decim}x coarser). For {native:.0f} m detail, draw a box of "
            f"about {math.sqrt(max_cells)*native/1000:.0f} km or less.")

    cell_m = src.cell_m * decim

    # The tier is what the data turned out to support, not what was asked for.
    tier = Tier.SITE if cell_m <= SITE_MAX_CELL_M else Tier.SURVEY

    if not src.validated:
        warnings.append(f"UNVALIDATED SOURCE — {src.product_id}: {src.caveat}")

    # Finer sources are *alternatives*, not warnings, and they are reported as
    # structured data rather than prose.
    #
    # As a warning this was noise by construction: a streamed source is never
    # the default, so "something finer exists" was true on every request
    # forever, printed in the same alarm colour as a real problem, directly
    # beneath a menu already offering the very thing it described. A notice
    # that always fires teaches the reader to skip the ones that matter.
    alternatives = tuple(
        {"key": s.key, "product_id": s.product_id, "cell_m": round(s.cell_m, 2),
         "finer_by": round(cell_m / s.cell_m, 1),
         "access": "streamed" if s.streamed else
                   ("on disk" if s.available else "needs download")}
        for s in sorted((s for s in SOURCES.values()
                         if s.cell_m < cell_m and _covers(s, south, north, west, east)
                         and s.key != src.key),
                        key=lambda s: s.cell_m))

    if (not src.polar
            and max(abs(south), abs(north)) > POLAR_CYLINDRICAL_LIMIT_DEG):
        warnings.append(
            f"Above {POLAR_CYLINDRICAL_LIMIT_DEG:.0f} deg the source grid is "
            "sampled anisotropically (its east-west cell collapses as cos(phi)). "
            "Resampling to a square local grid restores usable slope, but a "
            "dedicated polar product is better where one exists — south of "
            "87.5 deg, use 'polar_south'.")

    return AOI(south=south, north=north, west=west, east=east, tier=tier,
               source=src, decimation=decim, rows=rows, cols=cols,
               warnings=tuple(warnings), alternatives=alternatives)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def _self_test() -> int:
    npass = nfail = 0

    def check(name, ok, detail=""):
        nonlocal npass, nfail
        if ok:
            npass += 1
            print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
        else:
            nfail += 1
            print(f"  FAIL  {name}   {detail}")

    print("\nTier selection follows the data, not the request\n")

    site = plan_aoi(-89.55, -89.35, 220.0, 224.0, tier="site")
    print(f"    polar site  : {site.source.key} @ {site.cell_m:.0f} m, "
          f"{site.rows}x{site.cols} = {site.cell_count:,} cells")
    check("a polar box resolves to the 10 m polar source",
          site.source.key == "polar_south" and site.cell_m == 10.0)
    check("a polar site supports a traverse verdict",
          site.capability()["supports_traverse"])

    # Resolution is an outcome, not a precondition: a region outside the fine
    # data still analyses, at whatever covers it, and says what that supports.
    mid = plan_aoi(-20.0, -19.0, 10.0, 11.0)
    print(f"    mid-lat: {mid.source.key} @ {mid.cell_m:.0f} m, "
          f"{mid.cell_count:,} cells, tier={mid.tier.value}")
    check("a mid-latitude region analyses rather than being refused",
          mid.cell_count > 0,
          "asking for detail the data lacks is not a malformed request")
    check("its tier is derived from what the data gave",
          mid.tier is Tier.SURVEY and not mid.capability()["supports_traverse"],
          f"{mid.cell_m:.0f} m cell vs a {SITE_MAX_CELL_M:.0f} m limit")
    # A finer source is an option, not a fault. Reporting it as a warning meant
    # every region on the Moon carried one forever, in the same colour as a
    # real problem — which trains the reader to skip all of them.
    check("a normal region carries no warnings at all",
          not mid.warnings, list(mid.warnings))
    check("finer sources are offered as structured alternatives instead",
          any(a["access"] == "streamed" for a in mid.alternatives),
          ", ".join(f"{a['product_id']} {a['cell_m']}m ({a['access']})"
                    for a in mid.alternatives))
    check("each alternative says how much finer and how to get it",
          all({"finer_by", "access", "cell_m"} <= set(a) for a in mid.alternatives))
    check("a region already on the best source offers nothing",
          not plan_aoi(-89.50, -89.42, 218.0, 226.0).alternatives,
          "10 m polar is the finest that covers it")

    print("\nThe cell budget coarsens rather than refuses\n")

    big = plan_aoi(-30.0, 0.0, 0.0, 30.0)
    print(f"    900 km region: decimation {big.decimation}x -> "
          f"{big.cell_m:.0f} m, {big.cell_count:,} cells")
    check("a large region decimates rather than failing",
          big.cell_count <= MAX_AOI_CELLS and big.decimation > 1)
    check("and says so, with the box size that would keep full detail",
          any("Region too large" in w and "or less" in w for w in big.warnings))

    huge = plan_aoi(-89.9, -88.0, 0.0, 40.0)
    print(f"    oversized polar box: {huge.cell_m:.0f} m, tier={huge.tier.value}")
    check("an oversized polar box coarsens instead of being refused",
          huge.cell_count <= MAX_AOI_CELLS)
    check("and its tier drops to match, so nothing over-claims",
          (huge.tier is Tier.SITE) == (huge.cell_m <= SITE_MAX_CELL_M),
          f"{huge.cell_m:.0f} m -> {huge.tier.value}")

    print("\nA coarser look can still be asked for deliberately\n")
    fine = plan_aoi(-89.50, -89.42, 218.0, 226.0)
    fast = plan_aoi(-89.50, -89.42, 218.0, 226.0, tier="survey")
    print(f"    default {fine.cell_m:.0f} m ({fine.source.key}) vs "
          f"survey {fast.cell_m:.0f} m ({fast.source.key})")
    check("the default takes the finest data available", fine.cell_m < fast.cell_m,
          "resolution is chosen by the data, not demanded by the caller")
    check("asking for survey deliberately returns something coarser",
          fast.tier is Tier.SURVEY)

    print("\nAny region on the Moon can be planned\n")
    everywhere = [("Mare Imbrium", 32.0, 33.0, -18.0, -17.0),
                  ("equator", -0.5, 0.5, 100.0, 101.0),
                  ("far side", 10.0, 11.0, 180.0, 181.0),
                  ("86 north", 86.0, 87.0, 0.0, 1.0),
                  ("across the seam", -1.0, 1.0, 359.0, 361.0)]
    for nm, s, n, w, e in everywhere:
        a = plan_aoi(s, n, w, e, tier="survey")
        check(f"{nm:<16} {a.rows}x{a.cols} @ {a.cell_m:.0f} m",
              a.cell_count <= MAX_AOI_CELLS)

    high = plan_aoi(86.0, 87.0, 0.0, 1.0, tier="survey")
    check("a high-latitude survey warns about anisotropic source sampling",
          any("anisotropically" in w for w in high.warnings),
          "resampling fixes the grid; the warning names the better product")

    print("\nOnly sources actually on disk are chosen\n")
    absent = [k for k, s in SOURCES.items() if not s.available]
    present = [k for k, s in SOURCES.items() if s.available]
    print(f"    present: {present}")
    print(f"    absent : {absent}")
    a = plan_aoi(-0.5, 0.5, 100.0, 101.0, tier="survey")
    check("the chosen source is present on disk", a.source.available,
          f"picked {a.source.key} at {a.source.cell_m:.0f} m")
    check("an absent source is never selected automatically",
          a.source.key not in absent,
          "a missing product falls back to HTTP range reads — 2,000x slower")
    if absent:
        try:
            plan_aoi(-0.5, 0.5, 100.0, 101.0, tier="survey", source=absent[0])
            check("asking for an absent source is refused", False, "allowed")
        except AOIUnavailable as e:
            check("asking for an absent source is refused with the fix",
                  "not present on disk" in str(e), str(e)[:60] + "…")

    print("\nCapability is declared, not inferred\n")
    cap_s, cap_v = site.capability(), mid.capability()
    print(f"    site   : detect >= {cap_s['crater_detect_floor_m']:.0f} m, "
          f"measure >= {cap_s['crater_measure_floor_m']:.0f} m")
    print(f"    survey : detect >= {cap_v['crater_detect_floor_m']:.0f} m, "
          f"measure >= {cap_v['crater_measure_floor_m']:.0f} m")
    check("the site floor is far below the catalogue completeness limit",
          cap_s["crater_measure_floor_m"] < 1000.0,
          "below 1 km is where detection earns its place")
    check("the survey floor is above it",
          cap_v["crater_measure_floor_m"] > 1000.0,
          "a survey can only re-find what Robbins already has")
    check("neither tier claims boulders",
          not cap_s["supports_boulders"] and not cap_v["supports_boulders"],
          "a DEM cannot resolve a 1 m rock at any posting")

    print("\nIdentity is stable\n")
    again = plan_aoi(-89.55, -89.35, 220.0, 224.0, tier="site")
    check("the same request yields the same key", again.key == site.key, site.key)
    other = plan_aoi(-89.55, -89.35, 220.0, 224.5, tier="site")
    check("a different box yields a different key", other.key != site.key)

    print("\nWhat a region can do is answerable before any raster is opened\n")
    t_pole = available_tiers(-89.6, -89.4, 220.0, 224.0)
    t_mid = available_tiers(-20.0, -19.0, 10.0, 11.0)
    print(f"    polar   : {t_pole}")
    print(f"    mid-lat : {t_mid}")
    check("the pole offers both tiers", t_pole["site"] and t_pole["survey"])
    check("mid-latitudes offer survey only",
          not t_mid["site"] and t_mid["survey"])

    print(f"\n{npass} passed, {nfail} failed")
    return 1 if nfail else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
