"""
IAU Gazetteer of Planetary Nomenclature — official lunar feature names.

Why this module exists
----------------------
The Robbins catalogue gives the system 1.3 million craters, but almost none of
them have names: it is a morphometric survey, not a gazetteer.  The IAU
Gazetteer is the complementary source — far smaller (9 086 features) but
carrying the one thing Robbins lacks, the *official* name of a feature, along
with its type, its approval date and the etymology behind the name.

Joining the two is what lets the globe label "Tycho" rather than "08-1-050628".

Format handling
---------------
USGS distributes the gazetteer as an ESRI shapefile.  GDAL/OGR is unavailable
on the target platform, but that turns out not to matter: the attribute table
is a plain dBase III ``.dbf``, which is a documented, trivially-parsable format
(32-byte header, 32-byte field descriptors, fixed-width records).  The parser
below is ~40 lines of ``struct`` and needs no third-party dependency at all.

Coordinates come from the DBF's own ``center_lat``/``center_lon`` columns rather
than the ``.shp`` geometry, because they are the values IAU actually publishes
and are already in the east-positive planetocentric convention this project uses.

Source
------
https://planetarynames.wr.usgs.gov/GIS_Downloads
International Astronomical Union, Working Group for Planetary System
Nomenclature.  Public domain.
"""

from __future__ import annotations

import io
import json
import math
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path

from ..config import CACHE_DIR, INDEX_DIR, R_MOON_M

#: Lunar radius in kilometres — used to convert angular separations to ground
#: distance when joining catalogues.
R_MOON_KM = R_MOON_M / 1000.0

SHAPEFILE_URL = (
    "https://asc-planetarynames-data.s3.us-west-2.amazonaws.com/"
    "MOON_nomenclature_center_pts.zip"
)

_ARCHIVE = CACHE_DIR / "MOON_nomenclature_center_pts.zip"
_INDEX = INDEX_DIR / "iau_nomenclature.json"

CITATION = (
    "IAU Working Group for Planetary System Nomenclature, "
    "Gazetteer of Planetary Nomenclature, USGS Astrogeology Science Center"
)

#: Descriptor term -> short kind used by the interface.
#:
#: This is keyed on the Gazetteer's own ``type`` string rather than its
#: two-letter ``code``, because the type string is self-describing and the codes
#: are not: the Moon's maria carry code ``ME``, which reads naturally as "Mensa"
#: but in fact denotes "Mare, maria".  Keying on a code therefore invites a
#: silent, systematic misclassification of every mare on the Moon.  Keying on
#: the literal descriptor cannot make that mistake, and anything unrecognised
#: falls through to ``other`` where it is visible rather than mislabelled.
_KIND_BY_TYPE = {
    "crater": "crater",
    "satellite feature": "satellite_crater",
    "mare": "mare",
    "oceanus": "oceanus",
    "lacus": "lacus",
    "sinus": "sinus",
    "palus": "palus",
    "planitia": "planitia",
    "terra": "terra",
    "mons": "mons",
    "mensa": "mensa",
    "promontorium": "promontorium",
    "rupes": "rupes",
    "dorsum": "dorsum",
    "rima": "rima",
    "vallis": "vallis",
    "catena": "catena",
    "albedo feature": "albedo",
    "astronaut-named features": "landing_site",
    "statio": "landing_site",
    "landing site name": "landing_site",
}

#: Display styling per kind.  Craters dominate, so they are the neutral colour;
#: the others are tinted so a glance distinguishes basins from rilles.
KIND_STYLE = {
    "crater":           {"label": "Crater",           "colour": "#e8ecf4"},
    "satellite_crater": {"label": "Satellite crater", "colour": "#9aa3b2"},
    "mare":             {"label": "Mare",             "colour": "#7fb3ff"},
    "oceanus":          {"label": "Oceanus",          "colour": "#7fb3ff"},
    "lacus":            {"label": "Lacus",            "colour": "#7fb3ff"},
    "sinus":            {"label": "Sinus",            "colour": "#7fb3ff"},
    "palus":            {"label": "Palus",            "colour": "#7fb3ff"},
    "mons":             {"label": "Mons",             "colour": "#f4a261"},
    "mensa":            {"label": "Mensa",            "colour": "#f4a261"},
    "promontorium":     {"label": "Promontorium",     "colour": "#f4a261"},
    "rupes":            {"label": "Rupes",            "colour": "#e76f51"},
    "dorsum":           {"label": "Dorsum",           "colour": "#e9c46a"},
    "rima":             {"label": "Rima",             "colour": "#a78bfa"},
    "vallis":           {"label": "Vallis",           "colour": "#a78bfa"},
    "catena":           {"label": "Catena",           "colour": "#c084fc"},
    "planitia":         {"label": "Planitia",         "colour": "#7fb3ff"},
    "terra":            {"label": "Terra",            "colour": "#d4d8e0"},
    "albedo":           {"label": "Albedo feature",   "colour": "#9aa3b2"},
    "landing_site":     {"label": "Landing site",     "colour": "#35c48a"},
    "other":            {"label": "Feature",          "colour": "#9aa3b2"},
}


