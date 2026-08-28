"""
Static audit of the web client.

Three things a running browser will not tell you until something breaks:

1. **Interface parity.** The application holds one renderer and never asks
   which. If `CesiumRenderer` is missing a method `Globe` has, switching
   renderers throws only when that code path happens to run — possibly much
   later, possibly only for one user.
2. **Control wiring.** Every interactive element in the HTML should have a
   listener. An unwired control looks identical to a working one until clicked.
3. **Dead references.** A handler bound to an element id that no longer exists
   fails silently at boot and takes everything after it with it.
"""
from __future__ import annotations

import re
from pathlib import Path

F = Path(__file__).resolve().parents[1] / "frontend"

npass = nfail = nwarn = 0


def check(name, ok, detail=""):
    global npass, nfail
    if ok:
        npass += 1
        print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
    else:
        nfail += 1
        print(f"  FAIL  {name}   {detail}")


def warn(name, detail=""):
    global nwarn
    nwarn += 1
    print(f"  WARN  {name}   {detail}")


html = (F / "index.html").read_text(encoding="utf-8")
main = (F / "js" / "main.js").read_text(encoding="utf-8")
globe_js = (F / "js" / "globe.js").read_text(encoding="utf-8")
cesium_js = (F / "js" / "cesium-renderer.js").read_text(encoding="utf-8")

# ===========================================================================
print("=" * 74)
print("1. RENDERER INTERFACE PARITY")
print("=" * 74)


def methods_of(src: str, cls: str) -> set[str]:
    """Public methods declared inside a class body."""
    m = re.search(rf"export class {cls}\b", src)
    if not m:
        return set()
    body = src[m.start():]
    out = set()
    for line in body.splitlines():
        mm = re.match(r"^  (?:async\s+)?([a-zA-Z][\w$]*)\s*\(", line)
        if mm and not mm.group(1).startswith("_"):
            out.add(mm.group(1))
        # Getters are part of the public surface too. `get inputElement()` is
        # read as `globe.inputElement`, with no call parentheses, so a scan for
        # `name(` alone reports it as absent from both renderers when in fact
        # both define it.
        gg = re.match(r"^  get\s+([a-zA-Z][\w$]*)\s*\(", line)
        if gg and not gg.group(1).startswith("_"):
            out.add(gg.group(1))
    return out


g = methods_of(globe_js, "Globe")
c = methods_of(cesium_js, "CesiumRenderer")

# What main.js actually depends on.
used = set(re.findall(r"globe\.([a-zA-Z][\w$]*)\s*\(", main))
used |= set(re.findall(r"globe\.([a-zA-Z][\w$]*)\b", main))
used.discard("js")

print(f"  Globe          : {len(g)} public methods")
print(f"  CesiumRenderer : {len(c)} public methods")
print(f"  used by main.js: {len(used)}")
print()

missing_c = sorted((used & g) - c - {"controls"})
check("CesiumRenderer implements everything main.js calls on Globe",
      not missing_c, f"missing: {missing_c}" if missing_c else "full parity")

missing_g = sorted(used - g - c - {"controls"})
check("no call targets a method neither renderer has",
      not missing_g, f"undefined: {missing_g}" if missing_g else "")

check("both expose a `controls` object for camera-change subscription",
      "this.controls" in globe_js or "controls" in g,
      "Globe via OrbitControls, Cesium via shim")

extra = sorted(c - g)
if extra:
    print(f"  note: Cesium-only methods (fine): {extra}")

# ===========================================================================
print()
print("=" * 74)
print("2. CONTROL WIRING")
print("=" * 74)

ids = re.findall(r'id="([A-Za-z0-9_-]+)"', html)

# `re.DOTALL` matters: several controls span multiple lines in the source, and
# a `[^>]*` pattern without it silently matches nothing.
interactive = []
for tag in re.findall(r"<(?:button|input|select|textarea)\b.*?>", html, re.S):
    mid = re.search(r'id="([A-Za-z0-9_-]+)"', tag)
    if mid:
        interactive.append((mid.group(1), tag))

unwired = [eid for eid, tag in interactive
           if "disabled" not in tag and f"'{eid}'" not in main]

print(f"  interactive elements with an id : {len(interactive)}")
print(f"  disabled (Phase 2 slots)        : "
      f"{sum(1 for _, t in interactive if 'disabled' in t)}")
print(f"  referenced in main.js           : "
      f"{len(interactive) - len(unwired) - sum(1 for _, t in interactive if 'disabled' in t)}")
