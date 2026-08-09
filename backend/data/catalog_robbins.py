"""
Robbins (2019) global lunar crater database — index builder and query engine.

The source is a 227 MB CSV of 2 033 574 craters.  Re-parsing that on every
request is untenable (tens of seconds), and loading it whole costs hundreds of
megabytes of RAM, so it is converted **once** into a set of memory-mapped NumPy
columns (SRD SR-D6).  Thereafter a bounding-box query is a vectorised mask over
two 8 MB arrays — a few milliseconds, with no parse step and no RAM cost beyond
the pages actually touched.

Storage is **columnar**, not row-structured, deliberately: a spatial query reads
only ``lat`` and ``lon``.  A row-structured array would force every query to
page in diameter, ellipticity, arc fraction and the ID string as well —
roughly four times the I/O for the same answer.

Provenance
----------
Robbins, S. J. (2019), *A New Global Database of Lunar Impact Craters >1-2 km*,
JGR Planets 124(4), 871-892.  doi:10.1029/2018JE005592

The catalogue is **complete for D >= 1 km** and every crater in it was
identified manually.  LunarSerpent therefore treats it as ground truth at that
size and above, and applies its own detector only *below* the completeness
limit (see ``docs/DATASETS.md`` §5.1).
"""

from __future__ import annotations

import csv
import json
import sys
import time
from dataclasses import dataclass

import numpy as np

from ..config import (
    CRATER_CLASSES,
    INDEX_DIR,
    ROBBINS_COMPLETENESS_KM,
    ROBBINS_CSV,
    dataset_path,
)

__all__ = ["RobbinsIndex", "build_index", "load_index", "index_exists"]

#: Source column names, from the CSV header.
COL_ID = "CRATER_ID"
COL_LAT = "LAT_CIRC_IMG"
COL_LON = "LON_CIRC_IMG"
COL_DIAM = "DIAM_CIRC_IMG"
COL_ELLIP = "DIAM_ELLI_ELLIP_IMG"
COL_ARC = "ARC_IMG"

#: Circle-fit centre and diameter are used rather than the ellipse fit: they are
#: defined for every crater in the catalogue, whereas the ellipse fit requires
#: enough traced rim to constrain five parameters and is absent for the most
#: poorly-preserved features.  Ellipticity is carried separately as a shape
#: descriptor.

_COLUMNS = {
    "lat": ("robbins_lat.npy", "<f4"),
    "lon": ("robbins_lon.npy", "<f4"),
    "diam_km": ("robbins_diam.npy", "<f4"),
    "ellipticity": ("robbins_ellip.npy", "<f4"),
    "arc_frac": ("robbins_arc.npy", "<f4"),
    "class_id": ("robbins_class.npy", "|u1"),
}
_ID_FILE = "robbins_id.npy"
_META_FILE = "robbins_meta.json"

_CHUNK = 200_000


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_diameters(diam_km: np.ndarray) -> np.ndarray:
    """Assign a class index per ``config.CRATER_CLASSES`` (FORMULAS.md §4.3).

    Boundaries track documented morphological transitions, not round numbers:
    1 km is the catalogue completeness limit, 15 km the simple->complex
    transition, ~50 km peak-ring onset, ~300 km multi-ring basins.
    """
    out = np.zeros(diam_km.shape, dtype=np.uint8)
    for i, c in enumerate(CRATER_CLASSES):
        np.putmask(out, (diam_km >= c.min_km) & (diam_km < c.max_km), i)
    return out


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def index_exists() -> bool:
    return (INDEX_DIR / _META_FILE).exists() and all(
        (INDEX_DIR / f).exists() for f, _ in _COLUMNS.values()
    )