# ---------------------------------------------------------------------------
# dBase III reader
# ---------------------------------------------------------------------------

def _read_dbf(buf: bytes) -> list[dict]:
    """Decode a dBase III table into a list of dicts.

    Layout (per the dBase file-structure specification):
      bytes 4-7   record count (uint32 LE)
      bytes 8-9   header length (uint16 LE)
      bytes 10-11 record length (uint16 LE)
      byte 32..   32-byte field descriptors, terminated by 0x0D
      then        fixed-width records, each prefixed by a deletion flag byte
    """
    n_rec, hdr_len, rec_len = struct.unpack("<IHH", buf[4:12])

    fields: list[tuple[str, str, int]] = []
    off = 32
    while off < len(buf) and buf[off] != 0x0D:
        raw = buf[off:off + 32]
        name = raw[:11].split(b"\0")[0].decode("latin-1")
        fields.append((name, chr(raw[11]), raw[16]))
        off += 32

    out: list[dict] = []
    pos = hdr_len
    for _ in range(n_rec):
        rec = buf[pos:pos + rec_len]
        pos += rec_len
        if len(rec) < rec_len or rec[:1] == b"*":  # deleted
            continue
        o = 1
        row: dict = {}
        for name, ftype, flen in fields:
            val = rec[o:o + flen].decode("utf-8", "replace").strip()
            o += flen
            if ftype == "N":
                try:
                    row[name] = float(val) if val else None
                except ValueError:
                    row[name] = None
            else:
                row[name] = val
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def index_exists() -> bool:
    return _INDEX.exists()


def build_index(force: bool = False, progress: bool = True) -> dict:
    """Fetch the gazetteer and write a compact JSON index."""
    import requests

    if _INDEX.exists() and not force:
        return json.loads(_INDEX.read_text(encoding="utf-8"))["meta"]

    if not _ARCHIVE.exists() or force:
        if progress:
            print(f"downloading {SHAPEFILE_URL}")
        r = requests.get(SHAPEFILE_URL, timeout=600,
                         headers={"User-Agent": "LunarSerpent/0.5"})
        r.raise_for_status()
        _ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
        _ARCHIVE.write_bytes(r.content)

    z = zipfile.ZipFile(io.BytesIO(_ARCHIVE.read_bytes()))
    dbf = next(n for n in z.namelist() if n.lower().endswith(".dbf"))
    rows = _read_dbf(z.read(dbf))

    features = []
    by_kind: dict[str, int] = {}
    #: Descriptor terms with no mapping.  Surfaced in the build metadata so a
    #: new IAU feature type shows up as a known gap rather than vanishing into
    #: "other" unnoticed.
    unmapped: dict[str, int] = {}
    skipped = 0

    for r in rows:
        lat, lon = r.get("center_lat"), r.get("center_lon")
        name = (r.get("clean_name") or r.get("name") or "").strip()
        if lat is None or lon is None or not name:
            skipped += 1
            continue

        # "Mare, maria" -> "Mare"; "Crater, craters" -> "Crater".
        type_label = (r.get("type") or "").split(",")[0].strip()
        kind = _KIND_BY_TYPE.get(type_label.casefold(), "other")
        if kind == "other" and type_label:
            unmapped[type_label] = unmapped.get(type_label, 0) + 1
        by_kind[kind] = by_kind.get(kind, 0) + 1

        approval = (r.get("approvaldt") or "")[:4]
        features.append({
            "n": name,
            "t": kind,
            "ty": type_label,
            "la": round(float(lat), 5),
            "lo": round(float(lon) % 360.0, 5),
            "d": round(float(r["diameter"]), 3) if r.get("diameter") else None,
            "o": (r.get("origin") or "").strip() or None,
            "y": int(approval) if approval.isdigit() else None,
            "q": (r.get("quad_code") or "").strip() or None,
            "u": (r.get("link") or "").strip() or None,
        })

    # Largest first: the globe draws a bounded number of labels, and the most
    # significant features must survive truncation.
    features.sort(key=lambda f: -(f["d"] or 0.0))

    meta = {
        "source": SHAPEFILE_URL,
        "citation": CITATION,
        "n_features": len(features),
        "n_skipped": skipped,
        "by_kind": dict(sorted(by_kind.items(), key=lambda kv: -kv[1])),
        "unmapped_types": dict(sorted(unmapped.items(), key=lambda kv: -kv[1])),
        "largest": features[0]["n"] if features else None,
    }

    _INDEX.parent.mkdir(parents=True, exist_ok=True)
    _INDEX.write_text(
        json.dumps({"meta": meta, "features": features}, ensure_ascii=False),
        encoding="utf-8",
    )
    return meta


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

