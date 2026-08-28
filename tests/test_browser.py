"""
Run the frontend in a real browser.

Everything else about the frontend is checked by reading the source: that a
method exists on both renderers, that a handler is bound, that no identifier is
used above its declaration. Those catch a lot, and they caught the temporal
dead zone that once took the whole application down — but they cannot tell you
the page actually *boots*, that a module still parses when a browser loads it,
or that a 422 reaches the user as a sentence rather than a status code.

This drives headless Chrome, which is already installed on this machine, so
nothing has to be added to run it. Two passes:

1. **Boot** — load the app and inspect the resulting DOM. Several controls are
   filled in by JavaScript from ``/plan/options``, so finding them populated
   proves the boot sequence completed rather than merely that the HTML shipped.

2. **Harness** — ``browser_harness.html`` imports the application's own modules
   and exercises them against the live server: formatting helpers, the API
   client, error propagation, and a whole plan submitted and polled from the
   browser. It is copied into ``frontend/`` for the run so ES module imports
   resolve from the same origin, and removed afterwards.

Skips cleanly when Chrome or the server is absent.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
HARNESS = Path(__file__).parent / "browser_harness.html"
BASE = "http://127.0.0.1:8765"

#: Where the throwaway browser profiles go.
#:
#: `tempfile` would put them under the system temp directory, which on Windows
#: is on the system drive — so running the tests quietly wrote tens of
#: megabytes of Chrome profile to C: on every pass, on a machine where the
#: project deliberately keeps everything on its own drive. They are deleted
#: after each run either way, but a test suite should not spend a drive the
#: user did not offer it. Under the project's own cache, they are visible,
#: countable, and on the same disk as everything else this project owns.
PROFILE_DIR = ROOT / "data" / "cache" / "browser-profiles"

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome", "/usr/bin/chromium",
]

npass = nfail = 0


def check(name, ok, detail=""):
    global npass, nfail
    if ok:
        npass += 1
        print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
    else:
        nfail += 1
        print(f"  FAIL  {name}   {detail}")


def find_chrome() -> str | None:
    for p in CHROME_CANDIDATES:
        if Path(p).exists():
            return p
    return shutil.which("chrome") or shutil.which("chromium")


def dump_dom(chrome: str, url: str, budget_ms: int = 20000) -> str:
    """Load a page, let its JavaScript run, and return the resulting DOM."""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=PROFILE_DIR) as profile:
        # Bytes, not text: the page is UTF-8 and Python would otherwise decode
        # it with the Windows console codepage and die on the first degree sign.
        r = subprocess.run(
            [chrome, "--headless", "--disable-gpu", "--no-sandbox",
             f"--user-data-dir={profile}",
             f"--virtual-time-budget={budget_ms}", "--dump-dom", url],
            capture_output=True, timeout=budget_ms / 1000 + 90,
        )
    return (r.stdout or b"").decode("utf-8", errors="replace")


def server_up() -> bool:
    try:
        import requests
        requests.get(f"{BASE}/api/v1/meta/health", timeout=5)
        return True
    except Exception:                                    # noqa: BLE001
        return False


chrome = find_chrome()
if chrome is None:
    print("no Chrome or Edge found — skipping browser tests")
    raise SystemExit(0)
if not server_up():
    print(f"server not reachable at {BASE} — skipping browser tests")
    raise SystemExit(0)

print(f"\nBrowser: {Path(chrome).name}\n")

# ---------------------------------------------------------------------------
print("The application boots and its JavaScript runs\n")

dom = dump_dom(chrome, f"{BASE}/")
check("the page returns a DOM", len(dom) > 5000, f"{len(dom):,} chars")

# These are written into the DOM by boot(); their presence means the startup
# sequence reached the end rather than dying part way.
for label, needle in [
    ("rover list filled from /plan/options", "VIPER-class"),
    ("soil list filled from /plan/options", "Apollo nominal"),
    ("Plan panel rendered", 'id="tab-plan"'),
    ("layer panel rendered", "LROC WAC"),
    ("both renderers offered", "rnd-cesium"),
]:
    check(label, needle in dom)

check("no visible startup failure",
      "Startup failed" not in dom, "loading overlay would say so")

check("the globe offers to open a region in its own tab",
      'id="btn-aoi-open"' in dom, "region.html?south=...")

# ---------------------------------------------------------------------------
print("\nThe region page renders a whole analysis from its URL alone\n")

# A site AOI at the south pole: 10 m polar data, so every layer is real and
# the capability block should say the region can certify a traverse. The
# region travels entirely in the query string, which is the property being
# tested — a tab must be reloadable and shareable, not a view that only exists
# because the globe was in a particular state when it was opened.
REGION = "south=-89.50&north=-89.42&west=218&east=226&rover=viper&soil=nominal"
dom = dump_dom(chrome, f"{BASE}/region.html?{REGION}&finest=0", budget_ms=90000)

check("the region page returns a DOM", len(dom) > 3000, f"{len(dom):,} chars")
check("it resolved the region from the URL", "LDEM_875S_10M" in dom,
      "source named in the header line")
check("it reports the posting it actually got", "10 m" in dom)
check("capability is stated before any map is read",
      "Certifies a traverse" in dom and "Craters measurable" in dom)
check("the boulder exclusion is quantified, not just asserted",
      "cannot be recovered from this DEM at any effort" in dom
      and "% of one" in dom,
      "scope has to carry a number or it reads as an excuse")

# The layer grid is built by JavaScript from /aoi/layers, so finding the
# captions proves the catalogue was fetched and the grid was populated.
for label in ("Hillshade", "Slope", "Wheel slip", "Hazard class",
              "Risk", "Cost surface"):
    check(f"the {label.lower()} panel is present", f">{label}<" in dom)

check("every layer resolved to a picture rather than an error",
      dom.count("blob:") >= 8 and 'class="layer err"' not in dom,
      f"{dom.count('blob:')} images rendered")
check("each map carries the numeric range its colours mean",
      dom.count("rng") >= 8 and "rendering…" not in dom,
      "a colour with no numbers beside it is decoration")
check("terrain statistics were computed, not left loading",
      "mean slope" in dom and "passable" in dom and "analysing…" not in dom)
check("the hazard legend is filled from the server's own class table",
      "Impassable" in dom and "Marginal" in dom)

# The 3D surface. WebGL may or may not be available in this headless build, so
# the mesh being *fetched and described* is what is asserted — the caption is
# written from the response headers, and it cannot appear unless the binary
# came back and parsed.
check("the surface section fetched and described a real mesh",
      "triangles ·" in dom and "of relief across" in dom,
      dom[dom.find("triangles ·") - 12:dom.find("triangles ·") + 4].strip()
      if "triangles ·" in dom else "no caption written")
check("the surface says shading is not illumination",
      "not from a sun" in dom,
      "the brief rules out illumination effects")
check("vertical exaggeration is stated in the view, not just the caption",
      "vertical" in dom and 'id="r3d-vx"' in dom)
check("the drape menu offers imagery and every analysis layer",
      "Kaguya imagery" in dom and "Plain relief shading" in dom
      and dom.count("<option") >= 12)

# ---------------------------------------------------------------------------
print("\nA drape finer than the DEM under it is called out as such\n")

# Equatorial ground: 474 m LOLA against a 20.8 m orthomosaic. The imagery shows
# craters the elevation model does not contain, and a reader who took that for
# measured relief would be trusting terrain the analysis never saw.
# Pinned to the coarse source on purpose: this caveat exists for the case
# where imagery is far finer than the DEM under it, and at 29.6 m the Kaguya
# mosaic is only 1.4x finer, which is below the threshold that fires it.
EQ = "south=-0.20&north=0.12&west=0.03&east=0.36&drape=photo&finest=0"
dom_eq = dump_dom(chrome, f"{BASE}/region.html?{EQ}", budget_ms=90000)
check("the coarse equatorial region still builds a surface",
      "triangles ·" in dom_eq, "474 m LOLA")
check("the imagery/DEM resolution mismatch is stated plainly",
      "finer than the" in dom_eq and "not as measured relief" in dom_eq,
      "craters in the drape are not in the DEM")
check("and it is marked as a caveat rather than blended into the caption",
      'class="mismatch"' in dom_eq)

# ---------------------------------------------------------------------------
print("\nThe region page reaches for the best data, the globe stays instant\n")

# The distinction that answers the resolution problem. Dragging a box must
# stay in milliseconds, so the globe's preview uses local data. Opening a
# region is a commitment, and there the page asks for the finest validated
# source — which at the equator is 29.6 m rather than 473.8 m, and moves the
# smallest detectable crater from 1,421 m to 89 m. Measured against the Apollo
# sites, the coarse posting understates p99 slope by 2.7 to 5.5 times.
import json as _json
import urllib.request as _url

def _preview(extra=""):
    u = (f"{BASE}/api/v1/aoi/preview?south=20.11&north=20.27"
         f"&west=30.69&east=30.85{extra}")
    with _url.urlopen(u, timeout=30) as r:
        return _json.load(r)["aoi"]

fast, finest = _preview(), _preview("&finest=true")
check("the globe's preview stays on fast local data",
      fast["source"]["product_id"] == "LDEM_64",
      f"{fast['source']['product_id']} at {fast['cell_m']} m")
check("asking for the finest reaches the streamed 29.6 m product",
      finest["cell_m"] < fast["cell_m"] / 10,
      f"{finest['source']['product_id']} at {finest['cell_m']} m")
check("and that moves crater detection below the catalogue's 1 km floor",
      finest["capability"]["crater_detect_floor_m"] < 1000
      <= fast["capability"]["crater_detect_floor_m"],
      f"{fast['capability']['crater_detect_floor_m']:.0f} m -> "
      f"{finest['capability']['crater_detect_floor_m']:.0f} m; the Robbins "
      f"catalogue stops at 1,000 m, so only the finer one can contribute")

# ---------------------------------------------------------------------------
print("\nThe application's own modules, executed in the browser\n")

served = FRONTEND / "__harness__.html"
try:
    shutil.copyfile(HARNESS, served)
    dom = dump_dom(chrome, f"{BASE}/__harness__.html", budget_ms=60000)
finally:
    served.unlink(missing_ok=True)          # never ship a test page

start = dom.find('id="results">')
body = dom[start + len('id="results">'):] if start >= 0 else ""
body = body[:body.find("</div>")] if "</div>" in body else body
lines = [ln for ln in body.replace("&amp;", "&").splitlines() if "\t" in ln]

if not lines:
    check("the harness reported results", False,
          "no results element — the module may have failed to load")
else:
    for ln in lines:
        parts = ln.split("\t")
        status, name = parts[0].strip(), parts[1]
        detail = parts[2] if len(parts) > 2 else ""
        check(name, status == "PASS", detail)

print(f"\n{npass} passed, {nfail} failed")
raise SystemExit(1 if nfail else 0)