def build_index(force: bool = False, progress: bool = True) -> dict:
    """Stream the CSV into memory-mappable columns.

    The file is never held in memory: rows accumulate in fixed-size chunks that
    are converted to NumPy and concatenated at the end, so peak RAM is bounded
    by ``_CHUNK`` rather than by the catalogue size.

    Returns the metadata dictionary that is also written to disk.
    """
    if index_exists() and not force:
        return json.loads((INDEX_DIR / _META_FILE).read_text(encoding="utf-8"))

    src = dataset_path(*ROBBINS_CSV)
    if src is None:
        raise FileNotFoundError(
            f"Robbins CSV not found at <data root>/{'/'.join(ROBBINS_CSV)}. "
            "Is the Drive mounted?"
        )

    t0 = time.time()
    size_mb = src.stat().st_size / 1024 / 1024
    if progress:
        print(f"Building Robbins index from {src.name} ({size_mb:.1f} MB)")

    chunks: dict[str, list[np.ndarray]] = {
        "lat": [], "lon": [], "diam_km": [], "ellipticity": [], "arc_frac": [],
    }
    id_chunks: list[np.ndarray] = []
    buf: list[tuple] = []
    n_rows = n_bad = 0

    def flush():
        nonlocal buf
        if not buf:
            return
        a = np.array(buf, dtype=object)
        id_chunks.append(np.asarray(a[:, 0], dtype="S12"))
        for j, name in enumerate(
            ("lat", "lon", "diam_km", "ellipticity", "arc_frac"), start=1
        ):
            chunks[name].append(np.asarray(a[:, j], dtype=np.float32))
        buf = []

    # newline='' per the csv module contract; latin-1 tolerates any stray bytes
    # in a 227 MB file without aborting the whole build.
    with src.open("r", encoding="latin-1", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = {COL_ID, COL_LAT, COL_LON, COL_DIAM} - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV is missing expected columns: {sorted(missing)}")

        for row in reader:
            try:
                buf.append((
                    row[COL_ID],
                    float(row[COL_LAT]),
                    float(row[COL_LON]),
                    float(row[COL_DIAM]),
                    float(row.get(COL_ELLIP) or "nan"),
                    float(row.get(COL_ARC) or "nan"),
                ))
                n_rows += 1
            except (ValueError, TypeError, KeyError):
                n_bad += 1
                continue

            if len(buf) >= _CHUNK:
                flush()
                if progress:
                    print(f"  {n_rows:>9,} rows", end="\r", flush=True)
    flush()

    if n_rows == 0:
        raise ValueError("no parseable rows found in the Robbins CSV")

    lat = np.concatenate(chunks["lat"])
    lon = np.mod(np.concatenate(chunks["lon"]), 360.0).astype(np.float32)
    diam = np.concatenate(chunks["diam_km"])
    ellip = np.concatenate(chunks["ellipticity"])
    arc = np.concatenate(chunks["arc_frac"])
    ids = np.concatenate(id_chunks)

    # Sort by diameter descending.  The globe renders the largest craters first
    # at low zoom, so a top-N query becomes a prefix slice rather than a sort.
    order = np.argsort(-diam, kind="stable")
    lat, lon, diam = lat[order], lon[order], diam[order]
    ellip, arc, ids = ellip[order], arc[order], ids[order]
    cls = classify_diameters(diam)

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    for name, arr in (("lat", lat), ("lon", lon), ("diam_km", diam),
                      ("ellipticity", ellip), ("arc_frac", arc),
                      ("class_id", cls)):
        np.save(INDEX_DIR / _COLUMNS[name][0], arr)
    np.save(INDEX_DIR / _ID_FILE, ids)

    written = sum(
        (INDEX_DIR / f).stat().st_size for f, _ in _COLUMNS.values()
    ) + (INDEX_DIR / _ID_FILE).stat().st_size

    meta = {
        "source_file": src.name,
        "source_mb": round(size_mb, 1),
        "index_mb": round(written / 1024 / 1024, 1),
        "n_craters": int(n_rows),
        "n_unparseable": int(n_bad),
        "n_ge_1km": int((diam >= 1.0).sum()),
        "n_ge_5km": int((diam >= 5.0).sum()),
        "n_ge_20km": int((diam >= 20.0).sum()),
        "diam_min_km": float(diam.min()),
        "diam_max_km": float(diam.max()),
        "completeness_km": ROBBINS_COMPLETENESS_KM,
        "citation": "Robbins, S. J. (2019), JGR Planets 124, 871-892, "
                    "doi:10.1029/2018JE005592",
        "built_seconds": round(time.time() - t0, 1),
    }
    (INDEX_DIR / _META_FILE).write_text(json.dumps(meta, indent=2), encoding="utf-8")

    if progress:
        print(f"  {n_rows:>9,} rows        ")
        print(f"  {size_mb:.0f} MB CSV -> {meta['index_mb']} MB index "
              f"in {meta['built_seconds']} s")
    return meta


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

@dataclass
class Crater:
    """One catalogue entry."""

    id: str
    lat: float
    lon: float
    diameter_km: float
    ellipticity: float
    arc_fraction: float
    class_key: str
    class_label: str
    colour: str

    @property
    def radius_km(self) -> float:
        return self.diameter_km / 2.0

    @property
    def area_km2(self) -> float:
        return float(np.pi * self.radius_km ** 2)

    @property
    def is_authoritative(self) -> bool:
        """True where the catalogue is complete, so the entry is ground truth."""
        return self.diameter_km >= ROBBINS_COMPLETENESS_KM

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "lat": round(self.lat, 5),
            "lon": round(self.lon, 5),
            "diameter_km": round(self.diameter_km, 4),
            "radius_km": round(self.radius_km, 4),
            "area_km2": round(self.area_km2, 3),
            "ellipticity": None if np.isnan(self.ellipticity)
                           else round(self.ellipticity, 4),
            "arc_fraction": None if np.isnan(self.arc_fraction)
                            else round(self.arc_fraction, 4),
            "class": self.class_key,
            "class_label": self.class_label,
            "colour": self.colour,
            "source": "Robbins 2019",
            "authoritative": self.is_authoritative,
        }