@dataclass
class NamedFeature:
    name: str
    kind: str
    type_label: str
    lat: float
    lon: float
    diameter_km: float | None
    origin: str | None
    approval_year: int | None
    quad: str | None
    url: str | None

    @property
    def area_km2(self) -> float | None:
        if not self.diameter_km:
            return None
        return math.pi * (self.diameter_km / 2.0) ** 2

    def to_dict(self) -> dict:
        style = KIND_STYLE.get(self.kind, KIND_STYLE["other"])
        return {
            "name": self.name,
            "kind": self.kind,
            "kind_label": style["label"],
            "type": self.type_label,
            "colour": style["colour"],
            "lat": self.lat,
            "lon": self.lon,
            "diameter_km": self.diameter_km,
            "area_km2": round(self.area_km2, 2) if self.area_km2 else None,
            "origin": self.origin,
            "approval_year": self.approval_year,
            "quad": self.quad,
            "url": self.url,
            "source": "IAU Gazetteer of Planetary Nomenclature",
        }


class NomenclatureIndex:
    """In-memory query interface. The whole gazetteer is only ~9 000 rows."""

    def __init__(self):
        if not _INDEX.exists():
            raise FileNotFoundError(
                "IAU nomenclature index not built. Run: "
                "python -m backend.data.nomenclature --build"
            )
        blob = json.loads(_INDEX.read_text(encoding="utf-8"))
        self.meta = blob["meta"]
        self._f = blob["features"]
        self._crater_arrays = None   # built lazily, only if matching is used

    def __len__(self) -> int:
        return len(self._f)

    @staticmethod
    def _mk(f: dict) -> NamedFeature:
        return NamedFeature(
            name=f["n"], kind=f["t"], type_label=f["ty"],
            lat=f["la"], lon=f["lo"], diameter_km=f["d"],
            origin=f["o"], approval_year=f["y"], quad=f["q"], url=f["u"],
        )

    def all(self) -> list[NamedFeature]:
        return [self._mk(f) for f in self._f]

    def query(self, *, south=-90.0, north=90.0, west=0.0, east=360.0,
              min_diameter_km: float = 0.0, kinds: set[str] | None = None,
              limit: int | None = None) -> list[NamedFeature]:
        """Named features in a window, largest first."""
        full_lon = abs(east - west) >= 360.0
        w, e = west % 360.0, east % 360.0
        out = []
        for f in self._f:                      # already sorted by size
            if not (south <= f["la"] <= north):
                continue
            if not full_lon and w != e:
                lo = f["lo"]
                inside = (w <= lo <= e) if w < e else (lo >= w or lo <= e)
                if not inside:
                    continue
            if min_diameter_km and (f["d"] or 0.0) < min_diameter_km:
                continue
            if kinds and f["t"] not in kinds:
                continue
            out.append(self._mk(f))
            if limit and len(out) >= limit:
                break
        return out

    # -- joining a measured catalogue to official names ----------------------

    def _craters(self):
        """NumPy view over crater-like features, for vectorised matching."""
        if self._crater_arrays is None:
            import numpy as np

            rows = [(i, f) for i, f in enumerate(self._f)
                    if f["t"] in ("crater", "satellite_crater") and f["d"]]
            self._crater_arrays = (
                np.array([f["la"] for _, f in rows], dtype=np.float64),
                np.array([f["lo"] for _, f in rows], dtype=np.float64),
                np.array([f["d"] for _, f in rows], dtype=np.float64),
                np.array([i for i, _ in rows], dtype=np.int64),
            )
        return self._crater_arrays

    def match_crater(self, lat: float, lon: float, diameter_km: float,
                     pos_tol: float = 0.40,
                     diam_tol: float = 0.50) -> NamedFeature | None:
        """Find the official name of a catalogued crater, if it has one.

        The Robbins catalogue is a morphometric survey: it measures 1.3 million
        craters but names almost none of them.  The IAU gazetteer names ~1 600.
        Joining the two is what turns ``06-1-001099`` into ``Taruntius``.

        There is no shared key between the catalogues, so the join is spatial:
        a Robbins crater is identified with an IAU feature when their centres
        agree to within ``pos_tol`` of the crater radius *and* their diameters
        agree to within ``diam_tol``.  Requiring both guards against the obvious
        failure mode — a small crater sitting inside a large named one would
        satisfy the position test alone and inherit the wrong name.

        Where several candidates qualify, the closest in *relative* diameter
        wins, since two concentric craters are distinguished by size, not place.
        """
        import numpy as np

        if diameter_km <= 0:
            return None
        clat, clon, cdiam, cidx = self._craters()
        if clat.size == 0:
            return None

        lon %= 360.0
        dlat = clat - lat
        dlon = (clon - lon + 180.0) % 360.0 - 180.0
        dlon *= math.cos(math.radians(lat))
        sep_deg = np.hypot(dlat, dlon)

        # Convert the separation tolerance from km to degrees of arc.
        km_per_deg = math.pi * R_MOON_KM / 180.0
        sep_km = sep_deg * km_per_deg

        ok = (sep_km <= pos_tol * (diameter_km / 2.0)) & \
             (np.abs(cdiam - diameter_km) <= diam_tol * diameter_km)
        if not ok.any():
            return None

        cand = np.flatnonzero(ok)
        best = cand[np.argmin(np.abs(cdiam[cand] - diameter_km) / diameter_km)]
        return self._mk(self._f[int(cidx[best])])

    def by_name(self, name: str) -> NamedFeature | None:
        key = name.strip().casefold()
        for f in self._f:
            if f["n"].casefold() == key:
                return self._mk(f)
        return None

    def search(self, text: str, limit: int = 20) -> list[NamedFeature]:
        key = text.strip().casefold()
        if not key:
            return []
        starts, contains = [], []
        for f in self._f:
            nm = f["n"].casefold()
            if nm.startswith(key):
                starts.append(f)
            elif key in nm:
                contains.append(f)
            if len(starts) >= limit:
                break
        return [self._mk(f) for f in (starts + contains)[:limit]]

    def nearest(self, lat: float, lon: float,
                max_km: float | None = None,
                kinds: set[str] | None = None) -> NamedFeature | None:
        """Nearest named feature centre, weighted so a point inside a large
        feature prefers that feature over a tiny one slightly closer."""
        from ..config import R_MOON_M
        best, best_d = None, float("inf")
        lon %= 360.0
        for f in self._f:
            if kinds and f["t"] not in kinds:
                continue
            dlat = f["la"] - lat
            dlon = (f["lo"] - lon + 180.0) % 360.0 - 180.0
            dlon *= math.cos(math.radians(lat))
            d = math.hypot(dlat, dlon)
            if d < best_d:
                best_d, best = d, f
        if best is None:
            return None
        if max_km is not None:
            km = best_d * (math.pi * R_MOON_M / 180.0) / 1000.0
            if km > max_km:
                return None
        return self._mk(best)

    def containing(self, lat: float, lon: float) -> list[NamedFeature]:
        """Named features whose published radius encloses the point."""
        from ..config import R_MOON_M
        lon %= 360.0
        hits = []
        for f in self._f:
            if not f["d"]:
                continue
            dlat = f["la"] - lat
            dlon = (f["lo"] - lon + 180.0) % 360.0 - 180.0
            dlon *= math.cos(math.radians(lat))
            deg = math.hypot(dlat, dlon)
            km = deg * (math.pi * R_MOON_M / 180.0) / 1000.0
            if km <= f["d"] / 2.0:
                hits.append((f["d"], f))
        hits.sort()                      # smallest (most local) first
        return [self._mk(f) for _, f in hits]


