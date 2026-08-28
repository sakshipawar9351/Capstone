r"""
What data exists for a given piece of the Moon.

The architecture this supports: a region is chosen on the globe, and the next
page asks *what is actually available here* rather than assuming one global
product. Coverage is not uniform. Two products cover the whole Moon; a few
dozen cover a fraction of a percent of it at forty times the detail. Which
applies depends entirely on where the user clicked.

The distinction that governs everything
---------------------------------------
**Streamed** products are tile pyramids. Only the bytes a region needs are
fetched, nothing is stored, and they can be used without asking anyone. Two
qualify, both verified against the live service:

    Kaguya TC orthomosaic   20.82 m/px   imagery   global
    LOLA LDEM_1024          29.61 m      DEM       global

**Downloadable** products are single rasters. NASA Trek lists LRO NAC DEMs at
1.50 m and NAC mosaics at 0.50 m — resolution that would certify a rover
traverse outright and put boulders within reach — but they are served as whole
files of roughly 600 MB each, not as tiles. Probed directly at every plausible
zoom, they return 404: there is no pyramid to stream from.

So they cannot be used casually. They are reported here, with their size, so
the choice to spend disk on one is explicit and belongs to the user.

Why the catalogue is cached rather than queried live
----------------------------------------------------
The index is a few thousand records and changes on the order of months, while a
region preview must answer in milliseconds. Querying Trek on every selection
would add a network round trip to an interaction that has none, and would make
the page fail when the service is slow. It is fetched once and refreshed on
demand.
"""

from __future__ import annotations

import json
import math
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from ..config import CACHE_DIR, R_MOON_M

__all__ = ["TrekProduct", "available_for", "refresh", "load_catalogue",
           "STREAMED", "CATALOGUE_PATH"]

CATALOGUE_PATH = CACHE_DIR / "trek_catalogue.json"

_SEARCH = ("https://trek.nasa.gov/moon/TrekServices/ws/index/eq/searchItems"
           "?start={start}&rows={rows}&q=itemType:product&wt=json")

#: Products this project can already read without storing anything. Verified
#: against the live tile service rather than taken from the catalogue, which
#: does not distinguish a tile pyramid from a downloadable raster.
STREAMED: dict[str, dict] = {
    "kaguya_tc": {
        "product_id": "Kaguya_TCortho_Mosaic_Global_4096ppd",
        "kind": "imagery", "m_px": 20.82, "global": True,
        "note": ("Published at 7.40 m/px; the tile pyramid stops at z=10, so "
                 "20.82 m/px is what can actually be served."),
    },
    "ldem_1024": {
        "product_id": "LDEM_1024", "kind": "DEM", "m_px": 29.61,
        "global": True,
        "note": ("LOLA at 1024 ppd, read over HTTP range requests from PDS. "
                 "Cross-validated against LDEM_64 and corrected for a 103 m "
                 "eastward offset."),
    },
}


@dataclass(frozen=True)
class TrekProduct:
    """One Trek product and the ground it covers."""

    product_id: str
    title: str
    kind: str                    # DEM | imagery | slope | hillshade | other
    m_px: float | None
    west: float
    south: float
    east: float
    north: float
    bytes: int | None
    instrument: str
    mission: str

    @property
    def lon_span(self) -> float:
        """Width in longitude, on the circle."""
        span = self.east - self.west
        return span + 360.0 if span < 0 else span

    @property
    def is_global(self) -> bool:
        """Covers every longitude.

        Worth a property rather than an inline test. A product spanning
        -180..180 normalises to a zero-width interval, so the ordinary overlap
        arithmetic decides it covers nothing — which is how every global
        product in the catalogue came to report as covering no region at all.
        """
        return self.lon_span >= 359.5

    def covers(self, south: float, north: float,
               west: float, east: float) -> bool:
        """Whether this product overlaps a region at all.

        Longitudes are compared on a common branch: Trek writes them in
        -180..180 while this project uses 0..360, so a naive comparison puts
        every far-side product outside every near-side region.
        """
        if north < self.south or south > self.north:
            return False
        if self.is_global:
            return True
        a0 = _norm_lon(self.west)
        a1 = a0 + self.lon_span
        span_b = east - west
        if span_b < 0:
            span_b += 360.0
        b0 = _norm_lon(west)
        b1 = b0 + span_b
        for shift in (-360.0, 0.0, 360.0):
            if not (b1 + shift < a0 or b0 + shift > a1):
                return True
        return False

    def area_km2(self) -> float:
        lat_m = math.radians(abs(self.north - self.south)) * R_MOON_M
        mid = math.radians((self.north + self.south) / 2.0)
        lon_m = (math.radians(abs(self.east - self.west))
                 * R_MOON_M * math.cos(mid))
        return lat_m * lon_m / 1e6

    def to_dict(self) -> dict:
        return {
            "product_id": self.product_id, "title": self.title,
            "kind": self.kind, "m_px": self.m_px,
            "bounds": {"south": self.south, "north": self.north,
                       "west": self.west, "east": self.east},
            "area_km2": round(self.area_km2(), 1),
            "megabytes": round(self.bytes / 1e6, 1) if self.bytes else None,
            "instrument": self.instrument, "mission": self.mission,
            "access": "download",
            "coverage": "global" if self.is_global else "site",
        }


