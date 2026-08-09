# LunarSerpent — Mathematical Formulation, Proofs and Sources

**Document ID:** LS-DOC-005 · **Version:** 1.0 · **Status:** Baseline
**Date:** 2026-08-04
**Covers:** Project brief **Part 5** — every formula used, its proof/justification, its source, and *why* it was chosen.

---

## 0. How to read this document

Every formula below is presented in a fixed four-part structure, so that nothing is asserted
without support:

| Section | Meaning |
|---|---|
| **Statement** | The formula exactly as implemented in code |
| **Derivation / Proof** | Why it is mathematically true, or where it is empirically fitted |
| **Why this one** | What alternatives exist and why this was chosen over them |
| **Source** | Peer-reviewed citation with DOI |

**Notation used throughout:**

| Symbol | Meaning | Units |
|---|---|---|
| $R$ | Lunar reference radius = 1 737 400 | m |
| $\varphi$ | Planetocentric latitude | rad (deg where stated) |
| $\lambda$ | East longitude | rad (deg where stated) |
| $z$ | Elevation above the reference sphere | m |
| $g$ | Lunar surface gravity = 1.625 | m s⁻² |
| $\theta$ | Terrain slope angle | deg |
| $D$ | Crater rim-crest diameter | km |
| $d$ | Crater rim-to-floor depth | km |
| $W, H$ | DEM grid width, height | pixels |

**Units discipline.** Crater morphometry formulas (§4) are stated in **kilometres**, because
that is the unit in which they were originally fitted. Every other formula uses **metres**.
Implementation converts explicitly at the boundary; silent unit mixing is the most common
source of error in this class of software.

---

## 1. Coordinate systems and georeferencing

### 1.1 Reference frame

**Statement.** All positions are expressed in the IAU **Mean Earth / Polar Axis (ME)**
body-fixed frame, DE421 realisation, on a **sphere** of radius $R = 1\,737\,400$ m, with
latitude planetocentric and longitude **east-positive** in $[0°, 360°)$.

**Derivation / Proof.** This is not a modelling choice but an inherited constraint. The LOLA
PDS3 label declares:

```
A_AXIS_RADIUS = B_AXIS_RADIUS = C_AXIS_RADIUS = 1737.4 <km>
COORDINATE_SYSTEM_NAME = "MEAN EARTH/POLAR AXIS OF DE421"
POSITIVE_LONGITUDE_DIRECTION = "EAST"
```

Since all three axis radii are **equal**, the reference figure is a sphere, and flattening
$f = (a-c)/a = 0$ **exactly**.

**Why this one.** Using any other frame would require reprojecting the source data, which
introduces resampling error for no scientific gain. Working natively in the data's own frame
means the only transformation in the system is the exactly-invertible grid mapping of §1.2.

The Moon's true dynamic flattening is $\sim1.2\times10^{-3}$, so an ellipsoidal treatment
would change surface positions by $\lesssim 2$ km at mid-latitudes. **This does not matter
here**, because all data used is *already gridded on the spherical datum* — adopting an
ellipsoid would introduce an inconsistency, not remove one.