_cache: NomenclatureIndex | None = None


def load_index() -> NomenclatureIndex:
    global _cache
    if _cache is None:
        _cache = NomenclatureIndex()
    return _cache


# ---------------------------------------------------------------------------
# CLI
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

    idx = load_index()
    print(f"\nIAU nomenclature: {len(idx):,} features")
    for k, v in list(idx.meta["by_kind"].items())[:8]:
        print(f"    {k:<18} {v:>5}")
    print()

    check("feature count plausible", 8000 < len(idx) < 12000, f"{len(idx):,}")

    # Well-known craters, coordinates from the IAU Gazetteer itself.
    for nm, la, lo, dm in [
        ("Tycho", -43.31, 348.68, 85.0),
        ("Copernicus", 9.62, 339.92, 96.0),
        ("Clavius", -58.62, 345.32, 231.0),
        ("Plato", 51.62, 350.63, 100.0),
        ("Shackleton", -89.66, 129.20, 21.0),
    ]:
        f = idx.by_name(nm)
        if f is None:
            check(f"{nm} present", False)
            continue
        dlat = abs(f.lat - la)
        dlon = abs(((f.lon - lo + 180) % 360) - 180)
        check(f"{nm:<12} {f.lat:>7.2f} {f.lon:>7.2f}  D={f.diameter_km:.1f} km",
              dlat < 1.0 and dlon < 1.0 and abs(f.diameter_km - dm) < 0.25 * dm)

    big = idx.query(min_diameter_km=200, limit=5)
    check("large features found", len(big) == 5,
          ", ".join(f"{f.name} ({f.diameter_km:.0f} km)" for f in big[:3]))

    hits = idx.search("apoll", limit=5)
    check("prefix search works", len(hits) > 0,
          ", ".join(h.name for h in hits[:3]))

    enc = idx.containing(-43.31, 348.68)
    check("Tycho encloses its own centre",
          any(f.name == "Tycho" for f in enc), f"{len(enc)} enclosing")

    landing = idx.query(kinds={"landing_site"}, limit=100)
    check("landing sites catalogued", len(landing) > 0,
          f"{len(landing)} sites incl. " +
          ", ".join(f.name for f in landing[:2]))

    # ── Classification integrity ──────────────────────────────────────────
    # Regression guard: the maria were once mapped through the two-letter code
    # ``ME``, which reads as "Mensa" but denotes "Mare", silently misclassifying
    # every mare on the Moon.  Assert the kind directly against the descriptor.
    print()
    mismatched = [f for f in idx.all()
                  if f.kind not in ("other", "satellite_crater", "landing_site")
                  and f.kind.split("_")[0][:4] not in f.type_label.casefold()]
    check("every kind agrees with its IAU descriptor",
          not mismatched,
          f"{len(mismatched)} mismatched" if mismatched else "all consistent")

    for nm, want in [("Mare Imbrium", "mare"),
                     ("Oceanus Procellarum", "oceanus"),
                     ("Tycho", "crater"),
                     ("Vallis Alpes", "vallis"),
                     ("Montes Apenninus", "mons")]:
        f = idx.by_name(nm)
        check(f"{nm:<22} -> {want}",
              f is not None and f.kind == want,
              f"got '{f.kind}' (IAU type '{f.type_label}')" if f else "not found")

    unmapped = idx.meta.get("unmapped_types", {})
    check("no unmapped descriptor terms", not unmapped,
          str(unmapped) if unmapped else "all descriptors recognised")

    print(f"\n{npass} passed, {nfail} failed")
    return 1 if nfail else 0


if __name__ == "__main__":
    import sys

    if "--build" in sys.argv:
        meta = build_index(force="--force" in sys.argv)
        print(json.dumps(meta, indent=2, ensure_ascii=False))
    else:
        raise SystemExit(_self_test())
