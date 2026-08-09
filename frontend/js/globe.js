/**
 * LunarSerpent — 3D globe engine.
 *
 * Scientific constraints this module exists to satisfy
 * ---------------------------------------------------
 * 1. NO ILLUMINATION MODEL. The sphere uses MeshBasicMaterial, which is
 *    *unlit*: fragment colour is the texture value, independent of surface
 *    normal and view direction. Consequently every point on the globe renders
 *    at full brightness, both poles included, and the body is legible through
 *    a full 360° with no terminator and no dark limb. A lit material would
 *    make half the Moon unreadable, which is the opposite of the requirement.
 *
 * 2. REAL SELENOGRAPHIC COORDINATES. Positions are computed from latitude and
 *    longitude through an explicit mapping that matches THREE.SphereGeometry's
 *    own UV parameterisation, so a marker placed at (lat, lon) lands exactly on
 *    the texel showing that coordinate. No pixel-space guessing.
 *
 * 3. TRUE CRATER FOOTPRINTS. A crater of diameter D is drawn as a small circle
 *    of angular radius D/2R on the sphere — the actual rim trace — not as a
 *    fixed-size sprite. Its size on screen is therefore a measurement.
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';

export const R_MOON_M = 1737400.0;
const GLOBE_R = 1.0;                       // scene units; 1 unit = 1 lunar radius
const DEG = Math.PI / 180;

/* ── Coordinate mapping ────────────────────────────────────────────────────
 * THREE.SphereGeometry places a vertex at
 *     x = -r·cos(phi)·sin(theta),  y = r·cos(theta),  z = r·sin(phi)·sin(theta)
 * with theta the colatitude and phi the azimuth, and assigns uv.x = phi/2pi,
 * uv.y = 1 - theta/pi. An equirectangular basemap has longitude increasing
 * with uv.x and latitude decreasing with uv.y, so the mapping below is the
 * inverse of the geometry's own and is exact by construction.
 */
export function latLonToVec3(lat, lon, r = GLOBE_R) {
  const theta = (90 - lat) * DEG;
  const phi = (((lon % 360) + 360) % 360) * DEG;
  const st = Math.sin(theta);
  return new THREE.Vector3(
    -r * Math.cos(phi) * st,
    r * Math.cos(theta),
    r * Math.sin(phi) * st,
  );
}

export function vec3ToLatLon(v) {
  const r = v.length();
  const lat = 90 - Math.acos(THREE.MathUtils.clamp(v.y / r, -1, 1)) / DEG;
  let lon = Math.atan2(v.z, -v.x) / DEG;
  lon = ((lon % 360) + 360) % 360;
  return { lat, lon };
}

/** Destination point on a great circle — used to trace crater rims. */
function destination(lat, lon, bearingDeg, angDist) {
  const p1 = lat * DEG, l1 = lon * DEG, b = bearingDeg * DEG;
  const sp = Math.sin(p1), cp = Math.cos(p1);
  const sd = Math.sin(angDist), cd = Math.cos(angDist);
  const p2 = Math.asin(sp * cd + cp * sd * Math.cos(b));
  const l2 = l1 + Math.atan2(Math.sin(b) * sd * cp, cd - sp * Math.sin(p2));
  return { lat: p2 / DEG, lon: (((l2 / DEG) % 360) + 360) % 360 };
}

/**
 * Rank a feature for label placement.
 *
 * Ranking on raw diameter alone is wrong, and wrong in a way that hides exactly
 * the features people look for: Mare Imbrium is 1146 km across and Tycho is 85,
 * so on size Tycho loses every contest and the famous craters never appear.
 *
 * Diameter is therefore compared *within* a class, and the classes are ranked
 * by cartographic weight. Craters carry the highest weight because they are
 * what a viewer searches for by name; maria are large but few, and stay legible
 * even when ranked below craters, because they rarely compete for the same
 * pixels. The logarithm keeps a 2500 km basin from dominating a 200 km crater
 * by sheer magnitude.
 */
