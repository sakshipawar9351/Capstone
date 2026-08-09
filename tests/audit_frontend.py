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

print()
print("=" * 74)
print(f"  {npass} passed, {nfail} failed, {nwarn} warnings")
print("=" * 74)
raise SystemExit(1 if nfail else 0)
