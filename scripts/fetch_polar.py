"""
Fetch south-polar data for metre-scale hazard analysis.

    python scripts/fetch_polar.py --list      # show what would be fetched
    python scripts/fetch_polar.py --download  # actually fetch

Everything lands in D:\\Lunar_Serpent\\data\\raw\\polar\\. Nothing is written
outside the project.

Why these products
------------------
Our working DEM is LOLA LDEM_64 at 474 m/px. A rover experiences slope over
roughly its own wheelbase — about 2 m — so a 474 m baseline averages away every
feature that actually decides whether a traverse is safe. The LOLA polar DEMs
are gridded in polar stereographic at 5–40 m, which brings the measurement
scale within reach of the vehicle scale for the first time.

NAC scenes are fetched with their PDS3 labels because the label carries the
solar incidence angle, and boulder height follows from shadow length as
h = L · tan(90° − i). Without the label an image is unusable for hazard work,
which is precisely the limitation of the ungeoreferenced OHRC PNGs.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests  # noqa: E402

from backend.config import PROJECT_ROOT  # noqa: E402

ODE = "https://oderest.rsl.wustl.edu/live2/"
DEST = PROJECT_ROOT / "data" / "raw" / "polar"

#: Chosen from the ODE catalogue. 10 m/px is 47× finer than LDEM_64 and keeps
#: the download under a gigabyte.
WANTED_DEM = "ldem_875s_10m_float"
WANTED_PSR = "LPSR_85S_060M_201608"

#: Two scenes, not three. Polar NAC frames turn out to be ~516 MB each rather
#: than the ~270 MB assumed when the budget was agreed, so three would have
#: overshot by nearly a gigabyte. Two is enough to work with: one gives the
#: shadow measurements, the second provides an independent check under
#: different illumination, which is what validates the method rather than
#: merely demonstrating it.
N_NAC = 2


def human(n: float) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:,.1f} {u}"
        n /= 1024
    return f"{n:,.1f} TB"


def search(pt, iid, minlat, maxlat, limit=200):
    p = dict(target="moon", query="product", results="fmpc", output="JSON",
             ihid="LRO", iid=iid, pt=pt, limit=limit,
             minlat=minlat, maxlat=maxlat, westlon=0, eastlon=360)
    d = requests.get(ODE, params=p, timeout=240).json()
    prods = (d.get("ODEResults") or {}).get("Products")
    if not isinstance(prods, dict):
        return []
    got = prods.get("Product")
    if got is None:
        return []
    return [got] if isinstance(got, dict) else got


def files_of(p):
    pf = (p.get("Product_files") or {}).get("Product_file") or []
    if isinstance(pf, dict):
        pf = [pf]
    return pf


def pick_targets():
    """Resolve the products we want into a concrete download list."""
    targets = []

    # -- polar DEM -------------------------------------------------------
    for p in search("GDRDEM", "LOLA", -90, -80, limit=80):
        if str(p.get("pdsid", "")).lower() != WANTED_DEM:
            continue
        for f in files_of(p):
            url = f.get("URL", "")
            kb = float(f.get("KBytes", 0))
            # Skip browse imagery and checksums; keep the raster and its label.
            if url.lower().endswith((".img", ".lbl")):
                targets.append(("dem", url, kb))
        break

    # -- permanently shadowed regions ------------------------------------
    for p in search("GDRPSR", "LOLA", -90, -80, limit=40):
        if WANTED_PSR.lower() not in str(p.get("pdsid", "")).lower():
            continue
        for f in files_of(p):
            url = f.get("URL", "")
            kb = float(f.get("KBytes", 0))
            if url.lower().endswith((".img", ".lbl", ".tif")):
                targets.append(("psr", url, kb))
        break

    # -- NAC scenes near the pole ----------------------------------------
    nac = []
    for p in search("CDRNAC4", "LROC", -90, -88, limit=60):
        try:
            inc = float(p.get("Incidence_angle"))
        except (TypeError, ValueError):
            continue
        fs = files_of(p)
        mb = sum(float(f.get("KBytes", 0)) for f in fs) / 1024
        # Prefer moderate size and the most informative shadow geometry.
        nac.append((abs(inc - 75.0), mb, p, fs))
    nac.sort(key=lambda t: (t[0], t[1]))

    for _, _mb, p, fs in nac[:N_NAC]:
        for f in fs:
            url = f.get("URL", "")
            kb = float(f.get("KBytes", 0))
            if url.lower().endswith((".img", ".lbl")):
                targets.append((f"nac:{p.get('pdsid')}", url, kb))

    return targets


def download(url, dest: Path, expect_kb: float):
    dest.parent.mkdir(parents=True, exist_ok=True)
    have = dest.stat().st_size if dest.exists() else 0
    expect = int(expect_kb * 1024)

    if have and expect and abs(have - expect) < 4096:
        print(f"    already have {dest.name} ({human(have)})")
        return True

    headers = {"Range": f"bytes={have}-"} if have else {}
    mode = "ab" if have else "wb"
    t0, done, last = time.time(), have, 0.0

    try:
        with requests.get(url, headers=headers, stream=True, timeout=600) as r:
            r.raise_for_status()
            with open(dest, mode) as fh:
                for chunk in r.iter_content(1024 * 1024):
                    fh.write(chunk)
                    done += len(chunk)
                    now = time.time()
                    if now - last > 3.0:
                        last = now
                        rate = (done - have) / max(now - t0, 1e-6)
                        pct = (done / expect * 100) if expect else 0
                        print(f"      {pct:5.1f}%  {human(done)}  "
                              f"{human(rate)}/s", flush=True)
    except Exception as exc:
        print(f"    FAILED {dest.name}: {str(exc)[:70]}")
        return False

    print(f"    done  {dest.name}  {human(dest.stat().st_size)}")
    return True


def main() -> int:
    do_download = "--download" in sys.argv

    print("\nResolving products from the PDS catalogue…\n")
    targets = pick_targets()
    if not targets:
        print("Nothing resolved — the catalogue query returned no matches.")
        return 1

    groups: dict[str, list] = {}
    for kind, url, kb in targets:
        groups.setdefault(kind.split(":")[0], []).append((kind, url, kb))

    total = 0.0
    for g, items in groups.items():
        gb = sum(kb for _, _, kb in items) / 1024
        total += gb
        print(f"  {g:<6} {len(items):>2} file(s)  {gb:>9.1f} MB")
        for _, url, kb in items:
            print(f"           {url.rsplit('/', 1)[-1][:52]:<52} {kb/1024:>8.1f} MB")

    print(f"\n  TOTAL {total:.0f} MB -> {DEST}")

    if not do_download:
        print("\n  Nothing downloaded. Re-run with --download to fetch.")
        return 0

    print("\nDownloading…\n")
    ok = 0
    for kind, url, kb in targets:
        sub = kind.split(":")[0]
        name = url.rsplit("/", 1)[-1]
        print(f"  [{sub}] {name}")
        if download(url, DEST / sub / name, kb):
            ok += 1

    print(f"\n{ok}/{len(targets)} files retrieved into {DEST}")
    return 0 if ok == len(targets) else 1


if __name__ == "__main__":
    raise SystemExit(main())
