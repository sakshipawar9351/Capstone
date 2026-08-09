# LunarSerpent — Technology Selection and Justification

**Document ID:** LS-DOC-004 · **Version:** 1.0 · **Status:** Baseline
**Date:** 2026-08-04
**Covers:** Project brief **Part 8** — which technologies should be used for each part of the project, and the best-suited technique for each part.

---

## 1. How these decisions were made

Technology was chosen against four criteria, applied in this order:

1. **Does it run on the target machine?** A superior tool that cannot execute is worth nothing.
2. **Is the result scientifically auditable?** A reviewer must be able to trace any output to
   a formula in `FORMULAS.md`. This penalises black boxes.
3. **Is it the standard in its domain?** Standard tools make results comparable with published
   work; bespoke tools make them incommensurable.
4. **Does it minimise moving parts?** Every dependency is a future failure.

Criterion 1 turned out to be unusually decisive here, so it is documented first.

---

## 2. Environment constraints — the facts that forced the stack

These were established by direct measurement on the target machine, not assumed.

### 2.1 Windows Application Control blocks new compiled extensions ⚠️

Newly-downloaded binary Python extensions fail at import:

```
ImportError: DLL load failed while importing conversion:
             An Application Control policy has blocked this file.
```

**Confirmed blocked:** `pandas`, `rasterio` (and by extension GDAL), `pyproj`.
**Confirmed working:** `numpy`, `scipy`, `scikit-image`, `OpenCV`, `scikit-learn`,
`matplotlib`, `networkx`, `Pillow`, `tifffile`, `FastAPI`, `uvicorn`, `pydantic`, `requests`,
`httpx` — the pre-existing scientific stack is intact.

**Consequences:**
- **No GDAL/rasterio** → raster I/O is implemented directly against the PDS3 format.
- **No pyproj** → map projections are implemented explicitly from published formulas.
- **No PyTorch** (≈2.5 GB of compiled extensions; certain to be blocked) → **no deep learning.**

### 2.2 No Node.js, no npm, no git

**Consequence:** no build step is possible for the frontend. React, Vue, Vite, webpack and
TypeScript compilation are all unavailable. The frontend must run directly from source in a
browser.

### 2.3 Storage is constrained; data is on Google Drive

Datasets are mounted read-only at `G:` via Google Drive for Desktop.
**Consequence:** the system reads data in place and copies nothing.

### 2.4 Turning constraints into strengths

Each constraint has a defensible upside for a *scientific* project:

| Constraint | Naive reading | Actual effect |
|---|---|---|
| No GDAL | "Can't do GIS" | Every coordinate transform is explicit, cited and unit-tested — no hidden library behaviour |
| No PyTorch | "Can't do modern CV" | No unexplainable weights; every detection traces to a documented operator |
| No build step | "Primitive frontend" | Zero-install, runs anywhere, no toolchain rot |
| Read-only data | "Inconvenient" | Source data provably unmodified — reproducibility guaranteed |

---

## 3. Technology by project part

### Part 1 — The 3D Moon globe

| Concern | Technology | Why |
|---|---|---|
| 3-D rendering | **Three.js r170+**, ESM via CDN import-map | The mature WebGL library. Import-map delivery needs no bundler — satisfies §2.2 |
| Geometry | **Procedural `SphereGeometry`** | UV maps to lat/lon by construction (`FORMULAS.md` §1.3). The supplied `moon_small.glb` is *not* used for rendering, because an arbitrary mesh carries an arbitrary UV layout with no selenographic guarantee |
| Surface material | **`MeshBasicMaterial` (unlit)** | **The technical answer to "no sunlight effects".** Colour = texture, independent of surface normal and light direction, so all 360° including both poles render equally bright (`FORMULAS.md` §8.1) |
| Camera control | **`OrbitControls`** + custom damping | Standard rotate/zoom/pan; auto-rotate is a per-frame azimuth increment |
| Imagery | **NASA Moon Trek WMTS**, quadtree LOD | Google-Maps-style progressive refinement; keeps detail sharp at any zoom without storing 100 GB |
| Labels | **`CSS2DRenderer`** | Renders feature names as DOM elements — crisp at any zoom and selectable, unlike texture-baked text |
| Click → coordinate | **`Raycaster`** + inverse UV | Exact ray–sphere intersection → $(\varphi,\lambda)$; no pixel approximation |
| Offline fallback | `moon_texture.jpg` | Globe still renders with no network |

