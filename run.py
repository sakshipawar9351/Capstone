#!/usr/bin/env python3
"""
LunarSerpent — single-command launcher.

    python run.py

Checks the environment, reports which datasets resolved, starts the API and
opens the interface. Everything it can diagnose, it diagnoses before serving,
because a stack trace three layers into a memmap is a poor way to learn that a
DEM is missing.

Options
-------
    --check         run the preflight and exit; start nothing
    --test          run the full test suite first, and stop if it fails
    --docs          rebuild the HTML documentation before serving
    --port N        serve on a different port (default from config)
    --host H        bind a different interface (default 127.0.0.1)
    --no-browser    do not open a browser window
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

#: Import name -> pip name. uvicorn is needed to serve, the rest to compute.
REQUIRED = [
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
    ("numpy", "numpy"),
    ("scipy", "scipy"),
    ("PIL", "Pillow"),
    ("markdown", "markdown"),
]
#: Only the test suite needs these.
OPTIONAL = [("requests", "requests")]

BOLD, DIM, RED, GRN, YEL, OFF = (
    "\033[1m", "\033[2m", "\033[31m", "\033[32m", "\033[33m", "\033[0m")


def _supports_colour() -> bool:
    if not sys.stdout.isatty():
        return False
    if sys.platform == "win32":
        try:                                   # enable ANSI on Windows 10+
            import ctypes
            k = ctypes.windll.kernel32
            k.SetConsoleMode(k.GetStdHandle(-11), 7)
            return True
        except Exception:                      # noqa: BLE001
            return False
    return True


if not _supports_colour():
    BOLD = DIM = RED = GRN = YEL = OFF = ""

OK, BAD, WARN = f"{GRN}OK{OFF}", f"{RED}MISSING{OFF}", f"{YEL}WARN{OFF}"


def rule(title: str = "") -> None:
    print(f"\n{BOLD}{title}{OFF}" if title else "")
    print(DIM + "-" * 68 + OFF)


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

def check_python() -> bool:
    v = sys.version_info
    ok = v >= (3, 10)
    print(f"  {OK if ok else BAD:<20} Python {v.major}.{v.minor}.{v.micro}"
          + ("" if ok else "  — 3.10 or newer required"))
    return ok


def check_packages() -> bool:
    missing = []
    for mod, pkg in REQUIRED:
        found = importlib.util.find_spec(mod) is not None
        print(f"  {OK if found else BAD:<20} {pkg}")
        if not found:
            missing.append(pkg)
    for mod, pkg in OPTIONAL:
        found = importlib.util.find_spec(mod) is not None
        print(f"  {OK if found else WARN:<20} {pkg}"
              + ("" if found else "  — only needed by the test suite"))
    if missing:
        print(f"\n  {RED}Install what is missing:{OFF}\n"
              f"      python -m pip install {' '.join(missing)}")
    return not missing


def check_data() -> bool:
    """Report where each dataset resolved. Missing data degrades, not crashes."""
    from backend import config as C

    print(f"  {DIM}data roots searched, in order:{OFF}")
    for cand in C._DATA_ROOT_CANDIDATES:
        print(f"      {'found  ' if Path(cand).exists() else 'absent '} {cand}")

    dem = C.DEM_PRODUCTS[C.DEFAULT_DEM]
    checks = [
        ("global DEM (image)", C.dataset_path("lola_dem", f"{dem.product_id}.IMG")),
        ("global DEM (label)", C.dataset_path("lola_dem", f"{dem.product_id}.LBL")),
        ("Robbins crater catalogue", C.dataset_path(*C.ROBBINS_CSV)),
        ("polar DEM 10 m", C.dataset_path("polar", "dem", "ldem_875s_10m_float.img")),
    ]
    derived = [
        ("IAU nomenclature index", C.IAU_INDEX),
        ("Robbins memmap index", C.INDEX_DIR / "robbins_meta.json"),
    ]

    print()
    essential_ok = True
    for label, p in checks:
        good = p is not None
        print(f"  {OK if good else BAD:<20} {label}")
        if good:
            print(f"  {'':<12} {DIM}{p}{OFF}")
        if not good and "global DEM" in label:
            essential_ok = False
    for label, p in derived:
        good = p.exists()
        print(f"  {OK if good else WARN:<20} {label}"
              + ("" if good else "  — built on first use"))
    return essential_ok


def _dir_bytes(p: Path) -> tuple[int, int]:
    """Total bytes and file count under a directory."""
    n = b = 0
    if p.exists():
        for f in p.rglob("*"):
            if f.is_file():
                n += 1
                try:
                    b += f.stat().st_size
                except OSError:
                    pass
    return b, n


def _mb(b: int) -> str:
    return f"{b / 1048576:,.1f} MB"


def check_storage() -> None:
    """Where this project puts bytes, and how many.

    Worth reporting every run rather than on request. "Is this filling my
    drive?" is a question that should be answerable by looking, not by
    measuring the whole disk and reasoning about what else lives on it — and
    the honest answer includes naming the drive, because a project that writes
    to a drive nobody offered it is a problem regardless of the amount.
    """
    from backend import config as C

    caches = [
        ("basemap tiles", C.TILE_CACHE_DIR, C.TILE_CACHE_MAX_BYTES),
        ("analysed regions", C.CACHE_DIR / "aoi", 256 * 1024 * 1024),
        ("browser test profiles", C.CACHE_DIR / "browser-profiles", None),
        ("derived indices", C.DERIVED_DIR, None),
    ]

    total = 0
    for label, path, cap in caches:
        b, n = _dir_bytes(path)
        total += b
        cap_s = f"  cap {_mb(cap)}" if cap else ""
        pct = f"  [{b / cap * 100:3.0f}%]" if cap else ""
        print(f"  {_mb(b):>12}  {n:>6} files  {label}{cap_s}{pct}")

    print(f"  {_mb(total):>12}          total, all of it under "
          f"{C.DATA_DIR}")

    # The claim that matters, checked rather than asserted.
    drive = Path(C.PROJECT_ROOT).drive.upper() or "/"
    system = (os.environ.get("SystemDrive", "C:").upper()
              if sys.platform == "win32" else "/")
    if sys.platform == "win32":
        on_system = drive == system
        print(f"\n  {WARN if on_system else OK:<20} "
              + (f"this project lives on the system drive ({drive})"
                 if on_system else
                 f"nothing is written to the system drive ({system}) — "
                 f"everything is on {drive}"))
        try:
            import shutil as _sh
            for d in dict.fromkeys([system + "\\", drive + "\\"]):
                u = _sh.disk_usage(d)
                print(f"  {'':<20} {d[:2]}  {u.free / 2**30:,.1f} GB free "
                      f"of {u.total / 2**30:,.1f} GB")
        except Exception:  # noqa: BLE001
            pass


def check_env() -> None:
    from backend import config as C

    tok = getattr(C, "CESIUM_ION_TOKEN", "") or ""
    if tok:
        print(f"  {OK:<20} Cesium ion token loaded from .env "
              f"({DIM}asset {C.CESIUM_MOON_ASSET}{OFF})")
    else:
        print(f"  {WARN:<20} no Cesium ion token — the Terrain globe will not "
              f"load\n  {'':<12} {DIM}put CESIUM_ION_TOKEN=... in .env{OFF}")


def port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex((host, port)) != 0


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def run_tests() -> bool:
    import subprocess
    rule("Test suite")
    print(f"  {DIM}running tests/run_all.py — this takes about 90 s{OFF}\n")
    r = subprocess.run([sys.executable, "tests/run_all.py"], cwd=ROOT)
    return r.returncode == 0


def build_docs() -> None:
    import subprocess
    rule("Documentation")
    subprocess.run([sys.executable, "scripts/build_docs.py"], cwd=ROOT)


def report_components() -> None:
    """Ask the application itself what loaded. Cannot drift from the code."""
    from backend.main import health

    rule("Component status")
    h = health()
    for name, st in h["components"].items():
        if st.get("ok"):
            extra = {k: v for k, v in st.items() if k != "ok"}
            bits = ", ".join(f"{k}={v}" for k, v in extra.items())
            print(f"  {OK:<20} {name}  {DIM}{bits}{OFF}")
        else:
            print(f"  {BAD:<20} {name}  {st.get('detail', '')}")
    print(f"\n  {DIM}frame: {h['reference_frame']}{OFF}")


def open_when_ready(url: str, host: str, port: int) -> None:
    """Open the browser once the socket accepts, not merely once we asked."""
    for _ in range(120):                       # up to ~30 s
        time.sleep(0.25)
        if not port_free(host, port):          # something is listening
            time.sleep(0.4)                    # let the first route bind
            try:
                webbrowser.open(url)
            except Exception:                  # noqa: BLE001
                pass
            return


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(add_help=True, description="Run LunarSerpent.")
    ap.add_argument("--check", action="store_true", help="preflight only")
    ap.add_argument("--test", action="store_true", help="run the test suite first")
    ap.add_argument("--docs", action="store_true", help="rebuild HTML docs first")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--host", default=None)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    print(f"\n{BOLD}LunarSerpent{OFF}  {DIM}lunar surface analysis and "
          f"traverse planning{OFF}")

    rule("Environment")
    if not check_python():
        return 1
    if not check_packages():
        return 1

    rule("Datasets")
    data_ok = check_data()

    rule("Storage")
    check_storage()

    rule("Configuration")
    check_env()

    from backend import config as C
    host = args.host or C.HOST
    port = args.port or C.PORT

    if not data_ok:
        print(f"\n  {RED}The global DEM did not resolve.{OFF} Elevation, slope "
              f"and crater\n  analysis will fail. Fetch it with:\n"
              f"      python scripts/fetch_dem.py --download")

    if args.check:
        rule("Preflight only — nothing started")
        return 0 if data_ok else 1

    if args.test and not run_tests():
        print(f"\n  {RED}Tests failed — not starting the server.{OFF}")
        return 1

    if args.docs:
        build_docs()

    if not port_free(host, port):
        print(f"\n  {RED}Port {port} is already in use.{OFF}")
        print(f"  Either something is already serving on http://{host}:{port}/, "
              f"or a\n  previous run did not shut down. Try:  "
              f"python run.py --port {port + 1}")
        return 1

    report_components()

    url = f"http://{host}:{port}/"
    rule("Serving")
    print(f"  {BOLD}OPEN THIS{OFF}   {BOLD}{url}{OFF}   {DIM}<- the Moon globe{OFF}")
    print(f"\n  {DIM}The same server also exposes, if you want them:{OFF}")
    print(f"  {DIM}  {url}api/docs               API explorer{OFF}")
    print(f"  {DIM}  {url}api/v1/meta/health     status as JSON{OFF}")
    print(f"\n  {DIM}Ctrl+C to stop{OFF}\n")

    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url, host, port),
                         daemon=True).start()

    import uvicorn
    from backend.main import app
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    except KeyboardInterrupt:
        pass
    print(f"\n{DIM}stopped.{OFF}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
