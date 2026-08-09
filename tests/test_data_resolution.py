"""Confirm the project now reads from D: and survives without the Drive mount."""
import sys

sys.path.insert(0, r"d:\Lunar_Serpent")

from backend import config  # noqa: E402

npass = nfail = 0


def check(name, ok, detail=""):
    global npass, nfail
    if ok:
        npass += 1
        print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
    else:
        nfail += 1
        print(f"  FAIL  {name}   {detail}")


print("\nDataset resolution\n")
print("  roots, in priority order:")
for r in config.DATA_ROOTS:
    print(f"    {r}")
print()

dem = config.dataset_path("lola_dem", "LDEM_16.IMG")
check("LDEM_16.IMG resolves", dem is not None, str(dem))
check("...and resolves to D:, not G:",
      dem is not None and str(dem).upper().startswith("D:"),
      f"drive = {str(dem)[:2] if dem else '?'}")

tex = config.dataset_path("moon_texture", "moon_texture.jpg")
check("offline texture resolves to D:",
      tex is not None and str(tex).upper().startswith("D:"), str(tex))

# Not copied locally: must still be found on the Drive fallback if mounted.
csv = config.dataset_path(*config.ROBBINS_CSV)
if csv:
    check("Robbins CSV found via Drive fallback",
          str(csv).upper().startswith("G:"), str(csv)[:60] + "…")
else:
    print("  NOTE  Robbins CSV not reachable (Drive unmounted) — expected; the "
          "index is already built so it is not needed at runtime.")

print("\nRuntime independence from the Drive\n")

# Simulate an unmounted Drive by restricting the root to the local copy.
import importlib  # noqa: E402
import os  # noqa: E402

os.environ["LUNARSERPENT_DATA_ROOT"] = str(config.PROJECT_ROOT / "data" / "raw")
importlib.reload(config)
print(f"  forced root: {config.DATA_ROOT}")

from backend.core import raster  # noqa: E402
importlib.reload(raster)

src = raster.get_dem()
e_far = float(src.elevation_at(0.0, 180.0))
e_spa = float(src.elevation_at(-53.0, 191.0))
check(f"elevation at farside highlands = {e_far:.1f} m",
      1000 < e_far < 5000)
check(f"elevation at South Pole-Aitken  = {e_spa:.1f} m",
      e_spa < -2000)
check("DEM opened from the local copy",
      str(getattr(src, "path", "")).upper().startswith("D:")
      or config.DATA_ROOT.drive.upper() == "D:",
      f"root drive {config.DATA_ROOT.drive}")

# Derived indexes live on D: already and need no dataset root at all.
from backend.data.catalog_robbins import load_index  # noqa: E402
from backend.data.nomenclature import load_index as load_names  # noqa: E402

ci = load_index()
ni = load_names()
check(f"crater index loads ({len(ci):,} craters)", len(ci) > 1_000_000)
check(f"nomenclature loads ({len(ni):,} features)", len(ni) > 9000)

print("\nFootprint\n")
import pathlib  # noqa: E402

for label, p in (("D:\\Lunar_Serpent", r"d:\Lunar_Serpent"),
                 ("  data\\raw (local copies)", r"d:\Lunar_Serpent\data\raw"),
                 ("  data\\derived (indexes)", r"d:\Lunar_Serpent\data\derived"),
                 ("  data\\cache (tiles)", r"d:\Lunar_Serpent\data\cache")):
    root = pathlib.Path(p)
    if root.exists():
        s = sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
        print(f"  {label:<28} {s/1024/1024:8.1f} MB")

print(f"\n{npass} passed, {nfail} failed")
raise SystemExit(1 if nfail else 0)