**Source.** Archinal, B. A. et al. (2018), *Report of the IAU Working Group on Cartographic
Coordinates and Rotational Elements: 2015*, Celest. Mech. Dyn. Astron. **130**:22.
DOI: [10.1007/s10569-017-9805-5](https://doi.org/10.1007/s10569-017-9805-5)

---

### 1.2 Grid ↔ coordinate mapping (pixel-registered simple cylindrical)

**Statement.** For a DEM of $W$ columns and $H$ rows covering the full sphere:

$$\varphi(\text{row}) = 90° - (\text{row} + 0.5)\cdot\frac{180°}{H}$$

$$\lambda(\text{col}) = (\text{col} + 0.5)\cdot\frac{360°}{W}$$

with inverses

$$\text{row} = (90° - \varphi)\cdot\frac{H}{180°} - 0.5, \qquad
\text{col} = \lambda\cdot\frac{W}{360°} - 0.5$$

**Derivation / Proof.** The $+0.5$ terms encode **pixel registration** — a pixel's coordinate
refers to its *centre*, not its corner. The mapping is verified against the PDS label rather
than assumed. For `LDEM_16` ($W=5760$, $H=2880$):

- Substituting $\lambda = 180°$ gives $\text{col} = 180\cdot16 - 0.5 = 2879.5$, which equals
  the label's `SAMPLE_PROJECTION_OFFSET` for this grid. ✅
- Substituting $\varphi = 0°$ gives $\text{row} = 90\cdot16 - 0.5 = 1439.5$, equal to
  `LINE_PROJECTION_OFFSET`. ✅

For `LDEM_4` ($W=1440$, $H=720$) the same formulas give 719.5 and 359.5, again matching the
label exactly. ✅ The mapping therefore reproduces the producer's own georeferencing at two
independent resolutions.

**Why this one.** This satisfies the project requirement that *no pixel-based data* be used
for positioning: pixel indices exist **only** as the output of this transform, never as an
independent source of truth. Every feature position enters and leaves the system as
$(\varphi, \lambda)$.

**Source.** PDS3 label parameters, LOLA GDR `LDEM_4.LBL` / `LDEM_16.LBL` / `LDEM_64.LBL`,
read directly from PDS Geosciences Node, 2026-08-04.

---

### 1.3 Sphere UV parameterisation for the 3D globe

**Statement.** A point on the rendered globe at parametric coordinates $(u,v) \in [0,1]^2$
corresponds to

$$\lambda = 360°\,u, \qquad \varphi = 90° - 180°\,v$$

**Derivation / Proof.** Compare with §1.2: the equirectangular texture's $(u,v)$ is exactly
$(\text{col}/W, \text{row}/H)$. Therefore a simple-cylindrical basemap tile maps onto a UV
sphere **with no reprojection whatsoever** — the texture coordinate *is* the geographic
coordinate, up to linear scaling.

**Why this one.** This is the reason the project can render a scientifically-correct globe
with no GIS library. It also means the inverse operation — a mouse click → $(\varphi,\lambda)$
— is exact rather than approximate, which Part 1's coordinate-picking requirement demands.

It is also why the project **generates its sphere procedurally** rather than loading the
supplied `moon_small.glb`: an arbitrary mesh carries whatever UV layout its author chose,
which is not guaranteed to be selenographically meaningful.

---

### 1.4 Geographic → Cartesian

**Statement.**

$$\mathbf{r}(\varphi,\lambda,z) = (R+z)\begin{pmatrix}\cos\varphi\cos\lambda\\ \cos\varphi\sin\lambda\\ \sin\varphi\end{pmatrix}$$

**Derivation / Proof.** Standard spherical-to-Cartesian conversion; exact for a sphere.
Elevation enters as a radial offset because the vertical datum is the sphere itself (§1.1).

**Why this one.** Required for (a) placing feature markers in the 3D scene, (b) ray–sphere
intersection for click-to-coordinate, and (c) the chord-vs-arc check in §2.2.

---

## 2. Distances and geodesy

### 2.1 Great-circle distance (haversine)

**Statement.** For two points $(\varphi_1,\lambda_1)$, $(\varphi_2,\lambda_2)$:

$$a = \sin^2\!\left(\frac{\Delta\varphi}{2}\right) + \cos\varphi_1\cos\varphi_2\sin^2\!\left(\frac{\Delta\lambda}{2}\right)$$

$$c = 2\,\operatorname{atan2}\!\left(\sqrt{a},\ \sqrt{1-a}\right), \qquad s = R\,c$$

**Derivation / Proof.** *This formula is exact, not approximate.* On a sphere the geodesic
between two points is the minor arc of the great circle through them, and its length is
$R\Delta\sigma$ where $\Delta\sigma$ is the central angle. The haversine expression is an
algebraically equivalent rewriting of the spherical law of cosines
$\cos\Delta\sigma = \sin\varphi_1\sin\varphi_2 + \cos\varphi_1\cos\varphi_2\cos\Delta\lambda$,
chosen because it is **numerically stable for small separations**, where the law of cosines
loses precision catastrophically to floating-point cancellation ($\cos\Delta\sigma \to 1$).

Since the LunarSerpent datum is a sphere **exactly** (§1.1), no ellipsoidal correction exists
to be neglected. The result is the true geodesic distance.

**Why this one.** Vincenty's or Karney's ellipsoidal geodesics would be the correct choice on
Earth, but here they would model a flattening that the reference figure does not have. Using
them would be *less* accurate, not more — and vastly slower inside the path-planner's inner
loop, where this function is evaluated millions of times.

The `atan2` form is used rather than $c = 2\arcsin\sqrt{a}$ because the latter is
ill-conditioned for near-antipodal points ($a \to 1$).

**Source.** Sinnott, R. W. (1984), *Virtues of the Haversine*, Sky and Telescope **68**(2), 158.
Stability analysis: Karney, C. F. F. (2013), *Algorithms for geodesics*, J. Geodesy **87**, 43–55.
DOI: [10.1007/s00190-012-0578-z](https://doi.org/10.1007/s00190-012-0578-z)

---

### 2.2 Surface distance including topography

**Statement.** The traversed length of a path segment accounts for the vertical rise:

$$s_{3D} = \sqrt{s_{\text{gc}}^2 + (\Delta z)^2}$$

**Derivation / Proof.** For a segment short enough that slope is approximately constant, the
horizontal displacement $s_{\text{gc}}$ and vertical displacement $\Delta z$ form a right
triangle whose hypotenuse is the distance actually driven. Equivalently
$s_{3D} = s_{\text{gc}}/\cos\theta$.

**Why this one.** A rover drives *over* terrain, not through the chord. Ignoring this
systematically **under-estimates traverse distance, time and energy** — the error is
$1/\cos\theta - 1$, which is 3.5 % at 15° and 10 % at 25°. For mission planning that is not
negligible.

**Applicability limit.** Valid where the segment length is small relative to the radius of
curvature of the terrain. In LunarSerpent, segments are one DEM cell (≤ 1.9 km) whereas
$R = 1737$ km, so the flat-triangle approximation contributes error $O(s/R)^2 < 10^{-6}$.

---

### 2.3 Initial bearing

**Statement.**

$$\alpha = \operatorname{atan2}\!\big(\sin\Delta\lambda\cos\varphi_2,\ \cos\varphi_1\sin\varphi_2 - \sin\varphi_1\cos\varphi_2\cos\Delta\lambda\big)$$

**Derivation / Proof.** Standard result from the spherical triangle formed by the two points
and the north pole, obtained by applying the four-parts formula of spherical trigonometry.

**Why this one.** Required for rover heading commands and for the aspect-vs-heading
comparison in §6.3 (whether the rover is climbing, descending or side-slopes a gradient).
Note that on a sphere the bearing **changes continuously along a great circle**, so this is
the *initial* bearing and must be recomputed per segment.

---

### 2.4 Metric scale of a grid cell — the latitude problem

**Statement.** In a simple-cylindrical grid, the ground spacing of one cell is

$$\Delta y = \frac{\pi R}{H} \quad (\text{constant}), \qquad
\boxed{\Delta x(\varphi) = \frac{2\pi R}{W}\cos\varphi} \quad (\text{latitude-dependent})$$

**Derivation / Proof.** A row of the grid spans 180° of latitude over $H$ pixels, and the
meridional arc length per degree is constant on a sphere, giving $\Delta y = \pi R / H$. A
column spans 360° of longitude over $W$ pixels, but the **radius of the parallel of latitude**
$\varphi$ is $R\cos\varphi$, not $R$. Hence the east–west ground spacing contracts as
$\cos\varphi$.

*Consistency check at the equator.* For LOLA grids $W = 2H$, so
$\Delta x(0) = 2\pi R/(2H) = \pi R/H = \Delta y$ — the cells are square at the equator, as
expected. For `LDEM_16`: $\pi \cdot 1737400 / 2880 = 1895.2$ m, matching the label's
`MAP_SCALE = 1895.21 <m/pix>`. ✅

**Why this one — and why it is the most important formula in this section.** Slope is
$\arctan$ of a *ratio of metres to metres*. If $\Delta x$ is treated as constant, then at
60° latitude the east–west distance is over-estimated by a factor of 2, and the computed
east–west slope is **under-estimated by the same factor**. At 80° the error is a factor of
5.8. This is the single most common defect in naive planetary terrain analysis, and it
produces hazard maps that are dangerously optimistic exactly where Artemis wants to land —
the poles.

LunarSerpent therefore computes $\Delta x$ per-row and propagates it into §3.2.

**Degeneracy.** As $\varphi \to \pm 90°$, $\Delta x \to 0$ and the slope expression becomes
singular. This is a genuine defect of the *projection*, not of the terrain. Above
$|\varphi| = 85°$ the system switches to polar stereographic products
(`DATASETS.md` §5.3) rather than reporting numbers it cannot justify.

---

## 3. Terrain analysis

### 3.1 Elevation from digital number

**Statement.**

$$z = \mathrm{DN} \times 0.5\ \text{m}, \qquad r_{\text{planetary}} = z + 1\,737\,400\ \text{m}$$

**Derivation / Proof.** Quoted verbatim from the PDS label:

```
HEIGHT           = DN * SCALING_FACTOR      (SCALING_FACTOR = 0.5)
PLANETARY_RADIUS = DN * SCALING_FACTOR + OFFSET  (OFFSET = 1737400.0)
```

**Why this one.** It is the producer's own definition; there is no alternative. The
consequence worth stating is that the **vertical quantisation of the data is 0.5 m** — the
system must never report elevation differences to a finer precision than this, and derived
slopes carry a corresponding noise floor (§3.5).

**Source.** LOLA GDR PDS3 labels, PDS Geosciences Node.

---

### 3.2 Slope — Horn's operator

**Statement.** For the 3×3 elevation neighbourhood

$$\begin{matrix} z_1 & z_2 & z_3\\ z_4 & z_5 & z_6\\ z_7 & z_8 & z_9\end{matrix}$$

(row-major, $z_5$ the centre, $z_1$ at north-west):

$$\frac{\partial z}{\partial x} = \frac{(z_3 + 2z_6 + z_9) - (z_1 + 2z_4 + z_7)}{8\,\Delta x(\varphi)}$$

$$\frac{\partial z}{\partial y} = \frac{(z_7 + 2z_8 + z_9) - (z_1 + 2z_2 + z_3)}{8\,\Delta y}$$

$$\theta = \arctan\sqrt{\left(\frac{\partial z}{\partial x}\right)^2 + \left(\frac{\partial z}{\partial y}\right)^2}$$

**Derivation / Proof.** Horn's estimator is a **third-order finite difference** weighted so
that the four edge-adjacent neighbours receive weight 2 and the four diagonal neighbours
weight 1, normalised by 8. The weighting is the discrete approximation to a distance-weighted
plane fit: diagonal neighbours are $\sqrt2$ further away and are therefore down-weighted by
approximately that factor.

The magnitude $\|\nabla z\|$ is the **maximum** directional derivative of the fitted surface
(steepest descent), because for a plane $z = ax+by+c$ the directional derivative in unit
direction $\mathbf{u}$ is $\nabla z \cdot \mathbf{u}$, maximised at $\|\nabla z\|$ when
$\mathbf{u} \parallel \nabla z$. Slope is therefore correctly the *steepest* gradient at the
point, which is the quantity relevant to vehicle stability.

Note the appearance of $\Delta x(\varphi)$ from §2.4 — **this is where the latitude
correction must enter.**

**Why this one.** Four estimators were considered:

| Method | Behaviour | Verdict |
|---|---|---|
| 2-point central difference | Uses only 4 neighbours; highly noise-sensitive | Rejected — LOLA has 0.5 m quantisation noise |
| **Horn (1981)** | 8 neighbours, distance-weighted | **Selected** |
| Zevenbergen & Thorne (1987) | Exact quadratic through 9 points | Used for *curvature* (§3.4), not slope |
| Maximum-neighbour difference | Overestimates on noisy data | Rejected |

Horn's operator was selected because independent evaluations on real (noisy) DEMs find it the
most accurate of the 3×3 family, and because it is the operator implemented in ArcGIS,
GDAL (`gdaldem slope`) and GRASS — making LunarSerpent's outputs **directly comparable with
standard GIS results** rather than idiosyncratic.

Zevenbergen & Thorne fits an exact quadratic through all nine points, which is superior on
*smooth analytic* surfaces but amplifies noise on measured ones, because exact interpolation
reproduces the noise rather than smoothing it.

**Source.** Horn, B. K. P. (1981), *Hill Shading and the Reflectance Map*, Proc. IEEE
**69**(1), 14–47. DOI: [10.1109/PROC.1981.11918](https://doi.org/10.1109/PROC.1981.11918)
Comparative evaluation: Jones, K. H. (1998), *A comparison of algorithms used to compute hill
slope as a property of the DEM*, Computers & Geosciences **24**(4), 315–323.
DOI: [10.1016/S0098-3004(98)00032-6](https://doi.org/10.1016/S0098-3004(98)00032-6)

---

### 3.3 Aspect

**Statement.**

$$\psi = \operatorname{atan2}\!\left(\frac{\partial z}{\partial y},\ -\frac{\partial z}{\partial x}\right),
\qquad \psi_{\text{compass}} = (90° - \psi) \bmod 360°$$

**Derivation / Proof.** Aspect is the compass direction of steepest **descent**, i.e. the
azimuth of $-\nabla z$. The sign convention and the $90° - \psi$ rotation convert from
mathematical convention (counter-clockwise from +x/east) to compass convention (clockwise
from north).

**Why this one.** Needed for three purposes: (a) determining whether a traverse segment
climbs, descends or cross-slopes, which changes the rover mobility model (§7.2);
(b) illumination modelling for solar power at polar sites; (c) hillshade rendering (§3.6).

**Undefined case.** Where $\|\nabla z\| = 0$ the aspect is undefined; the implementation
returns a flag, not an arbitrary value such as 0° (which would falsely imply "north-facing").

---

### 3.4 Curvature — Zevenbergen & Thorne

**Statement.** Fit the quadratic surface

$$z = Ax^2y^2 + Bx^2y + Cxy^2 + Dx^2 + Ey^2 + Fxy + Gx + Hy + I$$

exactly through the 3×3 neighbourhood. Then

$$\kappa_{\text{profile}} = \frac{-2(DG^2 + EH^2 + FGH)}{(G^2+H^2)\,(1+G^2+H^2)^{3/2}}$$

$$\kappa_{\text{plan}} = \frac{2(DH^2 + EG^2 - FGH)}{(G^2+H^2)^{3/2}}$$

**Derivation / Proof.** With nine sample points and nine coefficients the fit is exact
(interpolating, not least-squares). $G$ and $H$ are the first partial derivatives at the
centre and $D, E, F$ the second partials. *Profile* curvature is the curvature of the surface
**in the direction of steepest slope**; *plan* curvature is the curvature **perpendicular**
to it — obtained by projecting the Hessian onto the gradient direction and its normal
respectively.

**Why this one — physical meaning.**

- $\kappa_{\text{profile}} < 0$ → surface is **convex** along the slope: a **crater rim** or
  ridge crest. Convex-upward breaks are where a rover risks high-centering or tipping.
- $\kappa_{\text{profile}} > 0$ → **concave**: a crater floor or valley, where regolith
  and volatiles accumulate.
- $\kappa_{\text{plan}}$ distinguishes converging from diverging flow — used to separate
  genuine circular crater rims from linear ridges in the detector of §5.1.

Curvature is the **primary discriminator for DEM-based crater detection**, because a crater
has a characteristic signature: an annulus of strongly negative profile curvature (the rim)
enclosing a region of positive curvature (the floor). This is far more robust than intensity
methods, which confound craters with albedo features.

**Source.** Zevenbergen, L. W. & Thorne, C. R. (1987), *Quantitative analysis of land surface
topography*, Earth Surface Processes and Landforms **12**(1), 47–56.
DOI: [10.1002/esp.3290120107](https://doi.org/10.1002/esp.3290120107)

---

### 3.5 Roughness, and the noise floor

**Statement.** Three complementary measures over a window $N$ of $n$ cells:

**Terrain Ruggedness Index** (Riley et al. 1999):
$$\mathrm{TRI} = \sqrt{\frac{1}{n}\sum_{i\in N}(z_i - z_c)^2}$$

**RMS slope** at baseline $L$ (Shepard et al. 2001):
$$s(L) = \sqrt{\left\langle \left(\frac{z(x+L)-z(x)}{L}\right)^2\right\rangle}$$

**Relief:** $\Delta z_{\max} = \max_N z - \min_N z$

**Derivation / Proof.** TRI is the root-mean-square deviation of neighbours from the centre
cell — a direct measure of local vertical scatter. RMS slope is the second moment of the
elevation-difference distribution at lag $L$, which for a self-affine surface obeys a power
law $s(L) \propto L^{H-1}$ with $H$ the Hurst exponent.

**Why this one — and the scale-dependence warning.** Shepard et al. showed that natural
planetary surfaces are **self-affine**: roughness is not a single number but a *function of
baseline*. A surface that is smooth at 2 km baseline can be lethal at 2 m baseline. It is
therefore **scientifically meaningless to quote a slope or roughness without stating the
baseline over which it was measured.**

LunarSerpent enforces this: every slope and roughness value carries its baseline length in
the API response and in the UI. At `LDEM_16` the baseline is **1895 m**; a rover wheel
responds to something nearer 1 m. The system therefore explicitly distinguishes:

- **Corridor-scale slope** (from LOLA) — valid for route selection over tens of kilometres
- **Rover-scale slope** (from OHRC/NAC-derived products) — required for final traverse safety

Conflating the two would be the most serious scientific error this project could make, and
Part 6's hazard model is structured to prevent it.

**Noise floor.** With 0.5 m vertical quantisation (§3.1) and $\Delta x \approx 1895$ m, a
one-DN difference between adjacent cells corresponds to a slope of
$\arctan(0.5/1895) = 0.015°$. Slopes below roughly 0.05° are therefore **not resolvable** and
are reported as "below noise floor" rather than as small numbers implying false precision.

**Sources.**
Riley, S. J., DeGloria, S. D. & Elliot, R. (1999), *A terrain ruggedness index that quantifies
topographic heterogeneity*, Intermountain Journal of Sciences **5**, 23–27.
Shepard, M. K. et al. (2001), *The roughness of natural terrain: A planetary and remote
sensing perspective*, JGR Planets **106**(E12), 32777–32795.
DOI: [10.1029/2000JE001429](https://doi.org/10.1029/2000JE001429)

---

### 3.6 Hillshade (visualisation only)

**Statement.**

$$I = 255\big[\cos\theta_z\cos\theta + \sin\theta_z\sin\theta\cos(\phi_a - \psi)\big]$$

with $\theta_z$ the solar zenith angle and $\phi_a$ the solar azimuth.

**Derivation / Proof.** This is the Lambertian cosine law $I \propto \mathbf{n}\cdot\mathbf{l}$
expanded in terms of slope and aspect, where $\mathbf{n}$ is the surface normal and
$\mathbf{l}$ the illumination direction.

**Why this one — and where it must NOT be used.** Hillshade is used **only** for optional
relief rendering in the analysis panels.

> ⚠️ **It is never applied to the 3D globe.** Part 1 requires the globe to be free of
> illumination effects so that all 360°, including both poles, is uniformly legible. This is
> implemented by using an **unlit material** (§8.1) — the technical opposite of a hillshade.
> The two coexist deliberately: the globe shows *albedo and morphology*, while a hillshade
> panel can show *shape*, and the user chooses.

**Source.** Horn (1981), *op. cit.* — the same paper that gives the slope operator.

---

## 4. Crater morphometry and classification

### 4.1 Depth–diameter scaling

**Statement.** For lunar craters, with $d$ and $D$ in **kilometres**:

$$\text{Simple } (D < 15\ \text{km}): \quad d = 0.196\,D^{1.010}$$
$$\text{Complex } (D > 15\ \text{km}): \quad d = 1.044\,D^{0.301}$$

**Derivation / Proof.** These are **empirical power-law fits**, not analytic results. Pike
measured rim-crest-to-floor depth for several hundred lunar craters from Lunar Orbiter and
Apollo photogrammetry and regressed $\log d$ on $\log D$. The near-unity exponent for simple
craters ($1.010$) means simple craters are approximately **geometrically similar** — depth
scales linearly with diameter, so $d/D \approx 0.196 \approx 1/5$ is roughly constant.

The complex-crater exponent ($0.301$) is dramatically shallower: doubling $D$ increases depth
by only $2^{0.301} = 1.23\times$. Large craters are **proportionally much shallower**.

**Physical interpretation — why the exponent changes.** The break occurs because gravity
overwhelms the strength of the target rock. For a transient cavity of depth $d_t$, the
lithostatic stress at the floor is $\rho g d_t$. When this exceeds the material's shear
strength, the cavity **collapses**: the floor rebounds upward, the walls slump inward forming
terraces, and a central peak forms by elastic rebound. The result is a wider, shallower final
crater. This is the *simple-to-complex transition*, and it is why the transition diameter
$D_t$ scales approximately as $g^{-1}$ across bodies — $\sim$15–20 km on the Moon
($g = 1.62$), but only $\sim$3 km on Earth ($g = 9.81$).

**Why this one.** Pike's relations remain the standard reference fit, reproduced by every
subsequent survey including modern LOLA-based work. LunarSerpent uses them in three ways:

1. **Prediction** — estimate depth where DEM resolution cannot resolve it directly.
2. **Validation** — compare measured LOLA depth against predicted; large deviation is
   physically meaningful, indicating a **degraded/infilled** crater (measured ≪ predicted)
   or an anomalously fresh one.
3. **Classification** — the transition diameter is the *physically justified* boundary
   between morphological classes (§4.3), rather than an arbitrary bin edge.

**Stated uncertainty.** Pike's fits have scatter of roughly ±30 % in $d$ at fixed $D$, arising
from genuine variation in target properties, impact angle and degradation state.
**LunarSerpent reports predicted depth with this uncertainty band, never as a point value.**

**Sources.**
Pike, R. J. (1974), *Depth/diameter relations of fresh lunar craters: Revision from spacecraft
data*, Geophys. Res. Lett. **1**(7), 291–294.
DOI: [10.1029/GL001i007p00291](https://doi.org/10.1029/GL001i007p00291)
Pike, R. J. (1977), *Size-dependence in the shape of fresh impact craters on the Moon*, in
*Impact and Explosion Cratering*, Pergamon, 489–509.
Modern confirmation: Wang, Y. et al. (2021), JGR Planets **126**, e2020JE006728.
DOI: [10.1029/2020JE006728](https://doi.org/10.1029/2020JE006728)

---

### 4.2 Rim height and excavation depth

**Statement.**

$$h_{\text{rim}} = 0.036\,D^{1.014}\ \text{km}, \qquad d_{\text{exc}} \approx 0.1\,D$$

**Derivation / Proof.** The rim-height relation is Pike's companion empirical fit. The
excavation-depth rule follows from the *proportional growth* model of transient cavity
formation: material is excavated from roughly the upper one-third of the transient cavity,
and with $d_t/D_t \approx 1/3$ this yields $d_{\text{exc}} \approx D/10$.

**Why this one.** Excavation depth determines **what stratigraphic layer a crater has exposed**
— it is the basis for using craters as natural boreholes into the crust, and it identifies
which craters may have excavated deep-seated or volatile-bearing material. For rover
traverse planning it also predicts **ejecta block size**, which feeds the boulder-hazard
model of §6.2.

**Source.** Melosh, H. J. (1989), *Impact Cratering: A Geologic Process*, Oxford University
Press, Ch. 5–7.

---

### 4.3 Size classification

**Statement.** Craters are assigned to classes by rim-crest diameter:

| Class | Diameter | Physical basis | Colour |
|---|---|---|---|
| **Micro** | < 100 m | Below LOLA resolution; regolith-scale | grey |
| **Very small** | 100 m – 1 km | Below Robbins completeness limit | light blue |
| **Small** | 1 – 15 km | **Simple morphology**: bowl-shaped, $d/D \approx 0.2$ | blue |
| **Medium** | 15 – 50 km | **Complex**: terraced walls, central peak | green |
| **Large** | 50 – 200 km | Complex with peak ring onset | orange |
| **Giant** | 200 – 300 km | Peak-ring basin | red |
| **Basin** | > 300 km | Multi-ring impact basin | purple |

**Derivation / Proof.** The class boundaries are **not arbitrary**. Each corresponds to a
documented physical or observational transition:

- **1 km** — the completeness limit of the Robbins catalogue. Below it, no authoritative
  global census exists, so LunarSerpent's own detections take over and are labelled as such.
- **15 km** — the **simple→complex transition** on the Moon (§4.1). This is a change in
  physics, not in nomenclature.
- **~50 km** — onset of **peak-ring** structures replacing single central peaks.
- **~300 km** — onset of **multi-ring basins**.
- **100 m** — approximately the LROC WAC resolution limit and the practical floor for
  global-scale work.

**Why this one.** The project requires classification "backed with proof/formulas". A scheme
whose boundaries track morphological transitions is defensible from cratering mechanics; a
scheme with round-number bins (10/100/1000 km) is not. Every boundary above can be cited.

**Sources.** Pike (1977) *op. cit.*; Melosh (1989) *op. cit.*;
Head, J. W. et al. (2010), *Global Distribution of Large Lunar Craters*, Science **329**,
1504–1507. DOI: [10.1126/science.1195050](https://doi.org/10.1126/science.1195050)

---

### 4.4 Degradation state and crater age — an explicit statement of limits

> **This section documents what the system will *not* claim.**

**The problem.** Crater age cannot be measured from topography. There is no formula
$\text{age} = f(\text{shape})$ with defensible accuracy for an individual crater.

**What is defensible.** Three distinct, separately-labelled quantities:

**(a) Degradation index** — a *measured, dimensionless* quantity:

$$\Delta = \frac{(d/D)_{\text{measured}}}{(d/D)_{\text{Pike}}} \in (0, 1]$$

$\Delta \to 1$ indicates a pristine crater matching the fresh-crater fit; $\Delta \ll 1$
indicates infilling and rim erosion. This is a **direct observable** and is reported as such.

**(b) Stratigraphic epoch** — assigned from the published Unified Geologic Map of the Moon
for *named* craters. Categorical, authoritative, and carries the map's own uncertainty:

| System | Approx. age (Ga) |
|---|---|
| Copernican | 0 – 1.1 |
| Eratosthenian | 1.1 – 3.2 |
| Imbrian | 3.2 – 3.85 |
| Nectarian | 3.85 – 3.92 |
| Pre-Nectarian | > 3.92 |

**(c) Model age** — from crater counting on a surface, using the Neukum production function
$N(>D)$ and chronology function

$$N(1) = 5.44\times10^{-14}\left(e^{6.93\,T} - 1\right) + 8.38\times10^{-4}\,T$$

with $T$ in Gyr and $N(1)$ the cumulative number of craters $\ge 1$ km per km².

**Why this structure.** Reporting a single "age" number per crater would be scientifically
indefensible, and the project brief demands scientific provability. LunarSerpent therefore
reports the **measured** degradation index always, the **stratigraphic epoch** where the
published map provides one, and a **model age with explicit uncertainty** only where a
statistically adequate crater count is available (typically requiring ≥ 50 superposed
craters on a mapped ejecta blanket).

**Sources.**
Neukum, G., Ivanov, B. A. & Hartmann, W. K. (2001), *Cratering records in the inner Solar
System in relation to the lunar reference system*, Space Sci. Rev. **96**, 55–86.
DOI: [10.1023/A:1011989004263](https://doi.org/10.1023/A:1011989004263)
Fortezzo, C. M., Spudis, P. D. & Harrel, S. L. (2020), *Release of the Digital Unified Global
Geologic Map of the Moon at 1:5,000,000 Scale*, LPSC 51, Abstract 2760.

---

## 5. Detection

### 5.1 DEM-based crater detection

**Statement.** A candidate crater is a connected region satisfying:

1. An annulus of profile curvature $\kappa_{\text{profile}} < -\tau_\kappa$ (the rim),
2. enclosing a region of $\kappa_{\text{profile}} > 0$ (the floor),
3. with radial symmetry measured by the **circular Hough accumulator** exceeding $\tau_H$,
4. and measured depth consistent with §4.1 to within the stated ±30 % band.

**Derivation / Proof.** Condition (1)–(2) is the topographic signature derived in §3.4.
Condition (3) formalises circularity: for a candidate centre $(x_0,y_0)$ and radius $r$, the
Hough score is

$$A(x_0,y_0,r) = \sum_{\text{edge pixels}} \mathbb{1}\big[\,\big|\|\mathbf{p}-\mathbf{c}\| - r\big| < \epsilon\,\big]$$

which is maximal when edge pixels lie on a circle. Condition (4) is a **physical consistency
filter** and is what distinguishes this from generic blob detection: a circular depression
whose depth is wildly inconsistent with impact scaling is probably not an impact crater.

**Why this one.** Intensity-based detection confounds craters with albedo features (fresh
ejecta rays, mare/highland boundaries) which have no topographic expression. Topographic
detection is immune to this by construction. Combining curvature + Hough + physical
consistency gives three quasi-independent tests, so false positives must satisfy all three.

**Validation.** Because Robbins is complete for $D \ge 1$ km, detector performance is measured
against it on that range — yielding genuine precision/recall rather than self-assessment. The
detector is then applied **below** 1 km where no ground truth exists, and its reported
confidence is the value calibrated on the $\ge 1$ km range.

**Sources.**
Hough, P. V. C. (1962), *Method and Means for Recognizing Complex Patterns*, US Patent 3,069,654.
Duda, R. O. & Hart, P. E. (1972), *Use of the Hough transformation to detect lines and curves
in pictures*, Comm. ACM **15**(1), 11–15. DOI: [10.1145/361237.361242](https://doi.org/10.1145/361237.361242)
Salamunićcar, G. & Lončarić, S. (2010), *Method for crater detection from digital topography
data*, Advances in Space Research **45**(1), 105–114.
DOI: [10.1016/j.asr.2009.07.026](https://doi.org/10.1016/j.asr.2009.07.026)

---

### 5.2 Boulder height from shadow length

**Statement.** For a boulder casting a shadow of measured length $L$ on locally level ground,
illuminated at solar **incidence angle** $i$ (measured from the surface normal), with solar
**elevation** $e = 90° - i$:

$$\boxed{\;h = L\,\tan e = \frac{L}{\tan i}\;}$$

**Derivation / Proof.** Consider a vertical object of height $h$ on a horizontal plane. The
sun's rays make angle $e$ with the plane. The shadow tip lies where the ray grazing the top of
the object meets the ground. By similar triangles, $\tan e = h / L$, hence $h = L\tan e$.
Since $e = 90° - i$ and $\tan(90° - i) = \cot i$, the second form follows.

**Slope correction.** On ground of slope $\theta$ inclined along the illumination azimuth, the
relation becomes

$$h = L\,\frac{\sin(e \pm \theta)}{\cos\theta}$$

with the sign positive for slopes tilted away from the sun. LunarSerpent applies this
correction using the local slope from §3.2.

**Why this one.** Shadow measurement is the **only** technique that recovers absolute boulder
height from a single monoscopic image. Stereo photogrammetry needs an image pair; photoclinometry
needs a calibrated reflectance model and known albedo. Shadow length needs only geometry, which
is recorded exactly in the image label.

**Why low sun matters.** The measurement is most sensitive when $\partial L/\partial h = \cot e$
is large — i.e. at **low solar elevation**. At $e = 10°$ a 0.5 m boulder casts a 2.8 m shadow,
resolvable at OHRC's 0.25 m/px; at $e = 60°$ the same boulder casts only 0.29 m of shadow, barely
one pixel. **Boulder detection must therefore use low-sun imagery**, and the pipeline records
$e$ per scene and reports the resulting minimum detectable boulder height.

**Detection limit.** With pixel scale $p$ and a minimum resolvable shadow of $k$ pixels
(conservatively $k = 3$):

$$h_{\min} = k\,p\,\tan e$$

For OHRC ($p = 0.25$ m) at $e = 15°$: $h_{\min} = 3 \times 0.25 \times 0.268 = 0.20$ m.
**LunarSerpent reports this limit alongside every boulder survey**, so that "no boulders
detected" is never confused with "no boulders present".

**Sources.**
Watkins, R. N. et al. (2019), *Boulder distributions around young lunar impact craters*,
JGR Planets **124**, 2754–2771. DOI: [10.1029/2019JE005963](https://doi.org/10.1029/2019JE005963)
Bandeira, L., Ding, W. & Stepinski, T. F. (2012), *Detection of sub-kilometer craters in high
resolution planetary images using shape and texture features*, Advances in Space Research
**49**(1), 64–74. DOI: [10.1016/j.asr.2011.08.021](https://doi.org/10.1016/j.asr.2011.08.021)

---

### 5.3 Boulder size–frequency distribution

**Statement.** The cumulative number of boulders with diameter $> D$ per unit area follows

$$N(>D) = k\,D^{-\beta}, \qquad \beta \approx 2.5 - 3.5$$

**Derivation / Proof.** Empirical power law observed for fragmentation products generally, and
confirmed for lunar ejecta blocks. It is the signature of scale-invariant brittle fragmentation.

**Why this one.** It permits **extrapolation below the detection limit**. Having measured
$N(>D)$ for $D > h_{\min}$, the fitted law estimates the population of smaller, undetectable
boulders — which is exactly what a rover hazard assessment needs, since sub-resolution
boulders still threaten wheels. This converts "we cannot see them" into a *quantified
probabilistic hazard* rather than an unstated gap.

**Source.** Watkins et al. (2019) *op. cit.*; Golombek, M. & Rapp, D. (1997), *Size-frequency
distributions of rocks on Mars and Earth analog sites*, JGR Planets **102**(E2), 4117–4129.
DOI: [10.1029/96JE03319](https://doi.org/10.1029/96JE03319)

---

## 6. Hazard, risk and cost

### 6.1 Slope hazard

**Statement.** With rover sustained gradeability $\theta_{\max}$ and static stability limit
$\theta_{\text{tip}}$:

$$H_\theta = \begin{cases}
0 & \theta < 0.5\,\theta_{\max}\\[4pt]
\dfrac{\theta - 0.5\theta_{\max}}{0.5\theta_{\max}} & 0.5\theta_{\max} \le \theta < \theta_{\max}\\[8pt]
1 & \theta \ge \theta_{\max}\ \ (\textbf{impassable})
\end{cases}$$

**Derivation / Proof.** Piecewise-linear ramp: zero hazard well below the limit, rising
linearly through the margin, saturating at the limit. The half-limit knee reflects standard
engineering practice of a **2× safety factor** on a mobility limit.

**Physical basis for $\theta_{\max}$.** A rover ascends without slipping while the available
traction exceeds the gravitational component along the slope:

$$\mu\, m g\cos\theta \ge m g\sin\theta \quad\Longrightarrow\quad \theta_{\max} = \arctan\mu$$

For lunar regolith the wheel–soil friction coefficient is $\mu \approx 0.3 - 0.6$, giving
$\theta_{\max} \approx 17° - 31°$. The default 15° for a VIPER-class rover sits conservatively
inside this range. Tip-over is a separate, geometric limit set by the centre-of-mass position.

**Why this one.** A binary passable/impassable threshold makes the planner indifferent between
a 1° and a 14° route. A graded cost makes it prefer gentler terrain while still permitting
steep sections when necessary — which is the actual behaviour required.

**Source.** Bekker, M. G. (1969), *Introduction to Terrain-Vehicle Systems*, University of
Michigan Press. Lunar friction values: Carrier, W. D., Olhoeft, G. R. & Mendell, W. (1991),
*Physical properties of the lunar surface*, in *Lunar Sourcebook*, Cambridge Univ. Press, Ch. 9.

---

### 6.2 Boulder and roughness hazard

**Statement.** With ground clearance $c$ and wheel diameter $d_w$:

$$H_b = \min\!\left(1,\ \frac{\text{TRI}}{c}\right), \qquad
\text{blocked if } h_{\text{boulder}} > \min(c,\ 0.5\,d_w)$$

**Derivation / Proof.** An obstacle is straddled if lower than the chassis clearance $c$, and
climbed if lower than roughly half the wheel diameter — the standard step-obstacle rule for
rigid-wheeled vehicles, arising because the wheel must be able to establish contact above the
obstacle's centre to generate climbing torque.

**Why this one.** It ties the hazard directly to **rover geometry**, so changing the rover
profile changes the hazard map correctly rather than requiring re-tuned abstract weights.

---

### 6.3 Crater proximity hazard

**Statement.** For a crater of radius $r_c$ at distance $s$ from the point:

$$H_c = \begin{cases}
1 & s < r_c \quad (\text{inside the rim})\\
\exp\!\left(-\dfrac{s - r_c}{\ell}\right) & s \ge r_c
\end{cases}$$

with decay length $\ell = 0.5\,r_c$.

**Derivation / Proof.** Inside the rim the terrain is the crater wall — steep by construction
(§4.1). Outside, hazard decays because **ejecta block density falls off with distance**,
empirically as a steep power law, approximated here by an exponential with a scale
proportional to crater size. The proportionality $\ell \propto r_c$ reflects that ejecta
blankets scale with the crater that produced them (continuous ejecta typically extends
$\sim1$ crater radius beyond the rim).

**Why this one.** It automatically produces a **standoff distance** that scales with crater
size — the planner avoids a 10 km crater by a wide margin and a 100 m crater narrowly, without
any hand-tuned per-crater rules.

---

### 6.4 Composite cost surface

**Statement.** The traversal cost of cell $i$:

$$C_i = \underbrace{\frac{s_{3D}}{v(\theta_i)}}_{\text{time}}\cdot\underbrace{\big(1 + \gamma\,H_i\big)}_{\text{risk multiplier}}, \qquad
H_i = \max\big(H_\theta, H_b, H_c\big)$$

and $C_i = \infty$ where any hazard is blocking.

**Derivation / Proof.** The base term is **traverse time** — a physically meaningful,
additive, non-negative quantity, which is exactly what a shortest-path algorithm requires. The
multiplier inflates the effective cost of risky cells so the planner trades time against risk
at a rate set by $\gamma$.

**Why $\max$ and not a weighted sum.** Hazards are **not independent and not compensatory**:
a cell with an impassable slope is impassable regardless of how smooth it is. A weighted sum
would let a low roughness score dilute a fatal slope score. The max operator implements
"a chain is as strong as its weakest link", which is the correct semantics for safety.

**Why cost must be non-negative and additive.** Dijkstra and A\* are only correct for
non-negative edge weights, and A\*'s optimality additionally needs consistency. Defining cost
as time × (positive multiplier) guarantees both by construction. This is proved in §9.1.

$\gamma$ is user-exposed as a **risk-aversion parameter**: $\gamma = 0$ gives the fastest
route ignoring risk, large $\gamma$ gives the safest route ignoring time. Presenting the
route family across $\gamma$ is more informative than asserting a single "best" answer.

---

### 6.5 Safety score

**Statement.** For a completed path $P$:

$$S = 100\left(1 - \frac{\sum_{i\in P} H_i\,s_i}{\sum_{i\in P} s_i}\right)$$

**Derivation / Proof.** The **distance-weighted mean hazard** along the route, mapped to
0–100. Weighting by segment length (not cell count) is essential: a 10 m hazardous segment
should not count as much as a 10 km one.

**Why this one.** It is interpretable ("this route is 87 % safe" means the length-weighted
mean hazard is 0.13) and comparable between routes of different length — which the
multi-algorithm comparison of Part 6 requires.

---

## 7. Rover mobility model

### 7.1 Power-limited speed on a slope

**Statement.** For a rover of mass $m$ with available propulsive power $P$ and rolling
resistance coefficient $\mu_r$:

$$v(\theta) = \min\left(v_{\text{nom}},\ \frac{P}{m g\,(\sin\theta + \mu_r\cos\theta)}\right)$$

**Derivation / Proof.** Force balance on an incline. The tractive force required is

$$F = \underbrace{mg\sin\theta}_{\text{gravity}} + \underbrace{\mu_r\,mg\cos\theta}_{\text{rolling resistance}}$$

Mechanical power is $P = Fv$, so $v = P/F$, giving the expression above. The $\min$ imposes the
commanded nominal speed on level ground, where the power limit is not binding.

**Why this one.** It is derived from first principles rather than fitted, so it extrapolates
correctly to new rover profiles and slopes. It reproduces the observed behaviour that rovers
slow markedly on grades, and it goes to zero as $\theta \to \theta_{\max}$, which is
physically correct.

Note that $g$ appears explicitly: the same rover is **six times faster uphill on the Moon**
than on Earth for equal power, because gravitational resistance scales with $g$. Using
Earth gravity here would be a significant error.

**Rolling resistance for lunar regolith.** $\mu_r \approx 0.2 - 0.3$ for a rigid wheel on
loose regolith, dominated by compaction resistance — substantially higher than on a prepared
surface. Apollo LRV experience is the primary source.

**Source.** Bekker (1969) *op. cit.*; Asnani, V., Delap, D. & Creager, C. (2009), *The
development of wheels for the Lunar Roving Vehicle*, Journal of Terramechanics **46**(3),
89–103. DOI: [10.1016/j.jterra.2009.02.005](https://doi.org/10.1016/j.jterra.2009.02.005)

---

### 7.2 Traverse time and energy

**Statement.**

$$T = \sum_i \frac{s_{3D,i}}{v(\theta_i)}, \qquad
E = \sum_i m g\,(\sin\theta_i + \mu_r\cos\theta_i)\,s_{3D,i}$$

**Derivation / Proof.** Time is the sum of per-segment durations. Energy is the line integral
of tractive force along the path, $E = \int F\,ds$. Descending segments with
$\sin\theta < -\mu_r\cos\theta$ would give negative energy; since these rovers have no
regenerative braking, such terms are **clamped to zero** rather than credited.

**Why this one.** Energy, not time, is usually the binding constraint for a solar-powered
rover, and it determines whether a traverse can be completed within a lunar day. Reporting
both lets the user see which constrains their mission.

---

## 8. Rendering

### 8.1 Unlit material — satisfying the "no sunlight" requirement

**Statement.** The globe's surface colour is

$$\mathbf{c}_{\text{rendered}} = \mathbf{c}_{\text{texture}}(u,v)$$

with **no dependence on the surface normal $\mathbf{n}$ or any light direction $\mathbf{l}$.**

**Derivation / Proof.** A physically-based material computes
$\mathbf{c} = \mathbf{c}_{\text{tex}}\,(\mathbf{n}\cdot\mathbf{l})\,\ldots$, which vanishes
wherever $\mathbf{n}\cdot\mathbf{l} \le 0$ — i.e. **half the globe is always black**, and
terrain near the terminator is arbitrarily dark. Removing the $(\mathbf{n}\cdot\mathbf{l})$
factor makes rendered brightness depend only on texture, so **every point is equally legible
regardless of viewing direction**, including both poles.

**Why this one.** This is the direct technical implementation of Part 1's requirement that the
globe be *"viewable from all sides, a full 360°, clearly, without sunlight/illumination
effects"*. It is achieved with an **unlit** material and no light sources in the scene.

This is legitimate because the WAC basemap is **already photometrically normalised** — the
source data has had illumination effects removed by its producers, so it represents albedo,
not brightness. Applying a second, artificial illumination on top would corrupt a
radiometrically-corrected product.

**Source.** Requirement traceability: `PRD.md` FR-1.6. Photometric normalisation of the WAC
mosaic: Robinson et al. (2010) *op. cit.*

---

## 9. Path planning mathematics

### 9.1 Admissibility and consistency of the A\* heuristic

**Statement.** LunarSerpent uses

$$h(n) = \frac{s_{\text{gc}}(n, \text{goal})}{v_{\max}}$$

— the great-circle distance to the goal divided by the rover's maximum speed.

**Proof of admissibility.** Let $h^*(n)$ be the true optimal remaining cost. Any real path
from $n$ to the goal has length $\ell \ge s_{\text{gc}}$, because the great-circle distance is
the *minimum possible* distance between two points on the sphere (§2.1). Each segment is
traversed at speed $v \le v_{\max}$, and the risk multiplier $(1+\gamma H) \ge 1$. Therefore

$$h^*(n) \;\ge\; \frac{\ell}{v_{\max}} \;\ge\; \frac{s_{\text{gc}}}{v_{\max}} \;=\; h(n)$$

so $h$ never overestimates. ∎

**Proof of consistency.** For neighbouring cells $n, n'$ with edge cost $c(n,n')$, the
triangle inequality on the sphere gives
$s_{\text{gc}}(n,\text{goal}) \le s_{\text{gc}}(n,n') + s_{\text{gc}}(n',\text{goal})$.
Dividing by $v_{\max}$ and noting $c(n,n') \ge s_{\text{gc}}(n,n')/v_{\max}$:

$$h(n) \le \frac{s_{\text{gc}}(n,n')}{v_{\max}} + h(n') \le c(n,n') + h(n')$$

∎

**Why this matters.** Admissibility guarantees A\* returns the **optimal** path; consistency
guarantees it does so **without re-expanding** any node. Both properties are *required* for
the algorithm comparison in Part 6 to be a fair test — otherwise a faster runtime might simply
reflect an inadmissible heuristic cutting corners, and comparing path costs would be
meaningless.

**Source.** Hart, P. E., Nilsson, N. J. & Raphael, B. (1968), *A Formal Basis for the
Heuristic Determination of Minimum Cost Paths*, IEEE Trans. Systems Science and Cybernetics
**4**(2), 100–107. DOI: [10.1109/TSSC.1968.300136](https://doi.org/10.1109/TSSC.1968.300136)

---

### 9.2 Grid-discretisation error and why Theta\* is included

**Statement.** On an 8-connected grid, the shortest representable path can exceed the true
Euclidean shortest path by up to

$$\frac{\sqrt{2}}{\,2\cos(\pi/8)\,}\ \approx\ 1.0824 \quad (+8.24\%)$$

**Derivation / Proof.** An 8-connected grid restricts headings to multiples of 45°. A desired
heading falling midway between two allowed directions (worst case, 22.5° off) must be
approximated by alternating steps. Summing the projections gives the stated bound.

**Why this matters.** An 8 % length penalty is significant for a mission where energy is
budgeted tightly. **Any-angle** algorithms (Theta\*, Field D\*) remove this restriction by
allowing line-of-sight shortcuts between non-adjacent cells, converging on the true optimum.
This is precisely why the algorithm comparison in `ALGORITHMS.md` includes any-angle methods
rather than only grid-constrained ones — the comparison would otherwise be blind to a
systematic 8 % error affecting **all** grid-based candidates equally.

**Source.** Nash, A., Daniel, K., Koenig, S. & Felner, A. (2007), *Theta\*: Any-Angle Path
Planning on Grids*, Proc. AAAI, 1177–1183.

---

## 10. Summary — formula-to-requirement traceability

| § | Formula | Brief part | Primary source |
|---|---|---|---|
| 1.2 | Grid ↔ lat/lon mapping | 1, 4 | PDS3 labels (verified) |
| 1.3 | Sphere UV parameterisation | 1 | Derived |
| 2.1 | Haversine geodesic | 6 | Sinnott (1984) |
| 2.4 | Latitude-dependent cell size | 3, 4, 6 | Derived (spherical geometry) |
| 3.2 | Horn slope | 4, 6 | Horn (1981) |
| 3.4 | Zevenbergen–Thorne curvature | 2, 4 | Zevenbergen & Thorne (1987) |
| 3.5 | TRI / RMS slope, scale-dependence | 4, 6 | Riley (1999), Shepard (2001) |
| 4.1 | Depth–diameter scaling | 2, 3 | Pike (1974, 1977) |
| 4.3 | Size classification | 3 | Pike, Melosh, Head |
| 4.4 | Degradation / epoch / model age | 2 | Neukum (2001), Fortezzo (2020) |
| 5.1 | Curvature + Hough crater detection | 2 | Salamunićcar & Lončarić (2010) |
| 5.2 | Shadow-length boulder height | 2 | Watkins (2019) |
| 5.3 | Boulder size–frequency law | 2, 6 | Golombek & Rapp (1997) |
| 6.1 | Slope hazard, $\theta_{\max}=\arctan\mu$ | 6 | Bekker (1969) |
| 6.4 | Composite cost surface | 6 | Derived |
| 7.1 | Power-limited speed | 6 | Bekker (1969), Asnani (2009) |
| 8.1 | Unlit rendering | 1 | Derived from requirement |
| 9.1 | A\* admissibility proof | 6 | Hart, Nilsson & Raphael (1968) |
| 9.2 | Grid discretisation bound | 6 | Nash et al. (2007) |

---

## 11. Revision history

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-08-04 | Baseline. All formulas stated with derivation, alternatives considered, and DOI-resolvable sources. Georeferencing verified against live PDS labels at two resolutions. |