class RobbinsIndex:
    """Memory-mapped query interface over the built index."""

    def __init__(self):
        if not index_exists():
            raise FileNotFoundError(
                "Robbins index not built. Run: "
                "python -m backend.data.catalog_robbins --build"
            )
        self.meta = json.loads((INDEX_DIR / _META_FILE).read_text(encoding="utf-8"))
        self.lat = np.load(INDEX_DIR / _COLUMNS["lat"][0], mmap_mode="r")
        self.lon = np.load(INDEX_DIR / _COLUMNS["lon"][0], mmap_mode="r")
        self.diam = np.load(INDEX_DIR / _COLUMNS["diam_km"][0], mmap_mode="r")
        self.ellip = np.load(INDEX_DIR / _COLUMNS["ellipticity"][0], mmap_mode="r")
        self.arc = np.load(INDEX_DIR / _COLUMNS["arc_frac"][0], mmap_mode="r")
        self.cls = np.load(INDEX_DIR / _COLUMNS["class_id"][0], mmap_mode="r")
        self._ids = None  # 15 MB of strings; loaded only when an ID is needed

    def __len__(self) -> int:
        return int(self.lat.shape[0])

    @property
    def ids(self) -> np.ndarray:
        if self._ids is None:
            self._ids = np.load(INDEX_DIR / _ID_FILE, mmap_mode="r")
        return self._ids

    # -- queries ------------------------------------------------------------

    def _mask_bbox(self, lat_south, lat_north, lon_west, lon_east):
        m = (self.lat >= lat_south) & (self.lat <= lat_north)

        # A span of a full turn (or more) selects every longitude.  This must be
        # tested *before* reducing modulo 360, because the natural way to write
        # "the whole globe" is west=0, east=360, and 360 % 360 == 0 would
        # otherwise collapse the window to a zero-width sliver at the prime
        # meridian rather than opening it to everything.
        if abs(lon_east - lon_west) >= 360.0:
            return m

        w = lon_west % 360.0
        e = lon_east % 360.0
        if w == e:
            return m  # degenerate after reduction: also a full turn
        if w < e:
            m &= (self.lon >= w) & (self.lon <= e)
        else:  # window crosses the 0/360 seam
            m &= (self.lon >= w) | (self.lon <= e)
        return m

    def query_bbox(self, lat_south: float, lat_north: float,
                   lon_west: float, lon_east: float,
                   min_diameter_km: float = 0.0,
                   limit: int | None = None) -> list[Crater]:
        """Craters within a bounding box, largest first.

        Because the index is sorted by descending diameter, truncating to
        ``limit`` yields the *most significant* craters in view rather than an
        arbitrary subset — which is what the globe needs when zoomed out.
        """
        m = self._mask_bbox(lat_south, lat_north, lon_west, lon_east)
        if min_diameter_km > 0:
            m &= self.diam >= min_diameter_km
        idx = np.flatnonzero(m)
        if limit is not None and idx.size > limit:
            idx = idx[:limit]
        return [self._row(int(i)) for i in idx]

    def count_bbox(self, lat_south, lat_north, lon_west, lon_east,
                   min_diameter_km: float = 0.0) -> int:
        """Count without materialising objects — for density statistics."""
        m = self._mask_bbox(lat_south, lat_north, lon_west, lon_east)
        if min_diameter_km > 0:
            m &= self.diam >= min_diameter_km
        return int(m.sum())

    def largest(self, n: int = 50, min_diameter_km: float = 0.0) -> list[Crater]:
        """The ``n`` largest craters — a prefix slice, no scan required."""
        if min_diameter_km > 0:
            idx = np.flatnonzero(self.diam >= min_diameter_km)[:n]
        else:
            idx = np.arange(min(n, len(self)))
        return [self._row(int(i)) for i in idx]

    def nearest(self, lat: float, lon: float,
                max_distance_km: float | None = None) -> Crater | None:
        """Nearest catalogue crater centre to a coordinate.

        Uses a flat-metric approximation with a ``cos(lat)`` correction on the
        longitude term.  That is adequate here because it is only used to *rank*
        candidates over short separations; the exact geodesic
        (``selenographic.haversine_distance``) is used wherever a reported
        distance matters.
        """
        from ..config import R_MOON_M

        dlat = np.asarray(self.lat, dtype=np.float32) - lat
        dlon = (np.asarray(self.lon, dtype=np.float32) - (lon % 360.0) + 180.0) % 360.0 - 180.0
        dlon *= np.cos(np.radians(lat))
        d2 = dlat * dlat + dlon * dlon
        i = int(np.argmin(d2))

        if max_distance_km is not None:
            deg = float(np.sqrt(d2[i]))
            km = deg * (np.pi * R_MOON_M / 180.0) / 1000.0
            if km > max_distance_km:
                return None
        return self._row(i)

    def containing(self, lat: float, lon: float) -> list[Crater]:
        """Craters whose rim encloses the point, smallest (most local) first.

        A point on the Moon typically lies inside several nested craters; the
        smallest is the one whose terrain dominates locally.
        """
        from ..core.selenographic import haversine_distance
        from ..config import R_MOON_M

        # Only craters big enough to possibly reach the point need testing.
        cand = np.flatnonzero(
            (np.abs(np.asarray(self.lat) - lat) < 15.0) & (self.diam > 0)
        )
        out = []
        for i in cand:
            d_m = float(haversine_distance(lat, lon, float(self.lat[i]),
                                           float(self.lon[i])))
            if d_m <= float(self.diam[i]) * 500.0:  # radius in metres
                out.append((float(self.diam[i]), int(i)))
        out.sort()
        return [self._row(i) for _, i in out]

    def get(self, crater_id: str) -> Crater | None:
        hit = np.flatnonzero(self.ids == crater_id.encode())
        return self._row(int(hit[0])) if hit.size else None

    # -- helpers ------------------------------------------------------------

    def _row(self, i: int) -> Crater:
        c = CRATER_CLASSES[int(self.cls[i])]
        return Crater(
            id=self.ids[i].decode(),
            lat=float(self.lat[i]),
            lon=float(self.lon[i]),
            diameter_km=float(self.diam[i]),
            ellipticity=float(self.ellip[i]),
            arc_fraction=float(self.arc[i]),
            class_key=c.key,
            class_label=c.label,
            colour=c.colour,
        )

    def class_histogram(self) -> dict[str, int]:
        counts = np.bincount(np.asarray(self.cls), minlength=len(CRATER_CLASSES))
        return {c.key: int(counts[i]) for i, c in enumerate(CRATER_CLASSES)}

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RobbinsIndex {len(self):,} craters, {self.meta['index_mb']} MB>"