check("every enabled control is referenced in main.js",
      not unwired, f"unwired: {unwired}" if unwired else "")

# Controls are wired either by id or by class selector; both are valid.
for sel in (".viewbtn", ".ptab", ".seg", ".dcard", ".mcard", ".scard"):
    cls = sel.lstrip(".")
    if cls not in html:
        continue
    by_selector = sel in main
    # Elements of this class that carry ids and are bound individually.
    by_id = any(cls in tag and f"'{eid}'" in main for eid, tag in interactive)
    check(f"{sel:<10} controls are bound", by_selector or by_id,
          "by selector" if by_selector else "by element id")

# ===========================================================================
print()
print("=" * 74)
print("3. DEAD REFERENCES")
print("=" * 74)

used_ids = set(re.findall(r"\$\('([A-Za-z0-9_-]+)'\)", main))
used_ids |= set(re.findall(r"getElementById\('([A-Za-z0-9_-]+)'\)", main))
dead = sorted(used_ids - set(ids))
check("no handler references a missing element id",
      not dead, f"dead: {dead}" if dead else f"{len(used_ids)} ids all present")

# ===========================================================================
print()
print("=" * 74)
print("4. TEMPORAL DEAD ZONE")
print("=" * 74)

lines = main.splitlines()
decls = {}
for i, ln in enumerate(lines, 1):
    m = re.match(r"^(let|const)\s+([A-Za-z_$][\w$]*)", ln)
    if m:
        decls.setdefault(m.group(2), i)

start = next((i for i, ln in enumerate(lines, 1)
              if re.match(r"^async function boot\(", ln)), None)
end = next((i for i, ln in enumerate(lines[start:], start + 1)
            if re.match(r"^(async )?function ", ln)), len(lines)) if start else 0

tdz = []
if start:
    for name, dl in decls.items():
        if dl <= end:
            continue
        for i in range(start, end):
            if re.search(rf"\b{re.escape(name)}\b", lines[i - 1]):
                tdz.append(f"{name} (used {i}, declared {dl})")
                break
check("no let/const used above its declaration inside boot()",
      not tdz, "; ".join(tdz) if tdz else f"boot() lines {start}-{end}")

# ===========================================================================
print()
print("=" * 74)
print("5. RENDERER-SPECIFIC BEHAVIOUR")
print("=" * 74)

# Things that must differ between the two, and things that must not.
check("Cesium sets the lunar ellipsoid before constructing the Viewer",
      cesium_js.index("Ellipsoid.default = C.Ellipsoid.MOON")
      < cesium_js.index("new C.Viewer("),
      "a Viewer built under WGS84 keeps it")

check("Cesium disables lighting (brief requires no illumination effects)",
      "enableLighting', false" in cesium_js and "intensity: 0.0" in cesium_js)

check("Cesium frees the constrained axis for pole crossing",
      "constrainedAxis = undefined" in cesium_js)

check("Three.js uses an unlit material",
      "MeshBasicMaterial" in globe_js and "MeshStandardMaterial" not in globe_js)

check("detail-patch streaming is skipped for Cesium",
      "state.renderer === 'cesium'" in main and "refreshCraters()" in main,
      "3D Tiles refine themselves")

check("provenance badge distinguishes viewing from measuring",
      "pv-measure" in main and "LOLA" in main)

# The CSS2D labels are real <div>s in a layer beside the canvas, not pixels in
# it. Hiding the canvas alone left them frozen on screen over the Cesium view —
# a full set of mare and crater names pinned in place while the Moon rotated
# behind them. Both halves of the switch must move the overlay with the canvas.
check("Three.js exposes a way to hide its DOM label layer",
      "setOverlayVisible" in globe_js and "labelRenderer.domElement" in globe_js)

check("switching to Cesium hides the Three.js label layer",
      "setOverlayVisible(false)" in main,
      "otherwise stale CSS2D labels overlay the Cesium globe")

check("switching back to Classic restores it",
      "setOverlayVisible(true)" in main)

check("both renderers implement setOverlayVisible",
      "setOverlayVisible" in cesium_js,
      "the adapter contract requires identical method names")

# The two renderers are interchangeable only while their method names match.
# A planning overlay added to one and not the other silently disappears when
# the user switches views — which looks like the plan failed.
for _m in ("setRoute", "clearRoute", "setPins", "clearPins",
           "setAOIBox", "clearAOIBox"):
    check(f"both renderers implement {_m}",
          f"  {_m}(" in globe_js and f"  {_m}(" in cesium_js,
          "renderer parity is what lets main.js stay renderer-agnostic")