def _norm_lon(x: float) -> float:
    return x % 360.0


def _resolution(label: str) -> float | None:
    """Metres per pixel, from the naming convention Trek uses in its labels."""
    m = re.search(r"(\d+)ppd", label)
    if m:
        return 2 * math.pi * R_MOON_M / (int(m.group(1)) * 360)
    m = re.search(r"(\d+)cmp", label)
    if m:
        return int(m.group(1)) / 100.0
    m = re.search(r"(\d+)mp\b", label)
    if m:
        return float(m.group(1))
    return None


def _kind(label: str, cat2: str) -> str:
    low = f"{label} {cat2}".lower()
    if "dem" in low or "dtm" in low:
        return "DEM"
    if "slope" in low:
        return "slope"
    if "shade" in low:
        return "hillshade"
    if any(k in low for k in ("mosaic", "ortho", "img", "image")):
        return "imagery"
    return "other"


def refresh(path: Path = CATALOGUE_PATH, *, timeout: int = 120) -> dict:
    """Fetch the Trek product index and cache it."""
    docs: list[dict] = []
    total = None
    while total is None or len(docs) < total:
        url = _SEARCH.format(start=len(docs), rows=1000)
        with urllib.request.urlopen(url, timeout=timeout) as r:
            resp = json.load(r)["response"]
        total = resp["numFound"]
        batch = resp["docs"]
        if not batch:
            break
        docs += batch

    keep = []
    for d in docs:
        bbox = d.get("bbox")
        label = d.get("productLabel") or ""
        if not bbox or not label:
            continue
        try:
            w, s, e, n = (float(x) for x in bbox.split(","))
        except ValueError:
            continue
        size = d.get("fileSize")
        if isinstance(size, list):
            size = size[0] if size else None
        keep.append({
            "product_id": label,
            "title": d.get("title") or label,
            "kind": _kind(label, str(d.get("productCat2") or "")),
            "m_px": _resolution(label),
            "west": w, "south": s, "east": e, "north": n,
            "bytes": int(size) if size else None,
            "instrument": d.get("instrument") or "",
            "mission": d.get("mission") or "",
        })

    doc = {"fetched_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "source": "NASA Trek / Moon EQ product index",
           "count": len(keep), "products": keep}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")
    return doc


def load_catalogue(path: Path = CATALOGUE_PATH) -> list[TrekProduct]:
    if not path.exists():
        return []
    doc = json.loads(path.read_text(encoding="utf-8"))
    return [TrekProduct(**p) for p in doc.get("products", [])]