const KIND_WEIGHT = {
  crater: 3.2,
  mare: 2.4, oceanus: 2.4, sinus: 1.5, lacus: 1.4, palus: 1.3,
  mons: 2.0, mensa: 1.6, promontorium: 1.3,
  vallis: 1.7, rupes: 1.6, rima: 1.2, catena: 1.2, dorsum: 1.1,
  landing_site: 3.6,          // historically significant, and always small
  satellite_crater: 0.7,
  planitia: 1.5, terra: 1.5, albedo: 0.8, other: 0.9,
};

export function labelPriority(f) {
  const w = KIND_WEIGHT[f.kind] ?? 1.0;
  const size = Math.log10(Math.max(f.diameter_km || 1, 1) + 1);
  return w * 10 + size;
}

export class Globe {
  constructor(canvas) {
    this.canvas = canvas;

    this.renderer = new THREE.WebGLRenderer({
      canvas, antialias: true, alpha: false, powerPreference: 'high-performance',
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setClearColor(0x000000, 1);

    this.scene = new THREE.Scene();

    this.camera = new THREE.PerspectiveCamera(38, 1, 0.001, 100);
    this.camera.position.set(0, 0, 3.2);

    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.075;
    this.controls.rotateSpeed = 0.42;
    this.controls.zoomSpeed = 0.8;
    this.controls.minDistance = GLOBE_R * 1.02;   // sit just above the surface
    this.controls.maxDistance = 12;
    this.controls.enablePan = false;
    this.controls.autoRotateSpeed = 0.45;

    this._buildSphere();
    this._buildStars();
    this._buildGraticule();

    this.craterGroup = new THREE.Group();
    this.scene.add(this.craterGroup);

    // Detail patch: a partial sphere carrying a high-zoom mosaic of the region
    // currently in view. See setDetailPatch() for why this exists.
    this.patch = null;
    this.patchKey = null;

    this.marker = this._buildMarker();
    this.scene.add(this.marker);
    this.marker.visible = false;

    // Named-feature labels are rendered as real DOM elements layered over the
    // canvas, not as textures. Text therefore stays crisp at any zoom and
    // remains selectable and accessible, which a baked-texture label cannot be.
    this.labelRenderer = new CSS2DRenderer();
    this.labelRenderer.domElement.className = 'label-layer';
    canvas.parentElement.appendChild(this.labelRenderer.domElement);
    this.labelGroup = new THREE.Group();
    this.scene.add(this.labelGroup);
    this._labels = [];
    this._onLabelClick = null;

    this.raycaster = new THREE.Raycaster();
    this._onHover = null;
    this._onPick = null;
    this._bindInput();

    window.addEventListener('resize', () => this.resize());
    this.resize();
  }

  /* ── Scene construction ─────────────────────────────────────────────── */

  _buildSphere() {
    const geo = new THREE.SphereGeometry(GLOBE_R, 192, 96);
    // Unlit: colour == texture, independent of normal. This is the technical
    // mechanism for "no sunlight effects, visible from all sides".
    this.material = new THREE.MeshBasicMaterial({ color: 0x8c8c8c });
    this.sphere = new THREE.Mesh(geo, this.material);
    this.scene.add(this.sphere);
  }

  _buildStars() {
    const N = 2600, pos = new Float32Array(N * 3);
    for (let i = 0; i < N; i++) {
      // Uniform on a sphere: z ~ U(-1,1) gives equal-area bands.
      const u = Math.random() * 2 - 1;
      const t = Math.random() * Math.PI * 2;
      const s = Math.sqrt(1 - u * u), r = 40 + Math.random() * 20;
      pos[i * 3] = r * s * Math.cos(t);
      pos[i * 3 + 1] = r * u;
      pos[i * 3 + 2] = r * s * Math.sin(t);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    this.stars = new THREE.Points(g, new THREE.PointsMaterial({
      color: 0xffffff, size: 0.13, sizeAttenuation: true,
      transparent: true, opacity: 0.55,
    }));
    this.scene.add(this.stars);
  }

  /**
   * Graticule whose spacing follows the zoom.
   *
   * A fixed 30° grid is right for the whole disc and useless at 20 km altitude,
   * where the entire screen fits inside one cell. The step is therefore chosen
   * from the visible angular span using a 1-2-5 progression — the same series
   * used for map and chart gradations, because it keeps the mental arithmetic
   * of reading a position between gridlines trivial at every scale.
   */
  _buildGraticule(stepDeg = 30) {
    if (this.graticule) {
      for (const c of this.graticule.children) {
        c.geometry.dispose();
        c.material.dispose();
      }
      this.scene.remove(this.graticule);
    }

    const minor = [], major = [];
    const R = GLOBE_R * 1.0015;
    // Finer grids need finer arc segments or the lines visibly chord.
    const seg = Math.max(stepDeg / 12, 0.05);

    for (let lat = -90 + stepDeg; lat <= 90 - stepDeg + 1e-9; lat += stepDeg) {
      const target = Math.abs(lat) < 1e-9 ? major : minor;
      for (let lon = 0; lon < 360; lon += seg) {
        target.push(latLonToVec3(lat, lon, R), latLonToVec3(lat, lon + seg, R));
      }
    }
    for (let lon = 0; lon < 360 - 1e-9; lon += stepDeg) {
      const target = (Math.abs(lon) < 1e-9 || Math.abs(lon - 180) < 1e-9)
        ? major : minor;
      for (let lat = -90; lat < 90; lat += seg) {
        target.push(latLonToVec3(lat, lon, R), latLonToVec3(lat + seg, lon, R));
      }
    }

    const mk = (pts, opacity) => {
      const g = new THREE.BufferGeometry().setFromPoints(pts);
      return new THREE.LineSegments(g, new THREE.LineBasicMaterial({
        color: 0x4da3ff, transparent: true, opacity,
      }));
    };
    this.graticule = new THREE.Group();
    this.graticule.add(mk(minor, 0.16), mk(major, 0.34));
    this.graticule.visible = this._gratOn !== false;
    this.graticuleStep = stepDeg;
    this.scene.add(this.graticule);
  }

  /** Choose a 1-2-5 step giving roughly 6-10 lines across the view. */
  _graticuleStepFor(spanDeg) {
    const target = spanDeg / 8;
    const steps = [30, 20, 10, 5, 2, 1, 0.5, 0.2, 0.1, 0.05, 0.02, 0.01];
    let best = steps[0];
    for (const s of steps) {
      if (s <= target) { best = s; break; }
      best = s;
    }
    return best;
  }

  /** Rebuild the graticule only when the appropriate step actually changes. */
  updateGraticule() {
    if (!this.graticule) return;
    const d = this.camera.position.length();
    const spanDeg = Math.min(2 * Math.acos(Math.min(1 / d, 1)) / DEG, 180);
    const step = this._graticuleStepFor(spanDeg);
    if (step !== this.graticuleStep) this._buildGraticule(step);
  }

  _buildMarker() {
    const g = new THREE.Group();
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(0.012, 0.017, 40),
      new THREE.MeshBasicMaterial({
        color: 0x4da3ff, side: THREE.DoubleSide,
        transparent: true, opacity: 0.95, depthTest: false,
      }),
    );
    const dot = new THREE.Mesh(
      new THREE.SphereGeometry(0.0045, 12, 12),
      new THREE.MeshBasicMaterial({ color: 0xffffff, depthTest: false }),
    );
    g.add(ring, dot);
    g.renderOrder = 999;
    return g;
  }

  /* ── Basemap ────────────────────────────────────────────────────────── */

  async setTexture(url) {
    const tex = await new THREE.TextureLoader().loadAsync(url);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
    tex.minFilter = THREE.LinearMipmapLinearFilter;
    tex.magFilter = THREE.LinearFilter;
    tex.wrapS = THREE.RepeatWrapping;
    if (this.material.map) this.material.map.dispose();
    this.material.map = tex;
    this.material.color.set(0xffffff);
    this.material.needsUpdate = true;
    return { width: tex.image.width, height: tex.image.height };
  }

  /* ── Detail patch (level of detail) ─────────────────────────────────── */

  /**
   * Return the lat/lon window the camera can actually see, and the ground
   * resolution the screen can resolve within it.
   *
   * The half-angle of the visible cap is derived from the camera's distance
   * from the centre: for a camera at distance d from the centre of a unit
   * sphere, the horizon lies at an angular radius of acos(1/d). Restricting
   * the request to that cap is what keeps the tile count bounded — asking for
   * the whole globe at high zoom would be gigabytes.
   */
  visibleRegion() {
    const d = this.camera.position.length();
    const centre = vec3ToLatLon(this.camera.position);

    // Angular radius of the visible cap, padded a little so the patch extends
    // past the screen edge and no seam is visible while panning.
    const horizon = Math.acos(Math.min(1 / d, 1));
    const half = Math.min(horizon * 1.35, Math.PI / 2) / DEG;

    // Ground metres per screen pixel at the sub-camera point.
    const vfov = this.camera.fov * DEG;
    const groundHeight = 2 * (d - GLOBE_R) * Math.tan(vfov / 2) * R_MOON_M;
    const mPerPx = groundHeight / Math.max(this.canvas.clientHeight, 1);

    const south = Math.max(-90, centre.lat - half);
    const north = Math.min(90, centre.lat + half);
    // Longitude span must widen with latitude: a degree of longitude covers
    // less ground near the poles, so the same screen width spans more degrees.
    const cosLat = Math.max(Math.cos(centre.lat * DEG), 0.08);
    const lonHalf = Math.min(half / cosLat, 180);

    return {
      centre, south, north,
      west: centre.lon - lonHalf,
      east: centre.lon + lonHalf,
      mPerPx,
      full: (north - south) >= 179 || lonHalf >= 179,
    };
  }

  /**
   * Attach a high-resolution mosaic to a lat/lon window.
   *
   * THREE.SphereGeometry accepts phiStart/phiLength and thetaStart/thetaLength,
   * so a *partial* sphere gives a perfectly curved patch whose UV
   * parameterisation is identical to the full globe's. The mosaic therefore
   * maps onto it with no reprojection, exactly as the basemap does — which is
   * why the patch lines up with the crater rims and the graticule.
   */
  /**
   * @param {string} url        imagery for this window
   * @param {object} bounds     {south, north, west, east}
   * @param {object} [relief]   {data, width, height, exaggeration}
   */
  async setDetailPatch(url, bounds, relief = null) {
    const tex = await new THREE.TextureLoader().loadAsync(url);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
    tex.minFilter = THREE.LinearMipmapLinearFilter;
    tex.magFilter = THREE.LinearFilter;
    tex.generateMipmaps = true;

    const { south, north, west, east } = bounds;

    // Segment counts must match the elevation lattice exactly: a SphereGeometry
    // with w x h segments emits (w+1) x (h+1) vertices in the same row-major,
    // north-first order the grid arrives in, so vertex i pairs with sample i.
    const wSeg = relief ? relief.width - 1
      : Math.max(64, Math.ceil((east - west) * 1.5));
    const hSeg = relief ? relief.height - 1
      : Math.max(48, Math.ceil((north - south) * 1.5));

    const geo = new THREE.SphereGeometry(
      GLOBE_R * 1.0004,          // hair above the base sphere, avoids z-fighting
      wSeg, hSeg,
      west * DEG, (east - west) * DEG,
      (90 - north) * DEG, (north - south) * DEG,
    );

    if (relief && relief.data && relief.exaggeration > 0) {
      this._displace(geo, relief);
    }

    const mat = new THREE.MeshBasicMaterial({ map: tex });  // unlit, as the base
    const mesh = new THREE.Mesh(geo, mat);

    this.clearDetailPatch();
    this.patch = mesh;
    this.patchRelief = relief || null;
    this.scene.add(mesh);
  }

  /**
   * Push each vertex radially outward by its measured elevation.
   *
   * Lunar relief is minute against the body: Tycho is 4.5 km deep on a
   * 1737 km radius, or 0.26 %. At true scale it is invisible, which is why
   * every planetary visualisation exaggerates the vertical — and why the
   * factor must be *displayed*, since exaggerated relief is a rendering
   * choice, not a measurement.
   *
   * The displacement is radial, so it preserves the vertex's latitude and
   * longitude exactly. Only its distance from the centre changes, which keeps
   * the imagery, the crater rims and the labels registered to the terrain.
   */
  _displace(geo, relief) {
    const pos = geo.attributes.position;
    const { data, exaggeration } = relief;
    const n = Math.min(pos.count, data.length);

    for (let i = 0; i < n; i++) {
      const e = data[i];
      if (!Number.isFinite(e)) continue;
      const x = pos.getX(i), y = pos.getY(i), z = pos.getZ(i);
      const r = Math.hypot(x, y, z);
      if (r === 0) continue;
      // Fraction of a lunar radius, scaled for visibility.
      const k = 1 + (e * exaggeration) / R_MOON_M;
      pos.setXYZ(i, x * k, y * k, z * k);
    }
    pos.needsUpdate = true;
    geo.computeBoundingSphere();
  }

  clearDetailPatch() {
    if (!this.patch) return;
    this.patch.geometry.dispose();
    if (this.patch.material.map) this.patch.material.map.dispose();
    this.patch.material.dispose();
    this.scene.remove(this.patch);
    this.patch = null;
  }

  /* ── Craters ────────────────────────────────────────────────────────── */

  /**
   * Draw crater rims as true small circles on the sphere.
   *
   * All rims of one class share a single LineSegments object, so the whole
   * catalogue view costs one draw call per class rather than one per crater —
   * which is what makes thousands of craters interactive.
   */
  setCraters(craters, classColours) {
    this.clearCraters();
    if (!craters || !craters.length) return 0;

    const byClass = new Map();
    for (const c of craters) {
      if (!byClass.has(c.class)) byClass.set(c.class, []);
      byClass.get(c.class).push(c);
    }

    let drawn = 0;
    for (const [cls, list] of byClass) {
      const pts = [];
      for (const c of list) {
        // Angular radius of the rim, in radians, on the unit sphere.
        const ang = (c.diameter_km * 500.0) / R_MOON_M;
        // More segments for larger craters; small ones need very few.
        const segs = ang > 0.05 ? 64 : ang > 0.012 ? 32 : 16;
        const step = 360 / segs;
        // Lift the trace slightly so it is not z-fought by the sphere.
        const rr = GLOBE_R * (1 + Math.min(ang * 0.05, 0.004) + 0.0022);
        let prev = null;
        for (let b = 0; b <= 360; b += step) {
          const p = destination(c.lat, c.lon, b, ang);
          const v = latLonToVec3(p.lat, p.lon, rr);
          if (prev) pts.push(prev, v);
          prev = v;
        }
        drawn++;
      }
      if (!pts.length) continue;
      const geo = new THREE.BufferGeometry().setFromPoints(pts);
      const mat = new THREE.LineBasicMaterial({
        color: new THREE.Color(classColours[cls] || '#ffffff'),
        transparent: true, opacity: 0.88,
      });
      const seg = new THREE.LineSegments(geo, mat);
      seg.userData.craterClass = cls;
      this.craterGroup.add(seg);
    }
    return drawn;
  }

  clearCraters() {
    for (const child of [...this.craterGroup.children]) {
      child.geometry.dispose();
      child.material.dispose();
      this.craterGroup.remove(child);
    }
  }

  setClassVisible(cls, visible) {
    for (const c of this.craterGroup.children) {
      if (c.userData.craterClass === cls) c.visible = visible;
    }
  }

  /* ── Named-feature labels ───────────────────────────────────────────── */

  /**
   * Place labels for officially named features.
   *
   * Each label is anchored slightly above the surface at the feature's true
   * selenographic coordinate. Labels on the far side of the globe are hidden
   * every frame by a dot-product test against the view direction — without
   * that, names from the hemisphere facing away would bleed through the sphere
   * and clutter the view.
   */
  setLabels(features, { onClick } = {}) {
    this.clearLabels();
    this._onLabelClick = onClick || null;

    for (const f of features) {
      const el = document.createElement('div');
      el.className = `feat-label kind-${f.kind}`;
      el.textContent = f.name;
      el.title = f.diameter_km
        ? `${f.kind_label} · D ${f.diameter_km.toFixed(1)} km`
        : f.kind_label;

      el.addEventListener('pointerdown', (e) => e.stopPropagation());
      el.addEventListener('click', (e) => {
        e.stopPropagation();
        if (this._onLabelClick) this._onLabelClick(f);
      });

      const obj = new CSS2DObject(el);
      obj.position.copy(latLonToVec3(f.lat, f.lon, GLOBE_R * 1.008));
      obj.userData.feature = f;
      obj.userData.priority = labelPriority(f);
      this.labelGroup.add(obj);
      this._labels.push(obj);
    }
    // Draw order follows priority so the important names are placed first.
    this._labels.sort((a, b) => b.userData.priority - a.userData.priority);
    return this._labels.length;
  }

  clearLabels() {
    for (const o of this._labels) {
      if (o.element?.parentNode) o.element.parentNode.removeChild(o.element);
      this.labelGroup.remove(o);
    }
    this._labels = [];
  }

  setLabelsVisible(on) { this.labelGroup.visible = on; }

  /**
   * Decide which labels are actually drawn this frame.
   *
   * Two filters, in order:
   *
   * 1. **Horizon cull.** A point is on the visible cap when its unit vector
   *    projects onto the camera direction by more than GLOBE_R/|cam|. Without
   *    this, names from the far hemisphere bleed through the sphere.
   *
   * 2. **Screen-space collision.** Labels are placed largest-first, and any
   *    label whose bounding box overlaps one already placed is dropped. This is
   *    what stops the clutter: on a real map, a name is either legible in its
   *    own space or it is not shown at all. Because placement follows priority,
   *    what survives a crowded view is always the most significant feature.
   *
   * Throttled to ~20 Hz — label sets change far more slowly than frames do, and
   * measuring DOM rectangles every frame would be wasteful.
   */
  _cullLabels() {
    if (!this.labelGroup.visible || !this._labels.length) return;

    const now = performance.now();
    if (now - (this._lastCull || 0) < 50) return;
    this._lastCull = now;

    const cam = this.camera.position;
    const camLen = cam.length();
    const horizon = (GLOBE_R / camLen) * 0.94;

    const w = this.canvas.clientWidth;
    const h = this.canvas.clientHeight;
    const placed = [];
    const PAD = 3;          // px of breathing room between neighbours

    for (const o of this._labels) {
      const el = o.element;
      if (!el) continue;

      const dot = o.position.dot(cam) / (o.position.length() * camLen);
      if (dot <= horizon) {
        el.classList.remove('shown');
        el.style.display = 'none';
        continue;
      }

      // Project to screen space to test for overlap.
      const p = o.position.clone().project(this.camera);
      const x = (p.x * 0.5 + 0.5) * w;
      const y = (-p.y * 0.5 + 0.5) * h;

      // Off-screen labels cost nothing to hide and must not reserve space.
      if (x < -80 || x > w + 80 || y < -30 || y > h + 30) {
        el.classList.remove('shown');
        el.style.display = 'none';
        continue;
      }

      el.style.display = '';
      const bw = (el.offsetWidth || 60) + PAD * 2;
      const bh = (el.offsetHeight || 14) + PAD * 2;
      const box = { l: x - bw / 2, r: x + bw / 2, t: y - bh / 2, b: y + bh / 2 };

      let clash = false;
      for (const q of placed) {
        if (box.l < q.r && box.r > q.l && box.t < q.b && box.b > q.t) {
          clash = true;
          break;
        }
      }
      if (clash) {
        el.classList.remove('shown');
        el.style.display = 'none';
      } else {
        placed.push(box);
        el.classList.add('shown');
      }
    }
    this._shownLabels = placed.length;
  }

  /** How many labels survived culling — reported in the status bar. */
  shownLabelCount() { return this._shownLabels || 0; }

  /* ── Interaction ────────────────────────────────────────────────────── */

  _ndc(ev) {
    const r = this.canvas.getBoundingClientRect();
    return new THREE.Vector2(
      ((ev.clientX - r.left) / r.width) * 2 - 1,
      -((ev.clientY - r.top) / r.height) * 2 + 1,
    );
  }

  _hit(ev) {
    this.raycaster.setFromCamera(this._ndc(ev), this.camera);
    const hits = this.raycaster.intersectObject(this.sphere, false);
    return hits.length ? vec3ToLatLon(hits[0].point) : null;
  }

  _bindInput() {
    let downAt = null;

    this.canvas.addEventListener('pointerdown', (e) => {
      downAt = { x: e.clientX, y: e.clientY, t: performance.now() };
    });

    this.canvas.addEventListener('pointerup', (e) => {
      if (!downAt) return;
      const moved = Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y);
      const held = performance.now() - downAt.t;
      downAt = null;
      // Distinguish a click from the end of an orbit drag.
      if (moved > 5 || held > 450) return;
      const c = this._hit(e);
      if (c && this._onPick) this._onPick(c);
    });

    this.canvas.addEventListener('pointermove', (e) => {
      if (!this._onHover) return;
      this._onHover(this._hit(e));
    });

    this.canvas.addEventListener('pointerleave', () => {
      if (this._onHover) this._onHover(null);
    });
  }

  onPick(fn) { this._onPick = fn; }
  onHover(fn) { this._onHover = fn; }

  /* ── Camera ─────────────────────────────────────────────────────────── */

  /** Rotate the camera to face a coordinate, preserving current altitude. */
  flyTo(lat, lon, ms = 900) {
    const dist = this.camera.position.length();
    const to = latLonToVec3(lat, lon, dist);
    const from = this.camera.position.clone();
    const t0 = performance.now();
    const ease = (t) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);

    const step = () => {
      const t = Math.min((performance.now() - t0) / ms, 1);
      // Slerp keeps the camera on the sphere of constant radius.
      const v = new THREE.Vector3().copy(from).normalize()
        .lerp(new THREE.Vector3().copy(to).normalize(), ease(t))
        .normalize().multiplyScalar(dist);
      this.camera.position.copy(v);
      this.controls.update();
      if (t < 1) requestAnimationFrame(step);
    };
    step();
  }