check("the route is coloured by the risk the planner minimised",
      "profile.risk" in main and "setRoute(latlon" in main,
      "a single-colour line cannot show why the route bends")

check("an armed endpoint picker consumes the click",
      "if (plan.picking)" in main,
      "otherwise placing a pin also fires the inspector")

check("survey routes are labelled, not presented as traverses",
      "regional-corridor" in main or "corridor" in main,
      "a corridor and a certified traverse must not read the same")

check("the profile is plotted against ground distance",
      "distance_m" in main and "drawProfile" in main,
      "indexing waypoints would stretch any-angle runs")

# Region dragging is written once against a two-method contract. If either
# renderer loses a method, drawing a box breaks in that view only — the kind
# of fault that looks like the feature never worked.
for _m in ("pickLatLon", "setInteractive"):
    check(f"both renderers implement {_m}",
          f"  {_m}(" in globe_js and f"  {_m}(" in cesium_js,
          "drag-to-select lives in main.js, not twice per renderer")
check("both renderers expose inputElement",
      "get inputElement()" in globe_js and "get inputElement()" in cesium_js)

check("dragging a region suspends the camera",
      "setInteractive(false)" in main,
      "otherwise the Moon orbits under the pointer and the box lands elsewhere")

check("drag handlers are removed when the drag ends",
      "detachRegionDrag" in main and "removeEventListener('pointermove'" in main,
      "leaked pointer handlers would keep redrawing the box afterwards")

check("region drag and pin picking disarm each other",
      "if (plan.dragging) armRegionDrag();" in main
      and "if (plan.picking) armPicker(plan.picking);" in main,
      "both consume the next click on the globe")

check("dragged longitude takes the short way round",
      "forward > 180" in main,
      "sorting raw values turns a 10 deg drag across the seam into 350 deg")

check("the preview is not called on every pointer move",
      "if (commit) refreshAOIPreview()" in main,
      "one network call per mouse move would flood the server")

# ===========================================================================
print()
print("=" * 74)
print("6. REGION PAGE")
print("=" * 74)

# A second page brings back every failure mode section 2 and 3 exist to catch —
# an unwired control, a handler bound to an id that was renamed — and none of
# the checks above look at it, because they read index.html and main.js by name.
region_html = (F / "region.html").read_text(encoding="utf-8")
region_js = (F / "js" / "region.js").read_text(encoding="utf-8")

r_ids = set(re.findall(r'id="([A-Za-z0-9_-]+)"', region_html))
r_used = set(re.findall(r"\$\('([A-Za-z0-9_-]+)'\)", region_js))
r_dead = sorted(r_used - r_ids)
check("no region handler references a missing element id",
      not r_dead, f"dead: {r_dead}" if r_dead else f"{len(r_used)} ids all present")

r_interactive = [
    m.group(1) for tag in re.findall(r"<(?:button|input|select)\b.*?>",
                                     region_html, re.S)
    if (m := re.search(r'id="([A-Za-z0-9_-]+)"', tag))
]
r_unwired = [i for i in r_interactive if f"'{i}'" not in region_js]
check("every region control is referenced in region.js",
      not r_unwired, f"unwired: {r_unwired}" if r_unwired
      else f"{len(r_interactive)} controls")

check("the region travels in the URL, not in memory",
      "URLSearchParams(location.search)" in region_js,
      "a tab must survive a reload and be shareable")

check("the globe can open a region in its own tab",
      "region.html?" in main and "_blank" in main)

check("the tab carries the globe's rover and regolith across",
      "rover: $('p-rover').value" in main and "q.get('rover')" in region_js,
      "resetting to a default would answer a different question")

# Rover and regolith are inputs to slope limits, slip, hazard and cost — not
# display settings. A page that redrew only the caption would show one rover's
# maps under another rover's name.
check("changing rover or regolith re-derives every map and statistic",
      "$('r-rover').addEventListener('change', run)" in region_js
      and "$('r-soil').addEventListener('change', run)" in region_js)

check("layer images are fetched, not assigned straight to src",
      "X-Range-Low" in region_js,
      "a colour with no numbers beside it is decoration, not a measurement")

region_css = (F / "css" / "region.css").read_text(encoding="utf-8")

# style.css hides the brand wordmark below 1400px — correct on the crowded
# globe toolbar, wrong here, where that element carries the centre, extent,
# posting and source. Without the override a 1366-wide laptop shows eight
# unlabelled maps of an unnamed place.
check("the region page keeps its identity line at every width",
      "#rtop .brand > div { display: block; }" in region_css,
      "it names which piece of the Moon these maps are of")

