# LunarSerpent — Dataset Catalogue

**Document ID:** LS-DOC-003 · **Version:** 1.0 · **Status:** Baseline
**Date:** 2026-08-04
**Covers:** Project brief **Part 8** — which datasets are available, accessible and scientifically valid, with resources and links.

---

## 1. Purpose and provenance policy

This document is the single authoritative register of every dataset LunarSerpent
consumes. It exists so that **any number the system displays can be traced backwards
to a named, published, citable source.**

Four rules govern this catalogue:

1. **No unsourced data.** Every layer rendered in the application resolves to an entry here.
2. **Verified means verified.** Entries marked ✅ were physically confirmed during system
   design on 2026-08-04 — either read from local storage or fetched over the network.
   Entries marked 📚 are documented in peer-reviewed literature but their live endpoint
   has not yet been exercised by this project. The distinction is never blurred.
3. **Resolution is declared, not implied.** Each product carries its true ground sample
   distance. The system never renders a derived quantity finer than the source that produced it.
4. **Synthetic data is labelled synthetic.** Simulated imagery is never presented as observation.

---

## 2. Reference frame standard

All datasets are used in, or transformed into, one common frame:

| Property | Value |
|---|---|
| Body-fixed frame | IAU **Mean Earth / Polar Axis (ME)**, DE421 realisation |
| Reference sphere radius | **1 737 400 m** exactly |
| Longitude convention | **East-positive**, 0°–360° |
| Latitude convention | Planetocentric, −90° … +90° |
| Vertical datum | Radius relative to the 1737.4 km sphere |

This is not an arbitrary choice — it is the **native frame of the LOLA products**, declared
in their PDS3 label as `COORDINATE_SYSTEM_NAME = "MEAN EARTH/POLAR AXIS OF DE421"` with
`A_AXIS_RADIUS = B_AXIS_RADIUS = C_AXIS_RADIUS = 1737.4 <km>`.

Because all three axis radii are **equal**, the Moon is treated as a **sphere, not an
ellipsoid**, and no flattening correction is applied anywhere in the system. The
consequence — that the great-circle distance is the *exact* geodesic rather than an
approximation — is derived in `FORMULAS.md` §2.

