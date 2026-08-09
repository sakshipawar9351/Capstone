"""
Verify the downloaded south-polar datasets: integrity, content and fitness.

Checks that each file parses, that its declared geometry matches its actual
size, and that the values it contains are physically sensible — a file can be
byte-complete and still be unusable if it lacks the metadata the science needs.
That last point is the whole reason the Chandrayaan PNGs failed.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
POLAR = ROOT / "data" / "raw" / "polar"

npass = nfail = 0


def check(name, ok, detail=""):
    global npass, nfail
    if ok:
        npass += 1
        print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
    else:
        nfail += 1
        print(f"  FAIL  {name}   {detail}")


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:,.1f} {u}"
        n /= 1024
    return f"{n:,.1f} TB"


def label_value(txt, key):
    m = re.search(rf"^\s*{key}\s*=\s*(.+?)\s*$", txt, re.M)
    return m.group(1).strip() if m else None


def read_attached_label(path: Path, nbytes=200_000) -> str:
    """LROC NAC products carry their PDS3 label inside the .IMG itself."""
    raw = path.open("rb").read(nbytes)
    txt = raw.decode("ascii", "replace")
    end = txt.find("\nEND\r\n")
    if end < 0:
        end = txt.find("\nEND\n")
    return txt[: end + 6] if end > 0 else txt


# ===========================================================================
print("=" * 76)
print("1. LOLA POLAR DEM  —  ldem_875s_10m_float")
print("=" * 76)

img = POLAR / "dem" / "ldem_875s_10m_float.img"
lbl = POLAR / "dem" / "ldem_875s_10m_float.lbl"

if not img.exists():
    check("DEM present", False, "missing")
else:
    txt = lbl.read_text(errors="replace")
    W = int(float(label_value(txt, "LINE_SAMPLES")))
    H = int(float(label_value(txt, "LINES")))
    bits = int(float(label_value(txt, "SAMPLE_BITS")))
    expect = W * H * bits // 8
    actual = img.stat().st_size

    print(f"  grid          : {W} x {H}, {bits}-bit {label_value(txt,'SAMPLE_TYPE')}")
    print(f"  scale         : {label_value(txt,'MAP_SCALE')}")
    print(f"  projection    : {label_value(txt,'MAP_PROJECTION_TYPE')}")
    print(f"  coverage      : {label_value(txt,'MINIMUM_LATITUDE')} to "
          f"{label_value(txt,'MAXIMUM_LATITUDE')}")
    print(f"  size          : {human(actual)} (expected {human(expect)})")

    check("file size matches the declared grid exactly", actual == expect,
          f"{actual:,} vs {expect:,} bytes")

    a = np.memmap(img, dtype="<f4", mode="r", shape=(H, W))
    samp = np.array(a[::37, ::37], dtype=np.float64)
    finite = samp[np.isfinite(samp)]
    print(f"  sampled       : {finite.size:,} values, "
          f"{finite.min()*1000:.0f} .. {finite.max()*1000:.0f} m")

    check("values are finite and physical",
          finite.size > 100_000 and -12 < finite.min() and finite.max() < 12,
          "km relative to the 1737.4 km sphere")
    check("relief is kilometre-scale, as expected at a polar crater field",
          (finite.max() - finite.min()) * 1000 > 3000,
          f"{(finite.max()-finite.min())*1000:.0f} m across the cap")

# ===========================================================================
print()
print("=" * 76)
print("2. PERMANENTLY SHADOWED REGIONS  —  lpsr_85s_060m")
print("=" * 76)

pimg = POLAR / "psr" / "lpsr_85s_060m_201608.img"
plbl = POLAR / "psr" / "lpsr_85s_060m_201608.lbl"

if not pimg.exists():
    check("PSR present", False, "missing")
else:
    txt = plbl.read_text(errors="replace")
    W = int(float(label_value(txt, "LINE_SAMPLES")))
    H = int(float(label_value(txt, "LINES")))
    bits = int(float(label_value(txt, "SAMPLE_BITS")))
    stype = label_value(txt, "SAMPLE_TYPE")
    expect = W * H * bits // 8
    actual = pimg.stat().st_size

    print(f"  grid          : {W} x {H}, {bits}-bit {stype}")
    print(f"  scale         : {label_value(txt,'MAP_SCALE')}")
    print(f"  coverage      : {label_value(txt,'MINIMUM_LATITUDE')} to "
          f"{label_value(txt,'MAXIMUM_LATITUDE')}")
    print(f"  size          : {human(actual)} (expected {human(expect)})")

    check("file size matches the declared grid", actual == expect,
          f"{actual:,} vs {expect:,}")

    dt = "<f4" if "REAL" in str(stype) else ("<i2" if bits == 16 else "u1")
    b = np.memmap(pimg, dtype=dt, mode="r", shape=(H, W))
    s = np.array(b[::11, ::11], dtype=np.float64)
    s = s[np.isfinite(s)]
    lit = float((s > 0).mean())
    print(f"  illumination  : {lit*100:.1f}% of sampled cells receive some light")
    check("map contains both lit and shadowed cells",
          0.01 < lit < 0.999,
          "a polar map that was all-lit or all-dark would be wrong")

# ===========================================================================
print()
print("=" * 76)
print("3. LROC NAC SCENES  —  the metadata the Chandrayaan PNGs lacked")
print("=" * 76)

for name in ("M1410768185LC.IMG", "M101980409LC.IMG"):
    p = POLAR / "nac" / name
    print(f"\n  --- {name}  ({human(p.stat().st_size) if p.exists() else 'MISSING'})")
    if not p.exists():
        check(f"{name} present", False)
        continue

    txt = read_attached_label(p)
    check(f"{name}: carries an attached PDS3 label",
          "PDS_VERSION_ID" in txt and len(txt) > 500, f"{len(txt):,} chars")

    fields = {
        "INCIDENCE_ANGLE": "solar incidence — REQUIRED for boulder height",
        "EMISSION_ANGLE": "viewing angle",
        "PHASE_ANGLE": "phase geometry",
        "SUB_SOLAR_AZIMUTH": "shadow direction",
        "CENTER_LATITUDE": "position",
        "CENTER_LONGITUDE": "position",
        "LINE_SAMPLES": "width",
        "LINES": "height",
        "PRODUCT_ID": "identity",
    }
    have = {}
    for k, why in fields.items():
        v = label_value(txt, k)
        if v is None:
            for alt in (f"LRO:{k}", k.replace("_", "")):
                v = label_value(txt, alt)
                if v:
                    break
        have[k] = v
        if v:
            print(f"      {k:<22} {str(v)[:30]:<30} {why}")

    # LROC CDR labels carry no geometry — pointing and illumination come from
    # SPICE, and are recovered from ODE into a sidecar. Absence from the label
    # is expected; absence from the sidecar is not.
    check(f"{name}: label omits geometry (expected for a CDR)",
          have.get("INCIDENCE_ANGLE") is None,
          "geometry is SPICE-derived, not embedded")

    import json  # noqa: PLC0415
    side = p.with_suffix(".geom.json")
    check(f"{name}: geometry sidecar present", side.exists(),
          "run scripts/fetch_nac_geometry.py" if not side.exists() else side.name)

    if side.exists():
        g = json.loads(side.read_text())["geometry"]
        inc = float(g["Incidence_angle"])
        lat = float(g["Center_latitude"])
        lon = float(g["Center_longitude"])
        print(f"      centre     {lat:>9.4f}°, {lon:>9.4f}°E")
        print(f"      incidence  {inc:>9.2f}°  "
              f"(sun {90 - inc:.2f}° above the horizon)")

        check(f"{name}: has a usable centre coordinate", -90 <= lat <= 90)
        check(f"{name}: scene lies in the south polar region", lat < -80,
              f"{lat:.2f}°")

        # Honest classification of what this illumination supports.
        sun_elev = 90.0 - inc
        shadow_of_1m = 1.0 / np.tan(np.radians(sun_elev))
        print(f"      a 1 m rock casts a {shadow_of_1m:.0f} m shadow")
        if sun_elev < 2.0:
            print("      -> grazing light: excellent for DETECTING boulders, "
                  "unreliable for MEASURING their height")
        check(f"{name}: illumination geometry is recorded and interpretable",
              0 < sun_elev < 90, f"sun elevation {sun_elev:.2f}°")

# ===========================================================================
print()
print("=" * 76)
print("SUMMARY")
print("=" * 76)
tot = sum(f.stat().st_size for f in POLAR.rglob("*") if f.is_file())
print(f"  {len(list(POLAR.rglob('*.img'))) + len(list(POLAR.rglob('*.IMG')))} "
      f"rasters, {human(tot)} total, in {POLAR}")
print(f"\n  {npass} passed, {nfail} failed")
raise SystemExit(1 if nfail else 0)