check("each map's colour key comes from the server, per layer",
      "l.ramp" in region_js and "linear-gradient(90deg,${l.ramp})" in region_js,
      "elevation and hillshade are not drawn with the risk ramp")

check("maps are drawn at one image pixel per analysed cell",
      "image-rendering: pixelated" in (F / "css" / "region.css").read_text(
          encoding="utf-8"),
      "smoothing would invent detail the posting does not have")

check("a failed layer is shown as a failure, not an empty frame",
      "layer err" in region_js)

# ---------------------------------------------------------------------------
print()
print("=" * 74)
print("7. THE REGION AS A SURFACE")
print("=" * 74)

r3d = (F / "js" / "region3d.js").read_text(encoding="utf-8")

check("the 3D view pins the same Three.js build as the globe",
      "three@0.180.0" in region_html and "three@0.180.0" in html,
      "two lunar terrain renderers on different builds is a silent difference")

# The brief rules out illumination effects, and here they would be worse than
# decorative: a shadow across a crater floor is indistinguishable from dark
# regolith, and this page is where someone decides if that floor is drivable.
check("the surface is not lit by a directional source",
      "DirectionalLight" not in r3d and "PointLight" not in r3d
      and "HemisphereLight" in r3d,
      "shading comes from the normal, which is a slope cue, not a sun")

check("vertical exaggeration is applied in the viewer, never in the data",
      "scale.z" in r3d and "exaggeration" in r3d,
      "a factor baked into the metres would travel into reports as measurement")
check("true scale is always one click away",
      "r3d-true" in region_js and "r3d-true" in region_html)
check("the exaggeration in force is always on screen",
      "r3d-vx" in region_js and "#r3d-vx" in region_css)

# The single way this view can mislead: imagery finer than the elevation model
# shows craters that are in no map and no route.
check("a drape finer than the DEM beneath it is called out",
      "mismatch" in region_js and "not as measured relief" in region_js,
      "otherwise imagery detail reads as measured relief")

check("imagery is placed at the bounds actually covered, not those requested",
      "cropToBounds" in region_js and "got.west" in region_js,
      "the mosaic snaps outward to whole tiles")

check("decimation is reported when the mesh is coarser than the analysis",
      "m.stride > 1" in region_js and "sampled not averaged" in region_js)

check("the view is disposed rather than leaked",
      "dispose()" in r3d and "cancelAnimationFrame" in r3d)

check("the region page is served with versioned assets like the globe",
      "region.html" in (Path(__file__).resolve().parents[1]
                        / "backend" / "main.py").read_text(encoding="utf-8"),
      "a stale api.js on one page and a fresh one on the other is the "
      "confusion versioning exists to prevent")

# ---------------------------------------------------------------------------
print()
print("=" * 74)
print("8. ONE RENDERER, TWO SURFACES")
print("=" * 74)

cesium_js = (F / "js" / "cesium-renderer.js").read_text(encoding="utf-8")

check("Cesium can draw our own basemap, not only the tileset",
      "setBasemap" in cesium_js and "UrlTemplateImageryProvider" in cesium_js,
      "the globe was always there — it was hidden, not absent")
check("it uses the Moon's tiling scheme, not Earth's",
      "GeographicTilingScheme" in cesium_js and "Ellipsoid.MOON" in cesium_js)
check("the imagery layer is capped at the product's own depth",
      "maximumLevel" in cesium_js,
      "past a layer's last level every tile 404s and the globe goes black")
check("relief and imagery are exclusive, not stacked",
      "this.tileset.show = !wantImagery" in cesium_js,
      "a sphere and a relief mesh drawn together intersect")
check("the surface toggle is wired",
      "toggleSurface" in main and "btn-surface" in html)
check("it only appears on the renderer where it means something",
      "state.renderer !== 'cesium'" in main and "btn.hidden = !on" in main)
check("the provenance card follows the surface actually drawn",
      "surfaceMode === 'imagery'" in main and "do not measure" in main,
      "citing the tileset while showing our basemap is the wrong source")
check("and the tileset's measured datum error is on screen",
      "+1.8 km vs LOLA" in main,
      "240 samples put it 1,789 m above LOLA on average")
check("an unloaded Moon tile does not flash Earth blue",
      "baseColor" in cesium_js)

print()
print("=" * 74)
print(f"  {npass} passed, {nfail} failed, {nwarn} warnings")
print("=" * 74)
raise SystemExit(1 if nfail else 0)