  setMarker(lat, lon) {
    const v = latLonToVec3(lat, lon, GLOBE_R * 1.004);
    this.marker.position.copy(v);
    this.marker.lookAt(0, 0, 0);
    this.marker.visible = true;
  }

  clearMarker() { this.marker.visible = false; }

  /** Camera altitude above the mean surface, in kilometres. */
  altitudeKm() {
    return (this.camera.position.length() - GLOBE_R) * (R_MOON_M / 1000);
  }

  setAutoRotate(on) { this.controls.autoRotate = on; }

  setGraticule(on) {
    this._gratOn = on;
    if (this.graticule) this.graticule.visible = on;
  }

  /** Zoom by a multiplicative step, respecting the controls' own limits. */
  zoomBy(factor) {
    const d = this.camera.position.length();
    const nd = THREE.MathUtils.clamp(
      d * factor, this.controls.minDistance, this.controls.maxDistance);
    this.camera.position.multiplyScalar(nd / d);
    this.controls.update();
  }

  /**
   * Ground metres per screen pixel at the sub-camera point — the number a
   * scale bar needs. Derived from the vertical field of view and the camera's
   * height above the surface, so it is exact for the centre of the view and
   * degrades gracefully toward the limb, as any planar scale bar must.
   */
  metresPerPixel() {
    const d = this.camera.position.length();
    const groundHeight =
      2 * Math.max(d - GLOBE_R, 1e-6) * Math.tan((this.camera.fov * DEG) / 2) * R_MOON_M;
    return groundHeight / Math.max(this.canvas.clientHeight, 1);
  }

  reset() {
    this.camera.position.set(0, 0, 3.2);
    this.controls.target.set(0, 0, 0);
    this.controls.update();
  }

  /* ── Loop ───────────────────────────────────────────────────────────── */

  resize() {
    const w = this.canvas.clientWidth || 1, h = this.canvas.clientHeight || 1;
    this.renderer.setSize(w, h, false);
    if (this.labelRenderer) this.labelRenderer.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  start(onFrame) {
    const loop = () => {
      requestAnimationFrame(loop);
      this.controls.update();
      // Keep the pick marker a constant apparent size at any zoom.
      if (this.marker.visible) {
        const s = THREE.MathUtils.clamp(this.camera.position.length() / 3.2, 0.18, 1.6);
        this.marker.scale.setScalar(s);
      }
      this._cullLabels();
      if (onFrame) onFrame();
      this.renderer.render(this.scene, this.camera);
      this.labelRenderer.render(this.scene, this.camera);
    };
    loop();
  }
}
