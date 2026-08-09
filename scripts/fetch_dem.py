"""
Fetch a LOLA DEM product to the project's local data directory.

    python scripts/fetch_dem.py ldem_64

The PDS3 label is fetched first and *verified against the compiled-in registry*
before the raster is downloaded.  That ordering is deliberate: the label is 4 KB
and the raster is half a gigabyte, so a geometry mismatch should be caught
before spending the bandwidth, not after.  ``raster.py`` emits a runtime warning
when it falls back to registry geometry, and this script exists to make that
warning go away for the products we actually rely on.

Downloads resume: an interrupted transfer is continued with a Range request
rather than restarted.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests  # noqa: E402

from backend.config import DEM_PRODUCTS, PROJECT_ROOT  # noqa: E402
from backend.core.pds import parse_label  # noqa: E402

DEST = PROJECT_ROOT / "data" / "raw" / "lola_dem"


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:,.1f} {unit}"
        n /= 1024
    return f"{n:,.1f} TB"


def fetch_label(product) -> dict:
    """Download and parse the .LBL, and check it against the registry."""
    dest = DEST / f"{product.product_id}.LBL"
    print(f"label   {product.label_url}")
    r = requests.get(product.label_url, timeout=120)
    r.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    print(f"        saved {human(len(r.content))} -> {dest.name}")

    lbl = parse_label(r.text)
    checks = [
        ("LINE_SAMPLES", product.width),
        ("LINES", product.height),
    ]
    ok = True
    for field, expected in checks:
        got = lbl.get(field)
        got = int(got) if got is not None else None
        mark = "ok " if got == expected else "MISMATCH"
        if got != expected:
            ok = False
        print(f"        {field:<16} label={got!s:<8} registry={expected:<8} {mark}")

    scale = lbl.get("MAP_SCALE")
    if scale is not None:
        try:
            s = float(str(scale).split()[0])
            d = abs(s - product.scale_m_px)
            print(f"        {'MAP_SCALE':<16} label={s:<8.3f} "
                  f"registry={product.scale_m_px:<8.3f} "
                  f"{'ok ' if d < 0.01 else 'MISMATCH'}")
            ok = ok and d < 0.01
        except (ValueError, IndexError):
            pass

    if not ok:
        raise SystemExit(
            "\nLabel disagrees with the compiled-in registry. Refusing to "
            "download until backend/config.py is corrected — using wrong "
            "geometry would silently misplace every elevation."
        )
    print("        label agrees with registry\n")
    return lbl


def fetch_raster(product) -> Path:
    dest = DEST / f"{product.product_id}.IMG"
    expected = product.nbytes
    have = dest.stat().st_size if dest.exists() else 0

    if have == expected:
        print(f"raster  already complete: {dest.name} ({human(have)})")
        return dest
    if have > expected:
        print(f"raster  {dest.name} is larger than expected; re-downloading")
        dest.unlink()
        have = 0

    mode = "ab" if have else "wb"
    headers = {"Range": f"bytes={have}-"} if have else {}
    if have:
        print(f"raster  resuming at {human(have)} of {human(expected)}")
    else:
        print(f"raster  {product.url}")
        print(f"        {human(expected)} to fetch")

    t0 = time.time()
    done = have
    with requests.get(product.url, headers=headers, stream=True,
                      timeout=600) as r:
        r.raise_for_status()
        with open(dest, mode) as fh:
            last = 0.0
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                fh.write(chunk)
                done += len(chunk)
                now = time.time()
                if now - last > 2.0:
                    last = now
                    pct = done / expected * 100
                    rate = (done - have) / max(now - t0, 1e-6)
                    eta = (expected - done) / rate if rate > 0 else 0
                    print(f"        {pct:5.1f}%  {human(done)}  "
                          f"{human(rate)}/s  eta {eta/60:.1f} min", flush=True)

    size = dest.stat().st_size
    print(f"        done: {human(size)} in {(time.time()-t0)/60:.1f} min")
    if size != expected:
        raise SystemExit(f"size mismatch: got {size}, expected {expected}")
    return dest


def main() -> int:
    key = sys.argv[1] if len(sys.argv) > 1 else "ldem_64"
    if key not in DEM_PRODUCTS:
        print(f"unknown product {key!r}; have {sorted(DEM_PRODUCTS)}")
        return 2
    product = DEM_PRODUCTS[key]

    print(f"\n=== {product.product_id} — {product.ppd} ppd, "
          f"{product.scale_m_px:.1f} m/px ===\n")
    fetch_label(product)
    path = fetch_raster(product)

    # Prove it reads correctly before declaring success.
    print("\nverifying...")
    from backend.core.raster import DEMSource

    src = DEMSource(key)
    for lat, lon, want, label in [
        (0.0, 180.0, (2000, 3500), "farside highlands"),
        (-53.0, 191.0, (-9000, -5000), "South Pole-Aitken"),
    ]:
        e = float(src.elevation_at(lat, lon))
        ok = want[0] <= e <= want[1]
        print(f"  {'PASS' if ok else 'FAIL'}  {label:<22} {e:>9.1f} m "
              f"(expect {want[0]}..{want[1]})")
        if not ok:
            return 1

    print(f"\n{product.product_id} ready at {path}")
    print(f"Set DEFAULT_DEM = \"{key}\" in backend/config.py to use it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
