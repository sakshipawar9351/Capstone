r"""
Training tiles for the crater detector: Kaguya imagery, Robbins rim masks.

Every choice here is forced by one alignment, and getting it wrong is the
difference between a detector that works and one that fights its own labels.

Why 125 m/px and why craters >= 2 km
------------------------------------
A convolutional detector needs roughly 16 pixels across an object before it can
find it reliably. Robbins (2019) states his own completeness: *"41.8% of the
body is complete for D >= 1 km, 93.7% for D >= 1.5 km"*, and an independent
check against the catalogue's own power law finds a 14.6 % shortfall at 1 km.

So label everything down to 1 km and roughly one in seven of the 1 km craters
sitting in a training image is unlabelled — and the network is taught that
those are background, immediately before being asked to find exactly that kind
of object. Training against the goal.

Setting the label floor at 2 km, where the catalogue is complete, and the
sampling at 125 m/px, where 2 km spans exactly 16 pixels, makes the two floors
coincide: **every crater the network can see is labelled**. Nothing visible is
ever punished as a false positive.

Rims, not discs
---------------
The target is a thin ring on each crater's rim rather than a filled circle.
Craters nest constantly — a small one inside a large one — and filled discs
merge into a blob from which neither is recoverable. Rings stay separate. The
rim is also the feature actually visible in an image: the lit-and-shadowed edge
where the wall catches the sun.

Square ground, not square degrees
---------------------------------
A tile spans equal *metres* north-south and east-west, so its longitude span
widens as ``1/cos(lat)``. Cutting equal degrees instead would stretch craters
into ellipses toward the poles and teach the network that a crater is an oval —
which the ring-template extraction downstream would then reject.

Splitting
---------
By longitude band, never at random. Adjacent tiles share illumination, terrain
and craters that straddle their border; a random split leaves 97 % of test
tiles touching training data and every metric measured on it is optimistic.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import random
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np

from ..config import PROJECT_ROOT, R_MOON_M

__all__ = ["TileSpec", "plan_tiles", "build_tile", "crater_mask",
           "split_of", "DATASET_DIR", "GSD_M", "MIN_DIAM_KM", "TILE_PX"]

#: Metres per pixel. Chosen so MIN_DIAM_KM lands on the detector's 16 px floor.
GSD_M = 125.0
#: Label floor. Robbins is complete here; below it, it is not.
MIN_DIAM_KM = 2.0
#: Tile side in pixels. 640 x 125 m = 80 km of ground.
TILE_PX = 640

DATASET_DIR = PROJECT_ROOT / "data" / "ml" / "craters_125mpp"

#: Latitude beyond which tiles are not cut. Not a projection limit — Kaguya's
#: coverage and quality degrade toward the poles, and the polar regions are
#: served by the 10 m DEM anyway, so training on stretched, noisy imagery there
#: would add difficulty without adding information.
LAT_LIMIT = 70.0

#: Longitude bands, in degrees, assigned round-robin to train/val/test. Bands
#: rather than tiles: the unit of separation has to be larger than the
#: correlation length of the terrain, and 30 degrees is 900 km at the equator.
BAND_DEG = 30.0
_SPLIT_CYCLE = ("train", "train", "train", "val",
                "train", "train", "train", "test",
                "train", "train", "val", "test")


def split_of(lon: float) -> str:
    """Which split a longitude falls in. Deterministic, blocked, no seed."""
    band = int((lon % 360.0) // BAND_DEG)
    return _SPLIT_CYCLE[band % len(_SPLIT_CYCLE)]


@dataclass(frozen=True)
class TileSpec:
    """One training tile: a square of ground, not a square of degrees."""

    lat: float                  # centre
    lon: float                  # centre, 0..360
    gsd_m: float = GSD_M
    size_px: int = TILE_PX

    @property
    def half_m(self) -> float:
        return 0.5 * self.size_px * self.gsd_m

    @property
    def dlat(self) -> float:
        """Degrees of latitude per pixel."""
        return self.gsd_m / (math.pi * R_MOON_M / 180.0)

    @property
    def dlon(self) -> float:
        """Degrees of longitude per pixel, widened by 1/cos(lat)."""
        c = max(math.cos(math.radians(self.lat)), 1e-6)
        return self.dlat / c

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """south, north, west, east — west/east may exceed 0..360."""
        h = 0.5 * self.size_px
        return (self.lat - h * self.dlat, self.lat + h * self.dlat,
                self.lon - h * self.dlon, self.lon + h * self.dlon)

    @property
    def key(self) -> str:
        raw = f"{self.lat:.5f},{self.lon:.5f},{self.gsd_m},{self.size_px}"
        return hashlib.sha1(raw.encode()).hexdigest()[:12]

    @property
    def split(self) -> str:
        return split_of(self.lon)

    def latlon_to_px(self, lat, lon):
        """Fractional pixel coordinates of a coordinate. Pixel centres."""
        s, n, w, e = self.bounds
        lat = np.asarray(lat, dtype=np.float64)
        lon = np.asarray(lon, dtype=np.float64)
        # Onto the tile's own longitude branch — a tile near 0 degrees must not
        # push a crater at 359.9 to the far side of the Moon.
        lon = np.where(lon - w > 180.0, lon - 360.0, lon)
        lon = np.where(w - lon > 180.0, lon + 360.0, lon)
        return ((lon - w) / self.dlon - 0.5,          # x
                (n - lat) / self.dlat - 0.5)          # y


def plan_tiles(gsd_m: float = GSD_M, size_px: int = TILE_PX,
               lat_limit: float = LAT_LIMIT) -> list[TileSpec]:
    """Tiles covering the Moon, spaced to touch without overlapping.

    Rows are laid at constant latitude spacing; within a row the longitude
    spacing widens with 1/cos(lat) so every tile covers the same ground area.
    Toward the limit that means fewer, wider-spaced tiles per row, which is
    correct: there is less surface there to cover.
    """
    span_deg_lat = size_px * gsd_m / (math.pi * R_MOON_M / 180.0)
    out: list[TileSpec] = []
    n_rows = int(2 * lat_limit / span_deg_lat)
    for i in range(n_rows):
        lat = -lat_limit + (i + 0.5) * span_deg_lat
        c = max(math.cos(math.radians(lat)), 1e-6)
        span_deg_lon = span_deg_lat / c
        n_cols = max(int(360.0 / span_deg_lon), 1)
        for j in range(n_cols):
            out.append(TileSpec(lat=lat, lon=(j + 0.5) * (360.0 / n_cols),
                                gsd_m=gsd_m, size_px=size_px))
    return out


# ---------------------------------------------------------------------------
# Imagery
# ---------------------------------------------------------------------------

def _kaguya_zoom(gsd_m: float) -> int:
    """Finest Kaguya level at least as sharp as the target sampling.

    Downsampling from a sharper level is safe; upsampling a coarser one would
    invent detail and, worse, would put craters at a pixel size the network was
    never trained on.
    """
    for z in range(0, 11):
        if 2 * math.pi * R_MOON_M / (2 ** (z + 1) * 256) <= gsd_m:
            return z
    return 10


def build_tile(spec: TileSpec, *, layer: str = "kaguya_tc"
               ) -> tuple[np.ndarray, np.ndarray]:
    """Fetch and resample one tile, with a mask of which pixels are real.

    Greyscale uint8: the orthomosaic carries no colour, and three identical
    channels would triple the dataset for nothing.
    """
    import time
    from concurrent.futures import ThreadPoolExecutor

    from PIL import Image

    from ..main import _fetch_tile          # local: pulls in the whole app

    z = _kaguya_zoom(spec.gsd_m)
    cols, rows = 2 ** (z + 1), 2 ** z
    s, n, w, e = spec.bounds

    x0 = math.floor((w % 360.0) / 360.0 * cols)
    x1 = math.floor(((e % 360.0) - 1e-9) / 360.0 * cols)
    if x1 < x0:
        x1 += cols
    y0 = max(0, math.floor((90.0 - n) / 180.0 * rows))
    y1 = min(rows - 1, math.floor((90.0 - s - 1e-9) / 180.0 * rows))

    def grab(zz, yy, xx, tries=4):
        """Fetch with backoff.

        Bulk fetching drops tiles: a first pass over a region left whole
        columns black, and every one of them returned normally when asked
        again a minute later. They were rate-limited, not absent. Retrying
        turns a systematic hole in the training image into a pause.
        """
        delay = 1.0
        for i in range(tries):
            b = _fetch_tile(layer, zz, yy, xx)
            if b:
                return b
            if i < tries - 1:
                time.sleep(delay)
                delay *= 2
        return None

    probe = grab(z, y0, x0 % cols)
    if probe is None:
        raise OSError(f"no imagery for tile {spec.key} at z={z}")
    tw, th = Image.open(io.BytesIO(probe)).size

    canvas = Image.new("L", ((x1 - x0 + 1) * tw, (y1 - y0 + 1) * th), 0)
    ok = Image.new("L", canvas.size, 0)
    solid = Image.new("L", (tw, th), 255)

    # Fetched in parallel because the wait dominates: one training tile spans
    # roughly twenty source tiles, and serially that is most of a minute of
    # latency per example. Eight at a time is brisk without being rude to a
    # shared public service — the retry above already exists because bulk
    # fetching too hard is what dropped tiles in the first place.
    jobs = [(yy, xx) for yy in range(y0, y1 + 1) for xx in range(x0, x1 + 1)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for (yy, xx), blob in zip(jobs, pool.map(
                lambda j: grab(z, j[0], j[1] % cols), jobs)):
            if not blob:
                continue
            canvas.paste(Image.open(io.BytesIO(blob)).convert("L"),
                         ((xx - x0) * tw, (yy - y0) * th))
            ok.paste(solid, ((xx - x0) * tw, (yy - y0) * th))

    # Crop to the tile's exact bounds inside the assembled mosaic, then resample.
    px_per_deg_lon = cols * tw / 360.0
    px_per_deg_lat = rows * th / 180.0
    left = ((w % 360.0) - x0 / cols * 360.0) * px_per_deg_lon
    top = ((90.0 - n) - y0 / rows * 180.0) * px_per_deg_lat
    right = left + (e - w) * px_per_deg_lon
    bottom = top + (n - s) * px_per_deg_lat

    cut = canvas.resize((spec.size_px, spec.size_px), Image.BILINEAR,
                        box=(left, top, right, bottom))
    val = ok.resize((spec.size_px, spec.size_px), Image.NEAREST,
                    box=(left, top, right, bottom))
    # The validity mask travels with the image so the loss can ignore ground
    # no instrument supplied. Treating a gap as dark terrain would teach the
    # network that black regions are craterless, which is a lesson about the
    # download rather than about the Moon.
    return np.asarray(cut, dtype=np.uint8), np.asarray(val, dtype=np.uint8) > 0


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

#: Widest a rim ring may be drawn, in pixels.
#:
#: Thickness proportional to radius with no ceiling is what broke the first
#: training run. A 200 km crater has an 800 px radius here, so a 10 % ring is
#: 80 px wide — a smooth band across a 640 px tile with no visible edge
#: anywhere along it. Tiles holding a crater over 100 km came out 25.75 %
#: "rim" against 1.06 % for tiles holding only small ones, and the network
#: spent its capacity on swaths it could not possibly see. Loss moved 1.0306
#: to 1.0214 across 36 epochs; held-out F1 was 0.109.
#:
#: A rim is an edge. An edge is a few pixels wide whatever the crater's size.
MAX_RING_PX = 3

#: Largest crater drawn, as a multiple of the tile's own width.
#:
#: A crater wider than the frame is not an object in the image, it is regional
#: context: its arc crosses the tile as a gentle curve indistinguishable from
#: any other slope. Labelling it teaches the network to mark ground on no
#: visible evidence.
MAX_DIAM_TILES = 1.0


def crater_mask(spec: TileSpec, craters, *,
                min_ring_px: int = 1) -> tuple[np.ndarray, list]:
    """Rim rings for every catalogued crater visible in the tile.

    Two ceilings, both learned the hard way — see MAX_RING_PX above.
    """
    size = spec.size_px
    mask = np.zeros((size, size), dtype=np.uint8)
    used = []

    for c in craters:
        cx, cy = spec.latlon_to_px(c.lat, c.lon)
        cx, cy = float(cx), float(cy)
        r = (c.diameter_km * 1000.0 / 2.0) / spec.gsd_m
        if r < 4.0:
            continue                      # below what a ring can express
        # Keep craters whose rim crosses the tile even if the centre is outside;
        # dropping them would leave visible arcs unlabelled.
        if cx < -r or cy < -r or cx > size + r or cy > size + r:
            continue
        if 2 * r > size * MAX_DIAM_TILES:
            continue                      # wider than the frame: not an object
        w = int(np.clip(round(r * 0.10), min_ring_px, MAX_RING_PX))
        # Only the annulus can be set, so only its bounding box is evaluated.
        # A full-frame distance field per crater is 410,000 cells whatever the
        # crater's size, and at ~90 craters a tile that dominated generation:
        # 2.2 s a tile, most of it computing distances to pixels nowhere near
        # the ring.
        lo_x = max(int(np.floor(cx - r - w)), 0)
        hi_x = min(int(np.ceil(cx + r + w)) + 1, size)
        lo_y = max(int(np.floor(cy - r - w)), 0)
        hi_y = min(int(np.ceil(cy + r + w)) + 1, size)
        if hi_x <= lo_x or hi_y <= lo_y:
            continue
        sub_y, sub_x = np.ogrid[lo_y:hi_y, lo_x:hi_x]
        d = np.hypot(sub_x - cx, sub_y - cy)
        mask[lo_y:hi_y, lo_x:hi_x][(d >= r - w) & (d <= r + w)] = 1
        used.append({"id": str(c.id), "lat": float(c.lat),
                     "lon": float(c.lon), "diam_km": float(c.diameter_km),
                     "px": [round(cx, 2), round(cy, 2), round(r, 2)]})
    return mask, used


def craters_for(spec: TileSpec, index, *, min_diam_km: float = MIN_DIAM_KM,
                pad_frac: float = 0.6):
    """Catalogue entries near the tile, padded so rim arcs are not missed."""
    s, n, w, e = spec.bounds
    ph = (n - s) * pad_frac
    pw = (e - w) * pad_frac
    return index.query_bbox(s - ph, n + ph, (w - pw) % 360.0, (e + pw) % 360.0,
                            min_diameter_km=min_diam_km)


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

    print("\nThe sampling puts the label floor on the detector floor\n")
    px = MIN_DIAM_KM * 1000.0 / GSD_M
    check("a 2 km crater spans exactly 16 px at 125 m/px", abs(px - 16.0) < 1e-9,
          f"{px:.2f} px — below this the catalogue is incomplete, above it "
          "the network cannot see")

    tiles = plan_tiles()
    check("tiles cover the Moon between the latitude limits",
          2000 < len(tiles) < 8000, f"{len(tiles):,} tiles")
    check("every tile is square on the ground, not in degrees",
          all(abs(t.dlon / t.dlat - 1 / math.cos(math.radians(t.lat))) < 1e-9
              for t in tiles[::97]),
          "longitude span widens as 1/cos(lat)")

    print("\nSplits are blocked, and the geometry round-trips\n")
    from collections import Counter
    c = Counter(t.split for t in tiles)
    frac = {k: v / len(tiles) for k, v in c.items()}
    check("all three splits are populated",
          all(k in frac for k in ("train", "val", "test")),
          " ".join(f"{k} {v*100:.0f}%" for k, v in sorted(frac.items())))
    check("a split is decided by longitude alone, never at random",
          split_of(12.0) == split_of(12.0) and split_of(12.0) == split_of(29.9),
          "same band, same answer — no seed involved")
    check("adjacent bands can differ",
          len({split_of(15.0), split_of(105.0), split_of(225.0)}) > 1)

    t = TileSpec(lat=12.0, lon=48.0)
    s, n, w, e = t.bounds
    for lat, lon, want in ((n, w, (-0.5, -0.5)), (s, e, (639.5, 639.5))):
        x, y = t.latlon_to_px(lat, lon)
        ok = abs(float(x) - want[0]) < 1e-6 and abs(float(y) - want[1]) < 1e-6
        if not ok:
            check(f"corner ({lat:.3f},{lon:.3f}) maps correctly", False,
                  f"got ({float(x):.3f},{float(y):.3f}) want {want}")
            break
    else:
        check("tile corners map to the pixel grid exactly",
              True, "north-west to (-0.5,-0.5), south-east to (639.5,639.5)")

    check("ground extent is 80 km square",
          abs(t.half_m * 2 / 1000 - 80.0) < 1e-6, f"{t.half_m*2/1000:.1f} km")

    print("\nMasks are rims, and they come from the real catalogue\n")
    try:
        from ..data.catalog_robbins import load_index
        ix = load_index()
    except Exception as e:                                   # noqa: BLE001
        print(f"  catalogue unavailable ({type(e).__name__}) — skipping")
        print(f"\n{npass} passed, {nfail} failed")
        return 1 if nfail else 0

    cr = craters_for(t, ix)
    check("the catalogue supplies craters for a tile", len(cr) > 0,
          f"{len(cr)} craters >= {MIN_DIAM_KM} km near {t.lat:.0f}N {t.lon:.0f}E")

    mask, used = crater_mask(t, cr)
    frac_on = mask.mean()
    check("the mask marks rims, not discs", 0.0 < frac_on < 0.15,
          f"{frac_on*100:.2f}% of pixels are rim — a filled disc would be many "
          "times this")
    check("every mask pixel traces to a catalogue entry",
          all("id" in u and u["diam_km"] >= MIN_DIAM_KM for u in used),
          f"{len(used)} craters drawn, each with its Robbins id")
    check("no crater below the completeness floor is drawn",
          all(u["diam_km"] >= MIN_DIAM_KM for u in used),
          "unlabelled visible craters would teach the network they are background")

    rings = [u for u in used if 4 <= u["px"][2]]
    check("drawn craters are large enough for a ring to mean anything",
          len(rings) == len(used), f"smallest radius {min((u['px'][2] for u in used), default=0):.1f} px")

    print(f"\n{npass} passed, {nfail} failed")
    return 1 if nfail else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())


# ---------------------------------------------------------------------------
# Corpus generation
# ---------------------------------------------------------------------------

#: A tile with more missing imagery than this is discarded rather than kept
#: with a validity mask. Past roughly a fifth, what remains is too fragmented
#: to be a useful training example and the gaps bias the crater statistics.
MAX_GAP_FRACTION = 0.20


def write_dataset(out_dir: Path = DATASET_DIR, *, limit: int | None = None,
                  min_craters: int = 3, resume: bool = True,
                  progress=print) -> dict:
    """Generate the training corpus and a manifest that can reproduce it.

    The manifest is the point. It records every tile's bounds, split and the
    catalogue id of every crater drawn on it, so any prediction can be traced
    to the labels it was trained against, and the corpus can be rebuilt exactly.
    """
    from PIL import Image

    from ..data.catalog_robbins import load_index

    index = load_index()
    tiles = plan_tiles()
    # Shuffled before truncating, with a fixed seed. plan_tiles walks latitude
    # rows in order, so taking the first N would sample one band of the Moon
    # and call it a global corpus — and the longitude-blocked split would then
    # be drawn from a sliver rather than the whole surface.
    random.Random(20260828).shuffle(tiles)
    if limit:
        tiles = tiles[:limit]

    for split in ("train", "val", "test"):
        (out_dir / split / "images").mkdir(parents=True, exist_ok=True)
        (out_dir / split / "masks").mkdir(parents=True, exist_ok=True)

    records, skipped = [], {"gaps": 0, "sparse": 0, "error": 0, "done": 0}
    for i, spec in enumerate(tiles):
        # Resume rather than restart. Generation takes tens of minutes and a
        # killed run should cost the tile it was on, not all of them.
        prior = next((out_dir / sp / "images" / f"{spec.key}.png"
                      for sp in ("train", "val", "test")
                      if (out_dir / sp / "images" / f"{spec.key}.png").exists()),
                     None)
        if prior is not None and resume:
            craters = craters_for(spec, index)
            _, used = crater_mask(spec, craters)
            if len(used) >= min_craters:
                records.append({
                    "key": spec.key, "split": spec.split,
                    "lat": round(spec.lat, 5), "lon": round(spec.lon, 5),
                    "gsd_m": spec.gsd_m, "size_px": spec.size_px,
                    "bounds": [round(v, 5) for v in spec.bounds],
                    "valid_fraction": 1.0,
                    "rim_fraction": round(float(_.mean()), 5),
                    "craters": used,
                })
                skipped["done"] += 1
                continue
        try:
            img, valid = build_tile(spec)
        except Exception:                                    # noqa: BLE001
            skipped["error"] += 1
            continue
        if 1.0 - valid.mean() > MAX_GAP_FRACTION:
            skipped["gaps"] += 1
            continue
        craters = craters_for(spec, index)
        mask, used = crater_mask(spec, craters)
        # An empty tile teaches "no craters here", which is a real and useful
        # lesson — but a corpus of them would drown the positive signal, so a
        # floor is set and the discards are counted rather than hidden.
        if len(used) < min_craters:
            skipped["sparse"] += 1
            continue

        sp = spec.split
        Image.fromarray(img).save(out_dir / sp / "images" / f"{spec.key}.png")
        Image.fromarray(mask * 255).save(out_dir / sp / "masks" / f"{spec.key}.png")
        records.append({
            "key": spec.key, "split": sp,
            "lat": round(spec.lat, 5), "lon": round(spec.lon, 5),
            "gsd_m": spec.gsd_m, "size_px": spec.size_px,
            "bounds": [round(v, 5) for v in spec.bounds],
            "valid_fraction": round(float(valid.mean()), 4),
            "rim_fraction": round(float(mask.mean()), 5),
            "craters": used,
        })
        if progress and (i + 1) % 25 == 0:
            progress(f"    {i+1}/{len(tiles)} planned · {len(records)} written")

    doc = {
        "what": ("Kaguya orthomosaic tiles with Robbins crater rims as masks. "
                 "Sampling and label floor are aligned so every crater the "
                 "network can see is labelled."),
        "gsd_m": GSD_M, "min_diameter_km": MIN_DIAM_KM, "size_px": TILE_PX,
        "band_deg": BAND_DEG, "lat_limit": LAT_LIMIT,
        "imagery": "Kaguya_TCortho_Mosaic_Global_4096ppd (NASA Trek)",
        "labels": "Robbins (2019) JGR Planets 124(4) 871-892, doi:10.1029/2018JE005592",
        "tiles_planned": len(tiles), "tiles_written": len(records),
        "skipped": skipped,
        "craters_total": sum(len(r["craters"]) for r in records),
        "split_counts": {s: sum(1 for r in records if r["split"] == s)
                         for s in ("train", "val", "test")},
        "tiles": records,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.json").write_text(json.dumps(doc, indent=1),
                                           encoding="utf-8")
    return doc
