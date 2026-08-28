"""
The Cesium tileset is a view, not a measurement surface.

Every other source in this project was checked against an independent one
before being trusted. The ion 3D Tileset that draws the Terrain globe never
was, and when it finally is, it disagrees with LOLA by more than a kilometre.

The evidence, from 240 heights sampled out of the tileset itself with
``scene.sampleHeightMostDetailed`` (``docs/results/cesium_tileset_heights.json``):

===========================  ==========
mean offset vs LOLA           +1,789 m
best fit                      1.060 x LOLA + 1,824 m
correlation                   0.968
residual RMS after both       609 m
samples within 250 m          0 of 240
===========================  ==========

The correlation says it is the same terrain; the offset and scale say it is in
the wrong place vertically. The decisive check is Apollo 15, where two
independent instruments already agree:

    LOLA LDEM_64      -1924.0 m
    LROC NAC DTM 2 m  -1925.0 m     <- different instrument, different pipeline
    Cesium tileset      234.5 m     <- +2,158 m

So this file does not test the tileset. It tests that the *project* keeps
saying so: that nothing samples elevation from Cesium, and that the interface
warns rather than presenting the surface as data. A future contributor wiring
`sampleHeight` into an analysis path is the failure this guards against.

Region selection over Cesium remains sound. A radial displacement does not
move a latitude or a longitude, so a box drawn on this globe covers the ground
it appears to cover; only the heights are wrong. Horizontal registration was
not measured here and is not claimed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MEASURED = ROOT / "docs" / "results" / "cesium_tileset_heights.json"
FRONTEND = ROOT / "frontend"

npass = nfail = 0


def check(name, ok, detail=""):
    global npass, nfail
    if ok:
        npass += 1
        print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
    else:
        nfail += 1
        print(f"  FAIL  {name}   {detail}")


print("\nThe measured disagreement is on record\n")

doc = json.loads(MEASURED.read_text(encoding="utf-8")) if MEASURED.exists() else None
check("the sampled heights are kept, not just the conclusion",
      doc is not None and doc.get("sampled", 0) >= 200,
      f"{doc.get('sampled')} samples" if doc else "missing")

if doc:
    named = {p["name"]: p["h"] for p in doc["points"] if p.get("name")}
    check("the Apollo 15 sample is among them", "Apollo 15" in named,
          f"{named.get('Apollo 15', float('nan')):.1f} m from the tileset")
    check("and it is nowhere near the two instruments that agree",
          abs(named.get("Apollo 15", 0) - (-1924.0)) > 1000,
          "LOLA and LROC NAC put it at -1924 m, within 1 m of each other")

print("\nNothing in the project measures from it\n")

main = (FRONTEND / "js" / "main.js").read_text(encoding="utf-8")
ces = (FRONTEND / "js" / "cesium-renderer.js").read_text(encoding="utf-8")

check("no analysis path samples height from the tileset",
      "sampleHeight" not in main and "sampleHeight" not in ces,
      "elevation comes from the DEM endpoints, never from the renderer")

check("the interface says the surface is not a measurement",
      "do not measure" in main and "+1.8 km vs LOLA" in main,
      "the number is on screen, not buried in a comment")

check("the level-of-detail figure is not presented as a resolution",
      "not a resolution" in main,
      "geometricError is a refinement threshold, not a posting")

print("\nSelection over Cesium is still sound\n")

check("picking returns a coordinate, not an elevation",
      "_toLatLon" in ces and "lat:" in ces and "lon:" in ces,
      "a radial error moves no latitude")
check("the AOI still resolves its own elevation from a DEM source",
      "plan_aoi" not in ces,
      "the renderer supplies bounds; the backend supplies data")

print(f"\n{npass} passed, {nfail} failed")
raise SystemExit(1 if nfail else 0)
