"""
LunarSerpent — central configuration.

Every path, dataset endpoint, physical constant and model parameter used by the
system is declared here, so that the provenance of each number is traceable to
exactly one place.

Values marked ``[MEASURED]`` come from an instrument or a published fit and are
cited in ``docs/FORMULAS.md``.  Values marked ``[ENGINEERING ESTIMATE]`` are
design assumptions chosen to make a model behave plausibly; they are flagged
because the project's integrity rule forbids presenting an assumption as an
observation.

Storage policy
--------------
Source data is read **in place** from the mounted Google Drive and is never
copied into the project.  Products not present locally are streamed from PDS
using HTTP range requests (verified: the server returns HTTP 206), so the
project's own disk footprint stays negligible.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]

FRONTEND_DIR = PROJECT_ROOT / "frontend"
DOCS_DIR = PROJECT_ROOT / "docs"
DATA_DIR = PROJECT_ROOT / "data"
DERIVED_DIR = DATA_DIR / "derived"
CACHE_DIR = DATA_DIR / "cache"
TILE_CACHE_DIR = CACHE_DIR / "tiles"
INDEX_DIR = DERIVED_DIR / "index"

for _d in (DERIVED_DIR, CACHE_DIR, TILE_CACHE_DIR, INDEX_DIR):
    _d.mkdir(parents=True, exist_ok=True)


#: Candidate locations for the read-only dataset collection, in priority order.
#: Override with the ``LUNARSERPENT_DATA_ROOT`` env var.
#:
#: The project's own copy comes first, deliberately.  Reading through a Google
#: Drive mount is transparent but not free: the Drive client caches every byte
#: it serves onto the system drive, so streaming a 227 MB catalogue from ``G:``
#: silently writes 227 MB to ``C:``.  Holding the few files the system reads at
#: runtime locally — about 32 MB — makes the project self-contained, keeps it
#: working when the Drive is unmounted, and leaves the user free to clear or
#: relocate Drive's cache without breaking anything here.
#:
#: The Drive path is retained as a fallback so bulk datasets that are *not*
#: copied (the 227 MB Robbins CSV, the Chandrayaan and training imagery) remain
#: reachable when they are genuinely needed.
_DATA_ROOT_CANDIDATES = [
    PROJECT_ROOT / "data" / "raw",
    Path(
        r"G:\My Drive\LunarNavigator_capstone_project_temp"
        r"\lunar-navigator\data\raw"
    ),
]


def _data_roots() -> list[Path]:
    """Dataset roots to search, in priority order."""
    env = os.environ.get("LUNARSERPENT_DATA_ROOT")
    if env:
        p = Path(env)
        return [p] if p.exists() else []
    out = []
    for cand in _DATA_ROOT_CANDIDATES:
        try:
            if cand.exists():
                out.append(cand)
        except OSError:
            continue  # drive not mounted
    return out


DATA_ROOTS: list[Path] = _data_roots()

#: Highest-priority root, or ``None`` when nothing is reachable.  Per SRD SR-D2
#: an absent dataset root must not prevent startup — sources simply report
#: themselves unavailable.
DATA_ROOT: Path | None = DATA_ROOTS[0] if DATA_ROOTS else None


def dataset_path(*parts: str) -> Path | None:
    """Resolve a dataset file across all roots, or ``None`` if nowhere.

    Resolution is *per file*, not per root: the local copy is preferred for the
    handful of products read at runtime, while anything not copied locally is
    still found on the Drive mount if it happens to be available. A missing
    Drive therefore degrades the system rather than disabling it.
    """
    for root in DATA_ROOTS:
        p = root.joinpath(*parts)
        try:
            if p.exists():
                return p
        except OSError:
            continue
    return None


# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------

#: [MEASURED] Lunar reference sphere radius [m].  Both the IAU/IAG mean radius
#: and the exact reference radius of the LOLA GDR products, whose PDS3 label
#: declares A_AXIS_RADIUS = B_AXIS_RADIUS = C_AXIS_RADIUS = 1737.4 km.
#: Archinal et al. (2018), doi:10.1007/s10569-017-9805-5
R_MOON_M = 1_737_400.0

#: [MEASURED] Mean lunar surface gravity [m s^-2].  NASA Moon Fact Sheet.
G_MOON = 1.625

#: Body-fixed frame of every coordinate in this system.  Matches the LOLA label
#: COORDINATE_SYSTEM_NAME = "MEAN EARTH/POLAR AXIS OF DE421".
REFERENCE_FRAME = "IAU Mean Earth / Polar Axis (ME), DE421 realisation"

#: Above this latitude, simple-cylindrical grids degenerate (east-west cell size
#: -> 0).  Analysis is refused rather than returning unjustifiable numbers.
#: See FORMULAS.md §2.4.
POLAR_CYLINDRICAL_LIMIT_DEG = 85.0


# ---------------------------------------------------------------------------
# LOLA gridded data records
# ---------------------------------------------------------------------------

LOLA_GDR_BASE = (
    "https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/"
    "lrolol_1xxx/data/lola_gdr/cylindrical/img/"
)


@dataclass(frozen=True)
class DEMProduct:
    """A LOLA global simple-cylindrical DEM.

    All fields were read from the product's PDS3 ``.LBL`` during design; none
    are assumed.  ``scale_m_px`` is the equatorial map scale and satisfies
    ``scale_m_px == 2*pi*R_MOON_M / width`` by construction.
    """

    product_id: str
    ppd: int              # pixels per degree (MAP_RESOLUTION)
    width: int            # LINE_SAMPLES
    height: int           # LINES
    scale_m_px: float     # MAP_SCALE at the equator [m/pixel]
    scaling_factor: float = 0.5           # DN -> metres
    offset_m: float = 1_737_400.0         # reference radius [m]
    dtype: str = "<i2"                    # LSB_INTEGER, SAMPLE_BITS = 16

    @property
    def url(self) -> str:
        return LOLA_GDR_BASE + self.product_id.lower() + ".img"

    @property
    def label_url(self) -> str:
        return LOLA_GDR_BASE + self.product_id.lower() + ".lbl"

    @property
    def nbytes(self) -> int:
        return self.width * self.height * 2

    @property
    def local_path(self) -> Path | None:
        """Path within the owner dataset collection, if present."""
        return dataset_path("lola_dem", f"{self.product_id}.IMG")


#: Registry of LOLA DEMs.  Verified against live PDS labels on 2026-08-04.
DEM_PRODUCTS: dict[str, DEMProduct] = {
    "ldem_4": DEMProduct("LDEM_4", 4, 1440, 720, 7580.84),
    "ldem_16": DEMProduct("LDEM_16", 16, 5760, 2880, 1895.21),
    "ldem_64": DEMProduct("LDEM_64", 64, 23040, 11520, 473.802),
    "ldem_128": DEMProduct("LDEM_128", 128, 46080, 23040, 236.901),
}

#: The working grid.
#:
#: LDEM_64 (474 m/px, 506 MB) rather than LDEM_16 (1895 m/px, 32 MB), because
#: the basemap imagery is served at 83 m/px and deforming it with a 1895 m/px
#: DEM left the picture 23× sharper than the shape beneath it.  At 474 m/px a
#: 100 km patch carries 211 real elevation samples instead of 53, so the relief
#: mesh is mostly measurement rather than interpolation.
#:
#: Fetched with ``python scripts/fetch_dem.py ldem_64``, which verifies the PDS
#: label against this registry before transferring the raster.
DEFAULT_DEM = "ldem_64"


# ---------------------------------------------------------------------------
# Basemap imagery — NASA Moon Trek WMTS (streamed)
# ---------------------------------------------------------------------------

TREK_BASE = "https://trek.nasa.gov/tiles/Moon/EQ"


@dataclass(frozen=True)
class TileLayer:
    key: str
    title: str
    layer_id: str
    ext: str
    max_zoom: int
    native_m_px: float
    description: str
    credit: str

    @property
    def url_template(self) -> str:
        return (
            f"{TREK_BASE}/{self.layer_id}/1.0.0/default/default028mm/"
            "{z}/{y}/{x}." + self.ext
        )


BASEMAP_LAYERS: dict[str, TileLayer] = {
    # The finest global imagery this project has found. Kaguya's Terrain Camera
    # orthomosaic is published at 4096 ppd (7.40 m/px), but Trek's tile pyramid
    # for it stops at z=10 — probed directly, and 404 at every z=11 tile tried,
    # at the equator, in Imbrium, at Tycho, on the far side and near the south
    # pole. So 20.82 m/px is what can actually be served, which is still four
    # times finer than the WAC mosaic and sixteen times the pixels.
    #
    # It is PNG, not JPEG: the pyramid is published that way, and the extension
    # is part of the tile URL rather than a preference.
    "kaguya_tc": TileLayer(
        key="kaguya_tc",
        title="Kaguya TC Orthomosaic",
        layer_id="Kaguya_TCortho_Mosaic_Global_4096ppd",
        ext="png",
        max_zoom=10,
        native_m_px=7.40,
        description=(
            "SELENE/Kaguya Terrain Camera orthorectified mosaic — the finest "
            "global lunar imagery available. Published at 7.40 m/px; served "
            "here to 20.8 m/px, which is where the tile pyramid ends. Same "
            "IAU Mean Earth/Polar Axis frame as the DEM, so it registers "
            "against the analysis without reprojection."
        ),
        credit="JAXA/SELENE (Kaguya) Terrain Camera team",
    ),
    "wac": TileLayer(
        key="wac",
        title="LROC WAC Global Mosaic",
        layer_id="LRO_WAC_Mosaic_Global_303ppd_v02",
        ext="jpg",
        max_zoom=8,
        native_m_px=100.0,
        description=(
            "LRO Wide Angle Camera global monochrome morphologic mosaic, "
            "photometrically normalised so that brightness represents albedo "
            "rather than illumination."
        ),
        credit="NASA/GSFC/Arizona State University",
    ),
    "lola_color": TileLayer(
        key="lola_color",
        title="LOLA Colour Shaded Relief",
        layer_id="LRO_LOLA_ClrShade_Global_128ppd_v04",
        ext="jpg",
        max_zoom=7,
        native_m_px=236.901,
        description="Hue encodes elevation relative to the 1737.4 km sphere.",
        credit="NASA/GSFC/MIT/LOLA Science Team",
    ),
    "lola_shade": TileLayer(
        key="lola_shade",
        title="LOLA Hillshade (grey)",
        layer_id="LRO_LOLA_Shade_Global_128ppd_v04",
        ext="jpg",
        max_zoom=7,
        native_m_px=236.901,
        description="Neutral grey hillshade of LOLA topography.",
        credit="NASA/GSFC/MIT/LOLA Science Team",
    ),
}

DEFAULT_BASEMAP = "wac"

#: Offline fallback so the globe renders with no network (PRD FR-1.16).
OFFLINE_TEXTURE = ("moon_texture", "moon_texture.jpg")

#: Bounded tile cache (SRD SR-D5).
TILE_CACHE_MAX_BYTES = 512 * 1024 * 1024


# ---------------------------------------------------------------------------
# Catalogues
# ---------------------------------------------------------------------------

ROBBINS_CSV = ("robbins_db", "lunar_crater_database_robbins_2018.csv")
ROBBINS_INDEX = INDEX_DIR / "robbins_index.npy"

#: [MEASURED] Robbins (2019) states completeness for D >= 1 km.  Below this the
#: system's own detector takes over and its output is labelled as such.
ROBBINS_COMPLETENESS_KM = 1.0

USGS_NOMENCLATURE_URL = "https://planetarynames.wr.usgs.gov/SearchResults"
IAU_INDEX = INDEX_DIR / "iau_nomenclature.json"


# ---------------------------------------------------------------------------
# Crater classification — FORMULAS.md §4.3
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CraterClass:
    key: str
    label: str
    min_km: float
    max_km: float
    colour: str
    basis: str          # the physical/observational transition the edge marks


#: Class edges track documented transitions, not round numbers.  Colours are
#: chosen to remain distinguishable under common colour-vision deficiencies.
CRATER_CLASSES: tuple[CraterClass, ...] = (
    CraterClass("micro", "Micro", 0.0, 0.1, "#9aa0a6",
                "Below LOLA resolution; regolith-scale"),
    CraterClass("very_small", "Very small", 0.1, 1.0, "#8ecae6",
                "Below Robbins completeness limit"),
    CraterClass("small", "Small", 1.0, 15.0, "#219ebc",
                "Simple morphology, bowl-shaped, d/D ~ 0.196"),
    CraterClass("medium", "Medium", 15.0, 50.0, "#2a9d8f",
                "Simple->complex transition: terraces, central peak"),
    CraterClass("large", "Large", 50.0, 200.0, "#e9c46a",
                "Peak-ring onset replaces single central peak"),
    CraterClass("giant", "Giant", 200.0, 300.0, "#f4a261",
                "Peak-ring basin"),
    CraterClass("basin", "Basin", 300.0, float("inf"), "#e76f51",
                "Multi-ring impact basin"),
)

#: [MEASURED] Pike (1974, 1977) depth-diameter fits, d and D in kilometres.
#: Simple:  d = 0.196 * D^1.010     Complex: d = 1.044 * D^0.301
PIKE_SIMPLE = (0.196, 1.010)
PIKE_COMPLEX = (1.044, 0.301)
PIKE_RIM_HEIGHT = (0.036, 1.014)

#: [MEASURED] Simple->complex transition diameter on the Moon [km].
SIMPLE_COMPLEX_TRANSITION_KM = 15.0

#: [MEASURED] Scatter in Pike's fits; reported as an uncertainty band, never
#: suppressed.
PIKE_RELATIVE_UNCERTAINTY = 0.30


# ---------------------------------------------------------------------------
# Rover profiles — FORMULAS.md §6.1, §7.1
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RoverProfile:
    """Mobility envelope of a surface vehicle.

    ``propulsion_power_w`` and ``mu_rolling`` are [ENGINEERING ESTIMATE]:
    published figures for drive-motor power are inconsistent across sources, so
    values here are chosen to reproduce each vehicle's *observed* nominal speed
    on level ground while producing physically sensible slowdown on grades.
    Every other field is [MEASURED] from mission documentation.
    """

    key: str
    name: str
    nominal_speed_ms: float          # commanded speed on level ground
    max_speed_ms: float
    max_slope_deg: float             # sustained gradeability
    tip_over_slope_deg: float        # static stability limit
    ground_clearance_m: float
    wheel_diameter_m: float
    mass_kg: float
    propulsion_power_w: float        # [ENGINEERING ESTIMATE]
    mu_rolling: float                # [ENGINEERING ESTIMATE] regolith
    crewed: bool
    note: str


ROVER_PROFILES: dict[str, RoverProfile] = {
    "viper": RoverProfile(
        key="viper",
        name="VIPER-class polar prospector",
        nominal_speed_ms=0.20, max_speed_ms=0.35,
        max_slope_deg=15.0, tip_over_slope_deg=35.0,
        ground_clearance_m=0.25, wheel_diameter_m=0.50,
        mass_kg=430.0, propulsion_power_w=60.0, mu_rolling=0.25,
        crewed=False,
        note="Four-wheel design sized for polar volatile survey.",
    ),
    "yutu2": RoverProfile(
        key="yutu2",
        name="Yutu-2-class (Chang'e-4)",
        nominal_speed_ms=0.055, max_speed_ms=0.055,
        max_slope_deg=20.0, tip_over_slope_deg=33.0,
        ground_clearance_m=0.20, wheel_diameter_m=0.30,
        mass_kg=140.0, propulsion_power_w=20.0, mu_rolling=0.30,
        crewed=False,
        note="Six-wheel rocker-bogie; demonstrated multi-year farside ops.",
    ),
    "pragyan": RoverProfile(
        key="pragyan",
        name="Pragyan-class (Chandrayaan-3)",
        nominal_speed_ms=0.01, max_speed_ms=0.01,
        max_slope_deg=20.0, tip_over_slope_deg=30.0,
        ground_clearance_m=0.15, wheel_diameter_m=0.20,
        mass_kg=26.0, propulsion_power_w=8.0, mu_rolling=0.30,
        crewed=False,
        note="Small six-wheel rover; operated in the south polar region.",
    ),
    "lrv": RoverProfile(
        key="lrv",
        name="Apollo LRV-class (crewed)",
        nominal_speed_ms=3.60, max_speed_ms=4.50,
        max_slope_deg=20.0, tip_over_slope_deg=45.0,
        ground_clearance_m=0.36, wheel_diameter_m=0.81,
        mass_kg=700.0, propulsion_power_w=1000.0, mu_rolling=0.20,
        crewed=True,
        note="Loaded mass includes crew and equipment. Fastest ever driven.",
    ),
}

DEFAULT_ROVER = "viper"

#: Risk-aversion multiplier gamma in the composite cost (FORMULAS.md §6.4).
#: 0 = fastest route ignoring risk; large = safest ignoring time.
DEFAULT_RISK_AVERSION = 2.0


# ---------------------------------------------------------------------------
# Analysis defaults
# ---------------------------------------------------------------------------

#: Roughness window sizes [pixels]; every product reports the window it used.
ROUGHNESS_WINDOWS = (3, 5, 7)

#: Largest AOI the planner will accept, in cells (SRD SR-N2).
MAX_AOI_CELLS = 1_500 * 1_500


# ---------------------------------------------------------------------------
# Cesium ion — high-detail 3D Tiles terrain
# ---------------------------------------------------------------------------

#: Cesium Moon Terrain: global 3D Tiles built from LRO data by Cesium, with
#: adaptive level of detail.  It subdivides the mesh where the camera is
#: looking, which is why it resolves far more surface detail than a single
#: fixed-resolution relief patch can.
CESIUM_MOON_ASSET = 2684829

def _load_dotenv(path: Path) -> None:
    """Read simple ``KEY=value`` pairs into the environment.

    A deliberate 20 lines rather than a dependency: the format needed here is
    trivial, and python-dotenv would be another compiled-adjacent package on a
    machine where Application Control already blocks several.
    Existing environment variables always win, so a real environment overrides
    the file rather than the other way round.
    """
    if not path.exists():
        return
    # utf-8-sig strips a byte-order mark if present. Windows editors and
    # PowerShell's `Out-File -Encoding utf8` both write one, and it would
    # otherwise become part of the first key's name — the variable then reads
    # as unset with no error anywhere to explain why.
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(PROJECT_ROOT / ".env")


#: Cesium ion access token — read from the environment, never committed.
#:
#: Cesium tokens are read by the browser, so they are unavoidably visible to
#: anyone using a deployed page; that is how the service authenticates. What
#: must not happen is a token entering version control, where it persists in
#: history long after it stops being appropriate to share — and this one is a
#: collaborator's, account-wide and non-expiring, so its exposure would spend
#: someone else's quota.
#:
#: Set it in ``.env`` (gitignored) or as a real environment variable. Absent,
#: the Cesium renderer reports itself unavailable and the Three.js globe is
#: unaffected — a missing credential degrades one view rather than breaking
#: the application.
CESIUM_ION_TOKEN = os.environ.get("CESIUM_ION_TOKEN", "")

#: Pinned CesiumJS release, served from Cesium's CDN.  Pinned rather than
#: "latest" because Moon support and the ellipsoid API have changed across
#: releases, and a silent upgrade could break the lunar frame.
CESIUM_VERSION = "1.126"

#: Cesium requires these credits to be displayed while its assets are streamed.
#: They are a licence condition, not decoration.
CESIUM_ATTRIBUTION = (
    "Cesium Moon Terrain — © Cesium; data from NASA and the "
    "USGS Astrogeology Science Center. Non-commercial use."
)


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

HOST = os.environ.get("LUNARSERPENT_HOST", "127.0.0.1")
PORT = int(os.environ.get("LUNARSERPENT_PORT", "8765"))
API_PREFIX = "/api/v1"