> Archinal, B. A. et al. (2018), *Report of the IAU Working Group on Cartographic
> Coordinates and Rotational Elements: 2015*, Celest. Mech. Dyn. Astron. 130:22.
> DOI: [10.1007/s10569-017-9805-5](https://doi.org/10.1007/s10569-017-9805-5)

---

## 3. Storage architecture — why local disk cost is ~zero

The project owner's datasets are held in Google Drive and exposed to the machine through
**Google Drive for Desktop**, mounted as drive `G:`. Files are therefore addressable as
ordinary filesystem paths and are streamed on access by the Drive client — they are **not
copied into the project**.

**Configured data root:**

```
G:\My Drive\LunarNavigator_capstone_project_temp\lunar-navigator\data\raw\
```

This yields a three-tier access strategy:

| Tier | Source | Mechanism | Local disk |
|---|---|---|---|
| **Owner datasets** | Google Drive → `G:` | Drive for Desktop streaming; `numpy.memmap` for rasters | **0 bytes** |
| **Large public rasters** | PDS Geosciences | **HTTP range requests** (verified 206 ✅) | **0 bytes** |
| **Basemap imagery** | NASA Moon Trek WMTS | Per-tile GET, bounded LRU cache | a few MB |

> **Verified ✅ — HTTP range access.** During design, a 1 024-byte window was read out of the
> 506 MB `LDEM_64` product without downloading the file:
> `Content-Range: bytes 265443840-265444863/530841600`, returning elevations
> `[2730.0, 2770.0, 2779.0, 2764.0, 2733.5 …] m` at (0 °N, 180 °E) — physically correct
> values for the farside highlands. **Random access into a half-gigabyte DEM cost 1 KB.**

This is why the project needs neither GDAL nor rasterio, and why no dataset above needs to
be duplicated onto the project drive.

---

## 4. Owner-supplied datasets (mounted at `G:`) ✅

Confirmed present on 2026-08-04. Sizes are as reported by the filesystem.

### 4.1 `lola_dem/` — LOLA topography ✅ **[primary elevation source]**

| File | Size |
|---|---|
| `LDEM_16.IMG` | **31.64 MB** |
| `LDEM_16.LBL` | 4.4 KB |

The PDS3 label was read directly (not assumed) and yields these parameters:

| Field | Value |
|---|---|
| Grid | 5760 × 2880 (`LINE_SAMPLES` × `LINES`) |
| Resolution | 16 pixels/degree |
| Map scale | **1895.21 m/px** at the equator |
| `SAMPLE_TYPE` | `LSB_INTEGER` → little-endian signed |
| `SAMPLE_BITS` | 16 → NumPy `<i2` |
| `SCALING_FACTOR` | 0.5 |
| `OFFSET` | 1 737 400.0 m |
| Header | **none** — byte 0 is pixel (0,0) |
| Stated range | DN −18150 … +21580 → **−9075.0 … +10790.0 m** |

Conversion, quoted verbatim from the label:

```
HEIGHT           = DN × SCALING_FACTOR
PLANETARY_RADIUS = DN × SCALING_FACTOR + OFFSET
```

Because the file is raw, uncompressed and headerless, it is opened with `numpy.memmap`,
giving O(1) random access to any window with no parse step and no full-file read.

**Georeferencing (pixel-registered):**

```
lat(row) = +90 − (row + 0.5) · (180 / H)
lon(col) =       (col + 0.5) · (360 / W)        [east, 0–360]
```

*Verification:* substituting lon = 180° gives col = 2879.5 and lat = 0° gives row = 1439.5,
which reproduce the label's `SAMPLE_PROJECTION_OFFSET` and `LINE_PROJECTION_OFFSET`
exactly for this grid. ✅

**Producer-stated limitation.** The label warns: *"The gridfiles were produced in 45 degree
latitude bands, and there may be edge artifacts at this boundary."* Above 64 ppd, GMT
`surface` interpolation (tension 0.5) fills gaps between ground tracks. Therefore
**apparent fine-scale roughness in interpolated regions is not real topography** and must
not be treated as a hazard signal — handled explicitly in `FORMULAS.md` §3.5.

**Verified finding — the label's `MINIMUM`/`MAXIMUM` bound the *source* grid, not this
file.** ✅ Measured directly during implementation on 2026-08-04:

| | Label declares | Actual array | Difference |
|---|---|---|---|
| `MINIMUM` | −18150 DN (−9075.0 m) | −17963 DN (−8981.5 m) | +187 DN |
| `MAXIMUM` | +21580 DN (+10790.0 m) | +21371 DN (+10685.5 m) | −209 DN |

The file is exactly 33 177 600 bytes — the full declared array, not truncated. The
discrepancy is explained by the label's own `DESCRIPTION`: *"This label describes an IMG
file in the form of a binary **resampling** to pixel registration."* Interpolation
necessarily contracts extremes; it cannot extend them.

**Consequence for verification.** Asserting equality against the label's `MINIMUM`/`MAXIMUM`
is wrong and will always fail. The correct assertion is **containment**: observed values
must lie *within* the declared bounds. Observed values *outside* them would indicate a
genuine fault — wrong NumPy dtype, wrong byte order, or a corrupt file. This is how the
system's raster test is written.

> Smith, D. E. et al. (2010), *The Lunar Orbiter Laser Altimeter Investigation on the LRO
> Mission*, Space Sci. Rev. 150, 209–241.
> DOI: [10.1007/s11214-009-9512-y](https://doi.org/10.1007/s11214-009-9512-y)

---

### 4.2 `robbins_db/` — Robbins (2019) global crater database ✅ **[primary crater layer]**

| File | Size |
|---|---|
| `lunar_crater_database_robbins_2018.csv` | **227.44 MB** |

The most complete global lunar crater database in existence.

| Property | Published (paper) | **Measured in this file** ✅ |
|---|---|---|
| Total craters | 2 033 574 | **1 296 796** |
| Craters D ≥ 1 km | 1 296 879 | 1 296 796 |
| Craters D ≥ 5 km | ≈ 83 000 | **83 061** |
| Craters D ≥ 20 km | 6 972 | **6 973** |
| Minimum diameter | — | **1.000 km** |
| Stated completeness | complete for D ≥ 1 km | — |
| Method | **Manual** identification on LROC WAC, LOLA, Kaguya TC and a merged LOLA+TC DTM | — |

> **Important correction, verified 2026-08-04.** The paper reports 2 033 574 craters, but
> the **PDS release contains only the D ≥ 1 km subset** — 1 296 796 rows, with a measured
> minimum diameter of exactly 1.000 km. The sub-kilometre population was measured but **not
> released**. Any statement that this file contains 2 million craters is wrong.
>
> This is not a defect; it is the boundary of the authoritative record, and it is precisely
> why LunarSerpent's own detector operates **below** 1 km (§5.1 rationale). The system's
> class histogram confirms it independently: the `micro` (< 100 m) and `very_small`
> (100 m – 1 km) classes are both **empty**.
>
> Measured class distribution: `small` 1 285 214 · `medium` 10 020 · `large` 1 501 ·
> `giant` 28 · `basin` 33.

**Why manual matters.** Every crater was human-verified. No automated detector — including
this project's — matches that reliability. LunarSerpent therefore uses Robbins as **ground
truth for D ≥ 1 km**, and applies its own computer vision only *below* the catalogue's
completeness limit, where no authoritative catalogue exists. This is the scientifically
honest division of labour, and it is what makes Part 2's accuracy claim defensible.

**Fields include:** centre lat/lon, diameter from both ellipse and circle fits, ellipticity,
rim arc-fraction traced, and per-crater confidence flags.

Since 227 MB exceeds comfortable in-memory CSV parsing, the acquisition layer performs a
**one-pass streaming parse into a compact NumPy binary index** (~40 MB) that is memory-mapped
thereafter. See `SRD.md` §5.2.

- Landing page: <https://astrogeology.usgs.gov/search/map/moon_crater_database_v1_robbins>

> Robbins, S. J. (2019), *A New Global Database of Lunar Impact Craters >1–2 km*,
> JGR Planets 124(4), 871–892. DOI: [10.1029/2018JE005592](https://doi.org/10.1029/2018JE005592)

---

### 4.3 `artificial_lunar/` — Keio Artificial Lunar Landscape dataset ✅ **[boulder-detection ground truth]**

| Contents | Count |
|---|---|
| `images/render/` — synthetic rendered scenes | **5 500** PNG |
| `images/ground/` — ground-truth segmentation masks | **5 500** PNG |
| `images/clean/` — noise-free masks | **5 500** PNG |
| `real_moon_images/` — **real** lunar images + 2 CSV | 72 PNG |
| `bounding_boxes.csv` | rock bounding boxes |
| `shadow_IDs.txt`, `cam_anomaly_IDs.txt`, `ground_facing_IDs.txt`, `mismatch_IDs.txt`, `top200_largerocks_IDs.txt` | QA exclusion lists |

**16 500 labelled images.** This is the dataset that lets Part 2's boulder detection be
**validated rather than merely asserted** — the single most important scientific asset in
the collection after LOLA and Robbins.

> ⚠️ **Critical caveat — this data is synthetic.** The renders are Blender-generated, not
> observed. Detectors tuned on synthetic imagery suffer a well-documented *domain gap* when
> applied to real sensors. The authors bundled the 72 real Moon images precisely for this
> reason. **LunarSerpent therefore tunes on `render/` but reports its accuracy on
> `real_moon_images/`, and publishes both numbers.** Quoting only the synthetic score would
> misrepresent real-world performance.

The QA `*_IDs.txt` lists identify frames with camera anomalies, ground-facing views and
mask mismatches; these are **excluded** from both tuning and scoring.

> Pessia, R. & Ishigami, G., Space Robotics Group, Keio University —
> *Artificial Lunar Landscape Dataset*.

---

### 4.4 `chandrayaan/` — Chandrayaan-2 OHRC ✅ **[highest-resolution real imagery]**

Six scenes, ISRO product-ID convention `ch2_ohr_ncp_<UTC timestamp>_d_img_d18`:

```
ch2_ohr_ncp_20240406T0052354542_d_img_d18
ch2_ohr_ncp_20240406T0647198948_d_img_d18
ch2_ohr_ncp_20240425T1012478407_d_img_d18
ch2_ohr_ncp_20240425T1209509264_d_img_d18
ch2_ohr_ncp_20240425T1406019344_d_img_d18
ch2_ohr_ncp_20240425T1603031918_d_img_d18
```

Each carries a per-scene `.csv` plus `images/`, and there is a parallel `output_shp/`
tree of **shapefiles**.

**Why this dataset matters.** The Orbiter High Resolution Camera flies at **~0.25 m/px —
the finest lunar imaging resolution ever achieved by any mission.** It is the only data in
this collection capable of resolving individual boulders at the scale that actually
threatens a rover wheel. `ncp` denotes the north circular-polar product line, and 2024
acquisition dates place these in the Chandrayaan-2 extended mission.

These six scenes are the **AOI-scale evidence base** for Part 2's boulder detection and for
Part 6's rover-scale hazard assessment.

> ⚠️ **Verification pending.** The `output_shp/` and per-scene CSV products appear to be
> *derived detections from a previous pipeline*, not raw observations. Per the project
> owner's instruction to build from scratch, **these derived outputs are not consumed as
> input.** Only the underlying imagery is used, and all detections are recomputed. Whether
> full-resolution OHRC rasters are present must be confirmed before the AOI pipeline is built
> (see §8, Open Items).

---

### 4.5 `kaggle_craters/` — YOLO-format crater dataset ✅

```
more-pics-dataset/
  data.yaml
  train/{images,labels}/  +  labels.cache
  valid/{images,labels}/  +  labels.cache
  test/{images,labels}/
```

`data.yaml` + `labels.cache` are the signature of the **Ultralytics YOLO** training format;
labels are normalised `class cx cy w h` text files.

> ⚠️ **Runtime constraint.** Ultralytics YOLO requires PyTorch (~2.5 GB), which cannot be
> installed on the target machine — Windows Application Control blocks newly-downloaded
> compiled DLLs (confirmed: `pandas` and `rasterio` both fail with
> *"An Application Control policy has blocked this file"*). **This dataset is therefore used
> for its labels, as independent validation truth for the classical-CV crater detector, not
> to train or run a neural network.** See `TECHNOLOGY.md` §4 for why this constraint improves
> rather than harms the project's scientific defensibility.

---

### 4.6 Supporting assets ✅

| Path | Size | Role |
|---|---|---|
| `moon_texture/moon_texture.jpg` | 0.23 MB | **Offline fallback basemap** — guarantees the globe renders with no network |
| `moon_model/moon_small.glb` | 13.16 MB | Reference 3D model. *Not used for rendering* — LunarSerpent generates its sphere procedurally so that UV coordinates map to selenographic lat/lon by construction (see `FORMULAS.md` §1.3) |
| `lroc_images/` | 5 × ~0.04 MB | LROC frames, Roboflow-exported (`*.rf.*` naming). Small sample; useful for detector smoke-tests |

---

## 5. Streamed public datasets

### 5.1 NASA Moon Trek WMTS ✅ — the primary basemap

**Verified ✅** — a tile request returned HTTP 200 with valid JPEG during design.

```
https://trek.nasa.gov/tiles/Moon/EQ/{layer}/1.0.0/default/default028mm/{z}/{y}/{x}.{ext}
```

| Layer ID | Content | Native res. |
|---|---|---|
| `LRO_WAC_Mosaic_Global_303ppd_v02` | WAC morphologic mosaic | ~100 m/px |
| `LRO_LOLA_ClrShade_Global_128ppd_v04` | Colour-coded shaded relief | 237 m/px |
| `LRO_LOLA_Shade_Global_128ppd_v04` | Grey hillshade | 237 m/px |

**Why streaming, not bulk download.** The WAC global mosaic as a single file exceeds
**100 GB**. WMTS delivers only the tiles in view, at only the zoom level needed — storage
cost is bounded by what the user looks at, not by the size of the Moon.

**Projection note.** The `EQ` endpoint serves simple-cylindrical tiles, which map directly
onto a sphere's UV parameterisation with no reprojection. This is precisely why the project
can texture a scientifically-correct globe without a GIS stack.

> Robinson, M. S. et al. (2010), *Lunar Reconnaissance Orbiter Camera (LROC) Instrument
> Overview*, Space Sci. Rev. 150, 81–124.
> DOI: [10.1007/s11214-010-9634-2](https://doi.org/10.1007/s11214-010-9634-2)

### 5.2 PDS Geosciences Node ✅ — higher-resolution topography on demand

`https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/`

| Product | Grid | Resolution | Map scale | Size | Access |
|---|---|---|---|---|---|
| `LDEM_4` | 1440 × 720 | 4 ppd | 7580.84 m/px | 2.0 MB | full fetch |
| `LDEM_16` | 5760 × 2880 | 16 ppd | 1895.21 m/px | 31.6 MB | **already local (§4.1)** |
| `LDEM_64` | 23040 × 11520 | 64 ppd | 473.802 m/px | 506 MB | **range request** |
| `LDEM_128` | 46080 × 23040 | 128 ppd | 236.901 m/px | 2.0 GB | **range request** |
| `LDEM_1024_*` | tiled | 1024 ppd | 29.6 m/px | ~900 MB/tile | **range request** |

All parameters above were read from the live PDS `.LBL` files during design ✅.
Because range access works, the finer products are usable **without ever storing them.**

### 5.3 LOLA polar products 📚 — required for Part 1's pole requirement

Simple-cylindrical grids degenerate at the poles: at 85° latitude east–west pixel spacing has
collapsed to 8.7 % of its equatorial value, and at the pole it is **zero**. Polar analysis
therefore uses **polar stereographic** products.

| Product family | Coverage | Use |
|---|---|---|
| `LDEM_85S` / `LDEM_85N` | ±85° → pole | Polar terrain analysis |
| `LDEM_87S` / `LDEM_87N` | ±87° → pole | Artemis candidate sites |
| `LDEM_875S` | ±87.5° → pole | Shackleton-class detail (20 m/px) |

Directory: `.../lola_gdr/polar/img/`

### 5.4 IAU Gazetteer of Planetary Nomenclature ✅ — official feature names

`https://planetarynames.wr.usgs.gov/` — host verified reachable, returns results for
`target=MOON`.

The **only** authoritative source for official feature names: ~9 000 named lunar features
(craters, maria, montes, rimae, valles, rupes, catenae, landing sites), with name, feature
type, centre coordinates, diameter, approval year and etymology.

Robbins gives the system 1.3 million craters; the Gazetteer tells it **which ones have names**
— this is what populates the labelled features required by Part 1.

*Access note:* the public interface returns HTML; the `displayType=csv` parameter yields a
results page rather than clean CSV, so the acquisition layer parses the returned table rather
than assuming a CSV endpoint exists.

### 5.5 PDS Orbital Data Explorer (ODE) ✅

`https://ode.rsl.wustl.edu/` — programmatic footprint search across LRO products. This is how
the AOI pipeline discovers which NAC images cover a requested region **and what their solar
incidence angles are** — a required input to shadow-based boulder height retrieval
(`FORMULAS.md` §5.2).

---

## 6. Reference datasets used as scientific authority (not ingested)

These are not consumed as files but are the **published basis** for formulas and
classification thresholds. Full derivations in `FORMULAS.md`.

| Source | Supplies | Used in |
|---|---|---|
| **Pike (1974, 1977)** | Depth–diameter scaling; simple→complex transition | Part 3 classification |
| **Wang et al. (2021)** | 3D morphometry (depth, rim height, volume) for ~1.3 M craters from SLDEM2015 | Part 3 validation |
| **Head et al. (2010)** | 5 185 craters D ≥ 20 km from LOLA; global size–frequency distribution | Part 3 cross-check |
| **Horn (1981)** | 3×3 slope operator | Part 4, Part 6 |
| **Zevenbergen & Thorne (1987)** | Surface curvature | Part 4 |
| **Barker et al. (2016)** | SLDEM2015 LOLA+Kaguya merged DEM | Resolution benchmarking |
| **Fortezzo et al. (2020)** | Unified Geologic Map of the Moon, 1:5 M | Stratigraphic epoch → defensible crater "age" |
| **Neukum et al. (2001)** | Production & chronology functions | Model-age estimation with uncertainty |

> Wang, Y. et al. (2021), JGR Planets 126, e2020JE006728. DOI: [10.1029/2020JE006728](https://doi.org/10.1029/2020JE006728)
> Head, J. W. et al. (2010), Science 329, 1504–1507. DOI: [10.1126/science.1195050](https://doi.org/10.1126/science.1195050)
> Barker, M. K. et al. (2016), Icarus 273, 346–355. DOI: [10.1016/j.icarus.2015.07.039](https://doi.org/10.1016/j.icarus.2015.07.039)

---

## 7. Dataset → project-part mapping

| Brief part | Datasets consumed |
|---|---|
| **1** — 3D globe | Moon Trek WMTS (WAC, LOLA colour shade); `moon_texture.jpg` fallback; IAU Gazetteer; `LDEM_16` |
| **2** — Crater/boulder detection | Robbins 2019 (global ≥ 1 km); `LDEM_16` (DEM-based detection); `artificial_lunar` (tuning + validation); Chandrayaan-2 OHRC (AOI boulders); `kaggle_craters` labels (independent validation) |
| **3** — Classification | Pike 1974/1977; Wang 2021; Head 2010; Robbins diameters |
| **4** — Per-feature calculation | `LDEM_16` windows; `LDEM_64` via range request for detail |
| **5** — Formula documentation | All of the above, cited at point of use |
| **6** — Path planning | LOLA-derived slope/roughness; crater + boulder layers; LOLA illumination |
| **8** — Technology research | This document + `TECHNOLOGY.md` |

---

## 8. Open items — additional data that may be requested

Per agreement with the project owner, further data will be discussed rather than assumed.
Nothing below currently blocks development.

| # | Item | Why it might be needed | Can it be avoided? |
|---|---|---|---|
| 1 | **Confirm raw OHRC rasters exist** in `chandrayaan/` | The listing exposed derived CSV/shapefiles; full-resolution imagery is required for genuine boulder detection | **Blocking for Part 2 AOI** if absent — would need re-download from ISRO Pradan |
| 2 | LOLA **polar stereographic** DEMs | Part 1 requires poles "properly and clearly visible"; cylindrical grids degenerate there | ✅ Streamable from PDS — no action needed |
| 3 | `LDEM_64` / `LDEM_128` | Finer slope for rover-scale hazard | ✅ Range-request streamable — no action needed |
| 4 | IAU Gazetteer name table | Named-feature labels | ✅ Fetchable (~1 MB) — no action needed |
| 5 | **LROC NAC** scenes for non-OHRC AOIs | Boulder detection outside the six OHRC footprints | ✅ Discoverable via ODE — no action needed |

**Summary:** only item 1 could require the owner to supply more data. Everything else is
reachable from public services at zero storage cost.

---

## 9. Licensing and citation obligations

All NASA, USGS, PDS and ISRO products listed here are **public domain / open access** and
carry no licence fee or redistribution restriction. Scientific practice — and this project's
integrity requirement — nonetheless obliges attribution:

- **Data-producer credit** is displayed in the application's layer panel for every active layer.
- **Peer-reviewed sources** are cited *at the point of use* in `FORMULAS.md`, not merely in a
  bibliography.
- The **Robbins database** and **Wang catalogue** are released under PDS terms requesting
  citation of the associated journal article in any derived publication. Any academic output
  from this capstone must carry those citations.
- The **Artificial Lunar Landscape** dataset requires attribution to the Space Robotics Group,
  Keio University, and — as noted in §4.3 — must be identified as synthetic wherever results
  derived from it are reported.

---

## 10. Revision history

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-08-04 | Baseline. LOLA parameters read from live PDS labels; PDS range access verified (HTTP 206); Moon Trek, Gazetteer, ODE and Astrogeology endpoints verified reachable; owner Drive datasets inventoried and mounted at `G:`. |