**Best-suited technique — the layers panel.** Analysis layers (hazard, risk, slope, cost) are
generated server-side as PNG overlays in the same simple-cylindrical projection as the
basemap, then composited as additional textures with per-layer opacity. Because both share the
projection of `FORMULAS.md` §1.2, **no reprojection or alignment step is needed** — layers
register pixel-exactly by construction.

**Rejected:** CesiumJS (heavyweight, Earth-centric, its Moon support is immature);
Google Maps API (Earth only); deck.gl (needs a bundler); raw WebGL (months of work Three.js
already solves).

---

### Part 2 — Crater and boulder detection

| Concern | Technology | Why |
|---|---|---|
| DEM access | **`numpy.memmap`** on raw PDS3 `.IMG` | PDS3 is headerless raw binary — memmap gives O(1) random access with no parse and no full read. Replaces GDAL entirely |
| Remote DEM access | **HTTP range requests** (`requests`) | Verified: a 1 KB read from a 506 MB product, HTTP 206. Higher-resolution DEMs usable at zero storage |
| Curvature / gradient | **SciPy `ndimage`** convolution | Separable convolutions; the Horn and Zevenbergen–Thorne operators are 3×3 kernels |
| Circle detection | **OpenCV `HoughCircles`** | The optimised reference implementation of the standard method |
| Blob / boulder detection | **scikit-image** `blob_dog`, `blob_log` | Scale-space Difference-of-Gaussian — the principled multi-scale detector for round bright/dark features |
| Shadow segmentation | **OpenCV** adaptive threshold + morphology | Shadows are the darkest connected regions; adaptive thresholding handles albedo variation |
| Classification | **scikit-learn** RandomForest / SVM | Trains on interpretable geometric features, not raw pixels — every decision is inspectable |
| Validation | **Robbins catalogue** + `artificial_lunar` masks + `kaggle_craters` labels | Three independent ground truths |

**Best-suited technique — craters: topographic, not photometric.** Detection runs on the
**DEM**, not on imagery. Rationale: image-based detection confounds craters with albedo
features (fresh ejecta rays, mare/highland boundaries) that have no topographic expression.
A crater has an unambiguous topographic signature — an annulus of negative profile curvature
enclosing positive curvature (`FORMULAS.md` §5.1) — which albedo features do not. Three
quasi-independent tests (curvature signature, Hough circularity, depth-diameter consistency)
must all pass, so false positives are strongly suppressed.

**Best-suited technique — boulders: shadow photoclinometry.** Boulder *height* comes from
shadow length and solar incidence angle, $h = L\tan e$ (`FORMULAS.md` §5.2). This is the only
method that recovers absolute height from a single monoscopic image — stereo needs a pair,
photoclinometry needs a calibrated reflectance model.

> **Note the deliberate tension with Part 1.** The globe must show *no* illumination effects,
> while boulder detection *depends* on shadows. These are different pipelines with opposite
> requirements: display uses photometrically-normalised WAC (illumination removed at source);
> detection uses raw low-sun OHRC/NAC (illumination essential). Conflating them would break
> both.

**On the absence of deep learning.** A YOLO segmentation dataset exists in the supplied data,
but PyTorch cannot be installed (§2.1). This is presented honestly rather than worked around:

| | CNN/YOLO | Classical CV (selected) |
|---|---|---|
| Accuracy on trained domain | Higher | Good |
| Explains *why* it detected something | ✗ | ✓ every step traces to a formula |
| Runs on this machine | ✗ | ✓ |
| Transfers across sensors | Poor (domain gap) | Better (geometry-based) |
| Suits "scientifically proven with formulas" | Weak | **Strong** |

For a project whose stated requirement is that every method be provable and referenced, a
detector built from published operators with citable behaviour is arguably the *better*
choice, not merely the available one. The YOLO labels are still used — as **independent
validation truth**.

---

### Part 3 — Classification

| Concern | Technology | Why |
|---|---|---|
| Size taxonomy | **Pike (1974, 1977)** morphometric boundaries | Class edges track physical transitions (simple→complex at ~15 km), not round numbers |
| Depth measurement | **NumPy** radial profile extraction from DEM | Direct rim-to-floor measurement |
| Statistical validation | **scikit-learn** clustering; **SciPy** regression | Tests whether measured $d/D$ actually separates into the predicted classes |
| Colour encoding | Perceptually-ordered categorical palette | Distinct classes must be distinguishable, including for colour-vision deficiency |