_INDEX: RobbinsIndex | None = None


def load_index() -> RobbinsIndex:
    """Process-wide singleton — the memmaps are opened once."""
    global _INDEX
    if _INDEX is None:
        _INDEX = RobbinsIndex()
    return _INDEX


# ---------------------------------------------------------------------------
# Self-verification
# ---------------------------------------------------------------------------

def _self_test() -> int:
    failures = 0

    def check(name, ok, detail=""):
        nonlocal failures
        failures += 0 if ok else 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}{'  ' + detail if detail else ''}")

    if not index_exists():
        print("Index not built; building now...")
        build_index()

    idx = load_index()
    print(f"\n{idx!r}")
    m = idx.meta
    print(f"  {m['source_mb']} MB CSV -> {m['index_mb']} MB index "
          f"({m['built_seconds']} s build)\n")

    print("Catalogue totals vs Robbins (2019) published counts")
    # The PDS *release* is the D >= 1 km subset (1,296,879 craters), not the
    # full 2,033,574 measured in the paper -- the sub-kilometre population was
    # not released.  Confirmed independently below: the micro and very_small
    # classes are empty.
    check("total ~1,296,879 (the released D>=1 km subset)",
          abs(len(idx) - 1_296_879) < 5_000, f"{len(idx):,}")
    check("D>=5 km ~83,000", abs(m["n_ge_5km"] - 83_000) < 5_000,
          f"{m['n_ge_5km']:,}")
    check("D>=20 km ~6,972", abs(m["n_ge_20km"] - 6_972) < 300,
          f"{m['n_ge_20km']:,}")
    check("no unparseable rows", m["n_unparseable"] == 0,
          f"{m['n_unparseable']}")
    check("minimum diameter ~1 km (confirms the >=1 km subset)",
          0.9 <= m["diam_min_km"] <= 1.2, f"{m['diam_min_km']:.3f} km")

    print("\nSorted largest-first")
    big = idx.largest(3)
    check("sorted descending",
          big[0].diameter_km >= big[1].diameter_km >= big[2].diameter_km,
          " > ".join(f"{c.diameter_km:.0f}" for c in big))
    # The largest entry should be South Pole-Aitken: ~2500 km near (53S, 170E),
    # the largest confirmed impact structure on the Moon.
    check("largest is South Pole-Aitken (~2500 km near 53S)",
          big[0].diameter_km > 2000 and big[0].lat < -40,
          f"{big[0].diameter_km:.1f} km at "
          f"({big[0].lat:.2f}, {big[0].lon:.2f})")

    print("\nKnown-feature spot checks")
    # Mare Orientale: ~19.9S, 265.3E, ~930 km.  `nearest` finds the closest
    # crater *centre*, which for a huge basin is almost always some small
    # crater superposed on it -- so search the region for the largest instead.
    box = idx.query_bbox(-35, -5, 250, 280, min_diameter_km=400.0)
    check("Orientale-scale basin in region (19.9S,265.3E)",
          len(box) > 0 and box[0].diameter_km > 400,
          f"{box[0].diameter_km:.0f} km at ({box[0].lat:.2f}, {box[0].lon:.2f})"
          if box else "none found")
    # Tycho: 43.31S, 348.64E, 85 km
    ty = idx.nearest(-43.31, 348.64, max_distance_km=50)
    check("Tycho-sized crater near (43.31S,348.64E)",
          ty is not None and 70 < ty.diameter_km < 100,
          f"{ty.diameter_km:.1f} km" if ty else "not found")
    # Copernicus: 9.62N, 339.92E, 93 km
    cop = idx.nearest(9.62, 339.92, max_distance_km=50)
    check("Copernicus-sized crater near (9.62N,339.92E)",
          cop is not None and 80 < cop.diameter_km < 105,
          f"{cop.diameter_km:.1f} km" if cop else "not found")

    print("\nSpatial query")
    t0 = time.time()
    box = idx.query_bbox(-10, 10, 20, 40, min_diameter_km=5.0)
    dt = (time.time() - t0) * 1000
    check("bbox query returns results", len(box) > 0, f"{len(box)} craters")
    check("all within latitude bounds",
          all(-10 <= c.lat <= 10 for c in box))
    check("all within longitude bounds",
          all(20 <= c.lon <= 40 for c in box))
    check("all above min diameter", all(c.diameter_km >= 5.0 for c in box))
    check("query fast (<500 ms, SRD SR-N1)", dt < 500, f"{dt:.0f} ms")

    print("\nAntimeridian-crossing query")
    seam = idx.query_bbox(-5, 5, 355, 5, min_diameter_km=10.0)
    check("seam query returns results", len(seam) > 0, f"{len(seam)} craters")
    check("all near the seam",
          all(c.lon >= 355 or c.lon <= 5 for c in seam))

    print("\nClassification (FORMULAS.md §4.3)")
    hist = idx.class_histogram()
    for k, v in hist.items():
        print(f"    {k:<12} {v:>10,}")
    check("classes sum to total", sum(hist.values()) == len(idx))
    check("small class is largest population",
          hist["small"] > 0 and hist["basin"] < hist["small"])

    print("\nID round-trip")
    got = idx.get(big[0].id)
    check("lookup by ID", got is not None and got.id == big[0].id, big[0].id)

    print(f"\n{'ALL CHECKS PASSED' if failures == 0 else f'{failures} FAILURE(S)'}")
    return failures


if __name__ == "__main__":
    if "--build" in sys.argv:
        meta = build_index(force="--force" in sys.argv)
        print(json.dumps(meta, indent=2))
        raise SystemExit(0)
    raise SystemExit(_self_test())