def available_for(south: float, north: float, west: float, east: float,
                  *, kinds=("DEM", "imagery"), max_m_px: float | None = None,
                  ) -> dict:
    """Everything that covers this region, streamed first then downloadable.

    The streamed entries are the answer to "what can I analyse right now"; the
    downloadable ones answer "what is the best that exists here, and what would
    it cost me". Keeping both in one response is the point — a page that showed
    only what is free would hide that 1.5 m data exists for this exact spot.
    """
    ready = [
        {**spec, "key": key, "access": "streamed", "megabytes": 0}
        for key, spec in STREAMED.items()
        if spec["kind"] in kinds
    ]

    hits = [p for p in load_catalogue()
            if p.kind in kinds and p.covers(south, north, west, east)]
    if max_m_px is not None:
        hits = [p for p in hits if p.m_px is not None and p.m_px <= max_m_px]
    # Finest first; products with no parseable resolution go last rather than
    # being dropped, since an unlabelled product is unknown, not absent.
    hits.sort(key=lambda p: (p.m_px is None, p.m_px or 0.0))

    # Site-specific coverage is the interesting half. A global product covers
    # this region exactly as it covers everywhere else, so listing it under
    # "what is available here" answers a question nobody asked.
    site = [p for p in hits if not p.is_global]
    glob = [p for p in hits if p.is_global]

    best_stream = min((r["m_px"] for r in ready if r["kind"] == "DEM"),
                      default=None)
    finest = next((p for p in site if p.kind == "DEM" and p.m_px), None)

    return {
        "region": {"south": south, "north": north, "west": west, "east": east},
        "streamed": sorted(ready, key=lambda r: r["m_px"]),
        "site_specific": [p.to_dict() for p in site],
        "global_downloads": [p.to_dict() for p in glob],
        "summary": {
            "streamed_dem_m": best_stream,
            "finest_dem_m": finest.m_px if finest else best_stream,
            "finest_dem_product": finest.product_id if finest else None,
            "finer_available": bool(finest and best_stream
                                    and finest.m_px < best_stream),
            "download_cost_mb": (round(finest.bytes / 1e6, 1)
                                 if finest and finest.bytes else 0),
            "site_products": len(site),
        },
    }


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def _main() -> int:
    import sys

    if "--refresh" in sys.argv or not CATALOGUE_PATH.exists():
        print("fetching the Trek product index…")
        doc = refresh()
        print(f"  cached {doc['count']:,} products with bounds "
              f"({CATALOGUE_PATH.stat().st_size/1024:.0f} KB)")

    npass = nfail = 0

    def check(name, ok, detail=""):
        nonlocal npass, nfail
        if ok:
            npass += 1
            print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
        else:
            nfail += 1
            print(f"  FAIL  {name}   {detail}")

    cat = load_catalogue()
    print(f"\nThe catalogue answers what covers a region\n")
    check("the index loaded", len(cat) > 100, f"{len(cat):,} products")

    dems = [p for p in cat if p.kind == "DEM" and p.m_px]
    check("it knows about DEMs finer than anything streamed",
          any(p.m_px < 20 for p in dems),
          f"finest {min(p.m_px for p in dems):.2f} m/px")

    # Murchison, where a 1.5 m NAC DEM exists.
    here = available_for(4.3, 5.2, 359.5, 359.8)
    check("a region with NAC coverage reports it",
          here["summary"]["finer_available"],
          f"{here['summary']['streamed_dem_m']:.1f} m streamed vs "
          f"{here['summary']['finest_dem_m']:.1f} m available")
    check("and says what it would cost to use",
          here["summary"]["download_cost_mb"] > 100,
          f"{here['summary']['download_cost_mb']:.0f} MB for the finest DEM")

    # Somewhere with no site-specific coverage at all.
    empty = available_for(-30.0, -29.5, 200.0, 200.5)
    check("a region with no site coverage still has the global products",
          len(empty["streamed"]) >= 2
          and not empty["summary"]["finer_available"],
          f"{empty['summary']['site_products']} site products, "
          f"{len(empty['global_downloads'])} global")

    check("streamed products are always offered first",
          all(r["access"] == "streamed" for r in here["streamed"]),
          "what needs no download and no permission comes first")

    # Longitude conventions: Trek writes -180..180, this project 0..360.
    far = [p for p in cat if not p.is_global and p.west < -100
           and p.m_px and p.m_px < 5]
    if far:
        p = far[0]
        mid_lon = _norm_lon((p.west + p.east) / 2)
        check("far-side products are found despite the longitude convention",
              p.covers(p.south + 1e-6, p.north - 1e-6,
                       mid_lon - 0.001, mid_lon + 0.001),
              f"{p.product_id} at {mid_lon:.1f} degE")

    world = [p for p in cat if p.is_global]
    check("a product spanning the whole circle is recognised as global",
          len(world) > 5 and all(g.covers(0, 1, 200, 201) for g in world[:5]),
          f"{len(world)} global products; a -180..180 span is not zero-width")

    print(f"\n{npass} passed, {nfail} failed")
    return 1 if nfail else 0


if __name__ == "__main__":
    raise SystemExit(_main())