**Best-suited technique.** Classification is **rule-based from published scaling laws**, not
learned from data. A learned classifier would produce boundaries that cannot be justified from
cratering mechanics; Pike's transition diameter can be derived from the gravity-vs-strength
argument in `FORMULAS.md` §4.1. Machine learning is used only to *validate* that the
rule-based classes are statistically separable — the correct division of labour.

---

### Part 4 — Per-feature scientific calculation

| Concern | Technology | Why |
|---|---|---|
| Windowed DEM extraction | **`numpy.memmap`** slicing | Reads only the neighbourhood, not the globe |
| Slope / aspect | **Horn (1981)** via SciPy convolution | GIS-standard; directly comparable with ArcGIS/GDAL output |
| Curvature | **Zevenbergen & Thorne (1987)** | Exact 9-point quadratic; separates rim from floor |
| Profile extraction | **SciPy `map_coordinates`** | Bilinear/spline sampling along an arbitrary transect |
| Statistics | **NumPy** | Vectorised; no pandas needed (and pandas is blocked) |

**Best-suited technique — resolution honesty.** Every returned value carries its **baseline
length** and an uncertainty. Because roughness is scale-dependent (`FORMULAS.md` §3.5),
a slope value without its baseline is scientifically meaningless. The API response schema
makes the baseline a **required** field, so it cannot be omitted by accident.

---

### Part 5 — Formula documentation

| Concern | Technology | Why |
|---|---|---|
| Format | **Markdown + KaTeX** | Renders as typeset mathematics in-browser; stays diffable as plain text |
| Citations | Inline DOI links | Verifiable at point of use, not buried in a bibliography |
| Verification | **`pytest`**-style unit tests | Each formula has a test against a hand-computed or published value — the documentation is *executable* |

---

### Part 6 — Path planning

| Concern | Technology | Why |
|---|---|---|
| Algorithms | **Hand-implemented** A\*, Dijkstra, Theta\*, D\* Lite, RRT\*, PRM, BFS, potential fields | The brief requires per-algorithm metrics (nodes expanded, peak open-set, runtime) to *justify* the selection. A library hides exactly those numbers |
| Priority queue | **`heapq`** (stdlib) | Binary heap, $O(\log n)$ — the standard structure for Dijkstra/A\* |
| Cost surface | **NumPy** arrays | Vectorised construction; the planner indexes it directly |
| Cross-validation | **`networkx`** | Independent shortest-path implementation to confirm our A\* agrees — guards against a subtle bug in our own code |
| Line-of-sight | **Bresenham** | Integer-only; exact cell enumeration for Theta\* and smoothing |
| Benchmarking | **`time.perf_counter`** + explicit counters | Machine-independent metrics (nodes expanded) alongside wall-clock |

**Best-suited technique.** A\* with an admissible *and consistent* heuristic, proved in
`FORMULAS.md` §9.1, plus **cost-validated shortcut smoothing** — shortcuts accepted only when
the integrated cost genuinely decreases. Full reasoning in `ALGORITHMS.md` §4.

---

### Part 7 — Interface

| Concern | Technology | Why |
|---|---|---|
| Structure | **Vanilla HTML5 + ES modules** | Forced by §2.2; also gives zero-install portability |
| Styling | **Modern CSS** — custom properties, grid, `color-mix()` | Theming and layout without a framework |
| State | Small hand-rolled observable store | The app has modest state; a framework would be overhead |
| Charts | **Inline SVG**, generated | Elevation/slope profiles along a path; crisp at any zoom, no chart library |
| Icons | Inline SVG | No icon-font dependency |

**Rejected:** React/Vue/Svelte (all need a build step, §2.2); Bootstrap/Tailwind (Tailwind
needs a build; Bootstrap imposes an ill-fitting visual language on a scientific instrument).

---

### Backend

| Concern | Technology | Why |
|---|---|---|
| Web framework | **FastAPI** | Verified working. Async (matters for tile proxying), auto-generated OpenAPI docs, Pydantic validation |
| Server | **Uvicorn** | ASGI server FastAPI is designed for |
| Validation | **Pydantic v2** | Schemas enforce that e.g. slope always carries its baseline |
| Numerics | **NumPy / SciPy** | The scientific computing standard |
| Caching | **`functools.lru_cache`** + on-disk tile cache | Avoids recomputing identical analysis windows |
| Tests | **`unittest`** (stdlib) | No extra dependency; `pytest` optional |

**Rejected:** Flask (no async, no built-in validation); Django (ORM/admin/templating all
unnecessary here); Node/Express (§2.2).

