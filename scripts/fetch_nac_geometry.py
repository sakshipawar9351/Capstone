"""
Fetch observation geometry for downloaded NAC scenes and store it alongside.

Why this is needed
------------------
An LROC NAC CDR label describes the *image* — dimensions, timing, instrument
settings — but not where the camera was pointing. Illumination and pointing are
derived from SPICE kernels rather than embedded, so the label alone cannot
support any measurement that depends on geometry.

That matters because boulder height comes from shadow length:

    h = L * tan(90 deg - i)

with *i* the solar incidence angle. Without *i* a shadow is just a dark patch.

The PDS Orbital Data Explorer computes this geometry for every product and
serves it in its catalogue, so the information is available from an
authoritative source even though it is absent from the file. This script
retrieves it and writes a ``.geom.json`` sidecar next to each image.

This is precisely the difference between the NAC scenes and the Chandrayaan
PNGs: for NAC the geometry exists and can be recovered; for those PNGs it
exists nowhere reachable, which is why they cannot be placed on the Moon.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests  # noqa: E402

from backend.config import PROJECT_ROOT  # noqa: E402

ODE = "https://oderest.rsl.wustl.edu/live2/"
NAC_DIR = PROJECT_ROOT / "data" / "raw" / "polar" / "nac"

#: Fields ODE derives from SPICE that the label does not carry.
GEOMETRY_FIELDS = [
    "Center_latitude", "Center_longitude",
    "Easternmost_longitude", "Westernmost_longitude",
    "Minimum_latitude", "Maximum_latitude",
    "Incidence_angle", "Emission_angle", "Phase_angle",
    "Solar_azimuth", "Sub_solar_azimuth", "Sub_solar_latitude",
    "Sub_solar_longitude", "Spacecraft_altitude",
    "Map_resolution", "Map_scale", "Pixel_resolution",
    "UTC_start_time", "UTC_stop_time", "Product_creation_time",
    "Observation_type", "Target_name",
]


def _products(params: dict) -> list[dict]:
    try:
        d = requests.get(ODE, params=params, timeout=180).json()
    except Exception as exc:
        print(f"    query failed: {str(exc)[:70]}")
        return []
    prods = (d.get("ODEResults") or {}).get("Products")
    if not isinstance(prods, dict):
        return []
    got = prods.get("Product")
    if got is None:
        return []
    return [got] if isinstance(got, dict) else got


def query_product(pdsid: str) -> dict | None:
    """Look a NAC scene up in the ODE catalogue.

    ODE identifies NAC products as ``nac.<lowercase product id>`` rather than
    by the bare PRODUCT_ID the label carries, so the plain identifier finds
    nothing. Both forms are tried, then a positional search as a fallback.
    """
    base = dict(target="moon", query="product", results="fmpc",
                output="JSON", limit=5)

    for ident in (f"nac.{pdsid.lower()}", pdsid, pdsid.lower()):
        got = _products({**base, "pdsid": ident})
        for p in got:
            pid = str(p.get("pdsid", "")).lower()
            if pid.endswith(pdsid.lower()):
                return p
        if got:
            return got[0]

    # Fallback: ODE also accepts a free-text product search.
    got = _products({**base, "productid": pdsid})
    return got[0] if got else None


def main() -> int:
    if not NAC_DIR.exists():
        print(f"no NAC directory at {NAC_DIR}")
        return 1

    images = sorted(NAC_DIR.glob("*.IMG"))
    if not images:
        print("no NAC images found")
        return 1

    ok = 0
    for img in images:
        pdsid = img.stem
        print(f"\n{pdsid}")
        p = query_product(pdsid)
        if p is None:
            print("    not found in the ODE catalogue")
            continue

        geom = {}
        for f in GEOMETRY_FIELDS:
            v = p.get(f)
            if v not in (None, "", "N/A", "UNK"):
                geom[f] = v

        inc = geom.get("Incidence_angle")
        lat = geom.get("Center_latitude")
        lon = geom.get("Center_longitude")

        if inc is None or lat is None:
            print("    geometry incomplete — cannot support shadow measurement")
            continue

        out = {
            "product_id": pdsid,
            "source": "PDS Orbital Data Explorer (oderest.rsl.wustl.edu), "
                      "derived from SPICE kernels",
            "retrieved_for": "shadow-based boulder height and georeferencing",
            "geometry": geom,
        }
        # Precompute the quantity actually used downstream, so the assumption
        # is recorded rather than re-derived differently in three places.
        try:
            i = float(inc)
            import math
            out["shadow_factor"] = round(math.tan(math.radians(90.0 - i)), 6)
            out["shadow_note"] = (
                f"boulder height h = shadow_length x {out['shadow_factor']:.4f} "
                f"(incidence {i:.2f} deg)")
        except (TypeError, ValueError):
            pass

        dest = img.with_suffix(".geom.json")
        dest.write_text(json.dumps(out, indent=2), encoding="utf-8")

        print(f"    centre     : {float(lat):.4f} deg, {float(lon):.4f} deg E")
        print(f"    incidence  : {float(inc):.2f} deg")
        if "shadow_factor" in out:
            print(f"    shadow     : 1 m boulder -> "
                  f"{1.0/out['shadow_factor']:.1f} m shadow")
        res = geom.get("Pixel_resolution") or geom.get("Map_scale")
        if res:
            print(f"    resolution : {res}")
        print(f"    written    : {dest.name}")
        ok += 1

    print(f"\n{ok}/{len(images)} scenes have usable geometry")
    return 0 if ok == len(images) else 1


if __name__ == "__main__":
    raise SystemExit(main())