---

## 4. Complete technology stack summary

```
┌──────────────────────── PRESENTATION ────────────────────────┐
│  Three.js r170  ·  CSS2DRenderer  ·  OrbitControls           │
│  Vanilla ES modules  ·  Modern CSS  ·  Inline SVG            │
│  (no build step — CDN import-map)                            │
└───────────────────────────┬──────────────────────────────────┘
                            │ REST / JSON  +  PNG layer tiles
┌───────────────────────────┴──────────────────────────────────┐
│                        APPLICATION                           │
│  FastAPI  ·  Uvicorn  ·  Pydantic v2                         │
└───────────────────────────┬──────────────────────────────────┘
┌───────────────────────────┴──────────────────────────────────┐
│                          ANALYSIS                            │
│  Terrain    : NumPy · SciPy ndimage (Horn, Zevenbergen)      │
│  Detection  : OpenCV · scikit-image (Hough, DoG, morphology) │
│  Classify   : scikit-learn · SciPy stats (Pike laws)         │
│  Planning   : heapq · NumPy · networkx (cross-check)         │
└───────────────────────────┬──────────────────────────────────┘
┌───────────────────────────┴──────────────────────────────────┐
│                            DATA                              │
│  numpy.memmap → PDS3 .IMG   (local, G: Drive mount)          │
│  HTTP range   → PDS remote  (LDEM_64/128, zero storage)      │
│  WMTS tiles   → Moon Trek   (bounded LRU cache)              │
│  csv (stdlib) → Robbins catalogue → compact NumPy index      │
└──────────────────────────────────────────────────────────────┘
```

**Total runtime dependencies: 9** — `numpy`, `scipy`, `scikit-image`, `opencv-python`,
`scikit-learn`, `networkx`, `Pillow`, `fastapi`, `uvicorn` (+ `requests` for acquisition).
All verified working on the target machine.

---

## 5. Technique summary — the single best method per task

| Task | Best-suited technique | Rationale |
|---|---|---|
| Globe illumination | **Unlit material** | Only way to guarantee uniform 360° legibility |
| Basemap delivery | **WMTS quadtree streaming** | Google-Maps sharpness without 100 GB |
| Coordinate mapping | **Explicit pixel-registered transform** | Verified against PDS labels at two resolutions |
| DEM access | **memmap + HTTP range** | O(1) random access, zero storage |
| Slope | **Horn 3×3** | Most accurate on noisy real DEMs; GIS-standard |
| Cell size | **Latitude-corrected $\Delta x=\frac{2\pi R\cos\varphi}{W}$** | Prevents severe polar slope underestimation |
| Crater detection | **Curvature + Hough + physical consistency** | Three independent tests; immune to albedo confusion |
| Boulder height | **Shadow photoclinometry** | Only monoscopic absolute-height method |
| Sub-resolution boulders | **Size–frequency extrapolation** | Quantifies what cannot be seen |
| Classification | **Pike scaling laws** | Boundaries follow physics, not round numbers |
| Crater age | **Degradation index + epoch + model age** | Three separately-labelled quantities, no false precision |
| Hazard combination | **max(), not weighted sum** | Safety is non-compensatory |
| Path planning | **A\* + cost-validated smoothing** | Provably optimal, deterministic, correct on weighted cost |
| Replanning | **D\* Lite** | Repair cost local to the change |

---

## 6. Risks arising from these choices

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | Moon Trek WMTS unavailable | Low | High | `moon_texture.jpg` offline fallback; tile cache |
| 2 | Classical CV underperforms CNN on small craters | **Medium** | Medium | Quantify honestly against Robbins; report precision/recall, never claim parity |
| 3 | OHRC raw rasters absent from supplied data | **Medium** | **High** | Confirm early; fall back to LROC NAC via ODE |
| 4 | Application Control blocks a future dependency | Medium | Medium | Prefer pure-Python; verify import before adopting |
| 5 | 227 MB Robbins CSV too slow to parse repeatedly | High | Low | One-pass conversion to a memory-mapped NumPy index |
| 6 | Browser memory at high zoom | Medium | Medium | Bounded LOD tile cache with LRU eviction |
| 7 | Drive mount unavailable (offline/unsynced) | Medium | High | Detect at startup; clear error; PDS streaming fallback |

---

## 7. Revision history

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-08-04 | Baseline. All selections verified against measured environment constraints; blocked and working packages confirmed by direct import test. |
