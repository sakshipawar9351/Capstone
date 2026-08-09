/**
 * Cesium renderer — a drop-in alternative to the Three.js globe.
 *
 * This class deliberately mirrors the public surface of `Globe` in globe.js:
 * same method names, same arguments, same meanings. The application talks to
 * whichever object is active and never asks which one it has. Adding a second
 * renderer that way costs one adapter instead of a branch at every call site,
 * and it keeps the panels, inspector, search and layer logic renderer-agnostic.
 *
 * What differs underneath
 * -----------------------
 * The Three.js globe draws one sphere and drapes a single detail patch over the
 * region in view. Cesium streams 3D Tiles whose mesh subdivides adaptively, so
 * `setTexture` and `setDetailPatch` have nothing to do here — Cesium is already
 * managing exactly what they exist to manage. They are accepted and ignored
 * rather than removed, because the caller should not have to know.
 */

import { api } from './api.js';

const DEG = Math.PI / 180;
const R_MOON_M = 1737400;

const CESIUM_BASE = (v) =>
  `https://cesium.com/downloads/cesiumjs/releases/${v}/Build/Cesium/`;

let cesiumLoaded = null;

/** Inject CesiumJS once. It is a classic script, not an ES module. */
function loadCesium(version) {
  if (cesiumLoaded) return cesiumLoaded;
  cesiumLoaded = new Promise((resolve, reject) => {
    window.CESIUM_BASE_URL = CESIUM_BASE(version);

    const css = document.createElement('link');
    css.rel = 'stylesheet';
    css.href = `${CESIUM_BASE(version)}Widgets/widgets.css`;
    document.head.appendChild(css);

    const s = document.createElement('script');
    s.src = `${CESIUM_BASE(version)}Cesium.js`;
    s.onload = () => resolve(window.Cesium);
    s.onerror = () => reject(new Error('could not load CesiumJS from the CDN'));
    document.head.appendChild(s);
  });
  return cesiumLoaded;
}

const wrapLon = (lon) => ((lon + 180) % 360 + 360) % 360 - 180;
const toEast = (lon) => (lon + 360) % 360;

/** Vertices of a spherical small circle — a true circle on the body. */
function circleOnSphere(C, latDeg, lonDeg, radiusKm) {
  const ang = radiusKm / (R_MOON_M / 1000);
  const lat = latDeg * DEG;
  const lon = wrapLon(lonDeg) * DEG;
  const n = Math.min(96, Math.max(24, Math.round(radiusKm / 3)));
  const sLat = Math.sin(lat), cLat = Math.cos(lat);
  const sA = Math.sin(ang), cA = Math.cos(ang);

  const pts = [];
  for (let i = 0; i <= n; i++) {
    const b = (i / n) * 2 * Math.PI;
    const la = Math.asin(sLat * cA + cLat * sA * Math.cos(b));
    const lo = lon + Math.atan2(Math.sin(b) * sA * cLat, cA - sLat * Math.sin(la));
    pts.push(C.Cartesian3.fromRadians(lo, la));
  }
  return pts;
}


export class CesiumRenderer {
  constructor(container) {
    this.container = container;
    this.ready = false;
    this._labels = [];
    this._craters = [];
    this._classVisible = {};
    this._marker = null;
    this._graticule = [];
    this._gratOn = true;
    this._gratStep = 0;
    this._onPick = null;
    this._onHover = null;
    this._shown = 0;
    this._autoRotate = false;

    // Shim so callers can subscribe to camera movement exactly as they do to
    // OrbitControls in the Three.js globe.
    this.controls = {
      _fns: new Set(),
      addEventListener: (_t, fn) => this.controls._fns.add(fn),
      removeEventListener: (_t, fn) => this.controls._fns.delete(fn),
      get autoRotate() { return this._auto; },
      set autoRotate(v) { this._auto = v; },
      _auto: false,
    };
  }

  async init() {
    const cfg = await api.cesiumConfig();
    const C = await loadCesium(cfg.version);
    this.C = C;
    this.cfg = cfg;

    C.Ion.defaultAccessToken = cfg.token;
    if (!C.Ellipsoid.MOON) {
      throw new Error(`CesiumJS ${C.VERSION} lacks Ellipsoid.MOON — 1.111+ required`);
    }
    // Must precede Viewer construction: a viewer built under the WGS84 default
    // keeps it, and every coordinate would land on an Earth ellipsoid.
    C.Ellipsoid.default = C.Ellipsoid.MOON;

    const viewer = new C.Viewer(this.container, {
      baseLayerPicker: false, geocoder: false, homeButton: false,
      sceneModePicker: false, navigationHelpButton: false, animation: false,
      timeline: false, fullscreenButton: false, infoBox: false,
      selectionIndicator: false, baseLayer: false,
      terrainProvider: new C.EllipsoidTerrainProvider(),
      requestRenderMode: false,
      msaaSamples: 4,
    });
    this.viewer = viewer;
    const scene = viewer.scene;

    // Unlit, per the brief: no terminator, no dark limb, every side legible.
    // Guarded because Cesium does not construct all of these under a
    // non-WGS84 ellipsoid.
    const set = (o, k, v) => { if (o != null) { try { o[k] = v; } catch {} } };
    set(scene.globe, 'show', false);
    set(scene.globe, 'enableLighting', false);
    set(scene.globe, 'showGroundAtmosphere', false);
    set(scene.skyAtmosphere, 'show', false);
    set(scene.skyBox, 'show', false);
    set(scene.sun, 'show', false);
    set(scene.moon, 'show', false);
    set(scene.fog, 'enabled', false);
    scene.backgroundColor = C.Color.fromCssColorString('#05070a');
    scene.light = new C.DirectionalLight({
      direction: new C.Cartesian3(1, 0, 0), intensity: 0.0,
    });

    // The camera controller reads distance-to-surface from scene.globe, which
    // is hidden here, so the bounds must be supplied directly or zoom is dead.
    const ctrl = scene.screenSpaceCameraController;
    ctrl.minimumZoomDistance = 300;
    ctrl.maximumZoomDistance = 30_000_000;
    ctrl.enableCollisionDetection = false;
    ctrl.zoomEventTypes = [C.CameraEventType.PINCH, C.CameraEventType.RIGHT_DRAG];
    // Free rotation across the poles; Cesium pins this to +Z by default.
    viewer.camera.constrainedAxis = undefined;

    this._installWheel();

    const tileset = await C.Cesium3DTileset.fromIonAssetId(cfg.asset, {
      maximumScreenSpaceError: 4,
      preferLeaves: true,
      cacheBytes: 1024 * 1024 * 1024,
      maximumCacheOverflowBytes: 512 * 1024 * 1024,
      dynamicScreenSpaceError: false,
      skipLevelOfDetail: false,
      enableDebugWireframe: true,
    });
    scene.primitives.add(tileset);
    this.tileset = tileset;
    tileset.imageBasedLighting.imageBasedLightingFactor = new C.Cartesian2(0, 0);

    this._bindInput();
    this._buildGraticule(30);
    this.reset();

    viewer.camera.percentageChanged = 0.15;
    viewer.camera.changed.addEventListener(() => {
      for (const fn of this.controls._fns) fn();
    });

    this.ready = true;
    return this;
  }

  /* ── Zoom: trackpad-aware ─────────────────────────────────────────── */

  _installWheel() {
    const C = this.C;
    this.viewer.canvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      let d = e.deltaY;
      if (e.deltaMode === 1) d *= 16;
      else if (e.deltaMode === 2) d *= 100;
      // Pinch arrives as ctrl+wheel and is a larger deliberate gesture than a
      // scroll flick; trackpad deltas are ~1-4 where a mouse detent is ~100.
      const gain = e.ctrlKey ? 0.022 : 0.0065;
      const frac = Math.max(-0.55, Math.min(0.55, -d * gain));
      if (!frac) return;
      const h = this.viewer.camera.positionCartographic.height;
      const step = Math.max(Math.abs(h * frac), 25) * Math.sign(frac);
      if (step > 0) this.viewer.camera.zoomIn(step);
      else this.viewer.camera.zoomOut(-step);
    }, { passive: false });

    for (const ev of ['gesturestart', 'gesturechange', 'gestureend']) {
      this.viewer.canvas.addEventListener(ev, (e) => e.preventDefault(),
        { passive: false });
    }
  }

  /* ── Input ────────────────────────────────────────────────────────── */

  _bindInput() {
    const C = this.C;
    const h = new C.ScreenSpaceEventHandler(this.viewer.scene.canvas);

    h.setInputAction((m) => {
      if (!this._onHover) return;
      const p = this.viewer.scene.pickPosition(m.endPosition);
      this._onHover(C.defined(p) ? this._toLatLon(p) : null);
    }, C.ScreenSpaceEventType.MOUSE_MOVE);

    h.setInputAction((click) => {
      const p = this.viewer.scene.pickPosition(click.position);
      if (!C.defined(p) || !this._onPick) return;
      this._onPick(this._toLatLon(p));
    }, C.ScreenSpaceEventType.LEFT_CLICK);
  }

  _toLatLon(cartesian) {
    const C = this.C;
    const c = C.Cartographic.fromCartesian(
      cartesian, C.Ellipsoid.default, new C.Cartographic());
    return { lat: C.Math.toDegrees(c.latitude), lon: toEast(C.Math.toDegrees(c.longitude)) };
  }

  onPick(fn) { this._onPick = fn; }
  onHover(fn) { this._onHover = fn; }

  /* ── Camera ───────────────────────────────────────────────────────── */

  reset() {
    this.viewer.camera.flyTo({
      destination: this.C.Cartesian3.fromDegrees(0, 0, 6_000_000),
      duration: 1.2,
      complete: () => { this.viewer.camera.constrainedAxis = undefined; },
    });
  }

  flyTo(lat, lon, heightKm) {
    const h = heightKm ? heightKm * 1000 : 250_000;
    this.viewer.camera.flyTo({
      destination: this.C.Cartesian3.fromDegrees(wrapLon(lon), lat, h),
      duration: 1.6,
      // flyTo restores the constrained axis on arrival, re-locking pole crossing.
      complete: () => { this.viewer.camera.constrainedAxis = undefined; },
    });
  }

  /** Straight-down view of a pole. */
  flyToPole(north) {
    const C = this.C;
    this.viewer.camera.flyTo({
      destination: C.Cartesian3.fromDegrees(0, north ? 89.9 : -89.9, 900_000),
      orientation: { heading: 0, pitch: C.Math.toRadians(-90), roll: 0 },
      duration: 2.0,
      complete: () => { this.viewer.camera.constrainedAxis = undefined; },
    });
  }

  altitudeKm() {
    return this.viewer.camera.positionCartographic.height / 1000;
  }

  metresPerPixel() {
    const h = Math.max(this.viewer.camera.positionCartographic.height, 1);
    const fov = this.viewer.camera.frustum.fovy ?? (60 * DEG);
    const ground = 2 * h * Math.tan(fov / 2);
    return ground / Math.max(this.viewer.canvas.clientHeight, 1);
  }

  zoomBy(factor) {
    const h = this.viewer.camera.positionCartographic.height;
    // factor < 1 means "closer", matching the Three.js globe's convention.
    const step = h * (1 - factor);
    if (step > 0) this.viewer.camera.zoomIn(step);
    else this.viewer.camera.zoomOut(-step);
  }

  visibleRegion() {
    const c = this.viewer.camera.positionCartographic;
    const lat = this.C.Math.toDegrees(c.latitude);
    const lon = toEast(this.C.Math.toDegrees(c.longitude));
    const d = (c.height + R_MOON_M) / R_MOON_M;
    const horizon = Math.acos(Math.min(1 / d, 1));
    const half = Math.min(horizon * 1.35 / DEG, 90);
    const cosLat = Math.max(Math.cos(lat * DEG), 0.08);
    const lonHalf = Math.min(half / cosLat, 180);
    return {
      centre: { lat, lon },
      south: Math.max(-90, lat - half),
      north: Math.min(90, lat + half),
      west: lon - lonHalf,
      east: lon + lonHalf,
      mPerPx: this.metresPerPixel(),
      full: (half * 2) >= 179 || lonHalf >= 179,
    };
  }

  setAutoRotate(on) {
    this._autoRotate = on;
    this.controls.autoRotate = on;
  }

  /* ── Overlays ─────────────────────────────────────────────────────── */

  setLabels(features, { onClick } = {}) {
    const C = this.C;
    this.clearLabels();
    for (const f of features) {
      const e = this.viewer.entities.add({
        position: C.Cartesian3.fromDegrees(wrapLon(f.lon), f.lat),
        label: {
          text: f.name,
          font: '500 13px system-ui, sans-serif',
          fillColor: C.Color.fromCssColorString(f.colour || '#f2f5fa'),
          outlineColor: C.Color.BLACK,
          outlineWidth: 3,
          style: C.LabelStyle.FILL_AND_OUTLINE,
          // Clamped to the tileset: a label at a fixed height sits below any
          // terrain higher than it and gets depth-culled.
          heightReference: C.HeightReference.CLAMP_TO_3D_TILE,
          verticalOrigin: C.VerticalOrigin.BOTTOM,
          pixelOffset: new C.Cartesian2(0, -6),
          disableDepthTestDistance: 0,
          scaleByDistance: new C.NearFarScalar(1e5, 1.15, 2.5e7, 0.5),
          translucencyByDistance: new C.NearFarScalar(1e5, 1.0, 2.8e7, 0.85),
        },
      });
      e.__feature = f;
      this._labels.push(e);
    }
    this._shown = features.length;
    this._labelClick = onClick || null;
    return this._labels.length;
  }

  clearLabels() {
    for (const e of this._labels) this.viewer.entities.remove(e);
    this._labels = [];
    this._shown = 0;
  }

  setLabelsVisible(on) {
    for (const e of this._labels) e.show = on;
  }

  shownLabelCount() { return this._shown; }

  setCraters(craters, colours = {}) {
    const C = this.C;
    this.clearCraters();
    for (const k of craters) {
      const col = colours[k.class_key] || k.colour || '#8ecae6';
      const e = this.viewer.entities.add({
        polyline: {
          positions: circleOnSphere(C, k.lat, k.lon, k.diameter_km / 2),
          width: 2,
          material: C.Color.fromCssColorString(col).withAlpha(0.85),
          clampToGround: true,
        },
      });
      e.__crater = k;
      e.__cls = k.class_key;
      this._craters.push(e);
    }
    for (const [key, on] of Object.entries(this._classVisible)) {
      this.setClassVisible(key, on);
    }
    return this._craters.length;
  }

  clearCraters() {
    for (const e of this._craters) this.viewer.entities.remove(e);
    this._craters = [];
  }

  setClassVisible(key, on) {
    this._classVisible[key] = on;
    for (const e of this._craters) {
      if (e.__cls === key) e.show = on;
    }
  }

  setMarker(lat, lon) {
    const C = this.C;
    this.clearMarker();
    this._marker = this.viewer.entities.add({
      position: C.Cartesian3.fromDegrees(wrapLon(lon), lat),
      point: {
        pixelSize: 11,
        color: C.Color.fromCssColorString('#4da3ff'),
        outlineColor: C.Color.WHITE,
        outlineWidth: 2,
        heightReference: C.HeightReference.CLAMP_TO_3D_TILE,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
    });
  }

  clearMarker() {
    if (this._marker) this.viewer.entities.remove(this._marker);
    this._marker = null;
  }

  /* ── Graticule ────────────────────────────────────────────────────── */

  _buildGraticule(stepDeg) {
    const C = this.C;
    for (const e of this._graticule) this.viewer.entities.remove(e);
    this._graticule = [];
    this._gratStep = stepDeg;

    const seg = Math.max(stepDeg / 12, 0.05);
    const mk = (pos, major) => this.viewer.entities.add({
      polyline: {
        positions: pos, width: major ? 1.6 : 1,
        material: C.Color.fromCssColorString('#4da3ff')
          .withAlpha(major ? 0.34 : 0.16),
        arcType: C.ArcType.NONE,
      },
    });

    for (let lat = -90 + stepDeg; lat <= 90 - stepDeg + 1e-9; lat += stepDeg) {
      const pts = [];
      for (let lon = 0; lon <= 360; lon += seg) {
        pts.push(C.Cartesian3.fromDegrees(wrapLon(lon), lat, 1200));
      }
      this._graticule.push(mk(pts, Math.abs(lat) < 1e-9));
    }
    for (let lon = 0; lon < 360 - 1e-9; lon += stepDeg) {
      const pts = [];
      for (let lat = -89.5; lat <= 89.5; lat += seg) {
        pts.push(C.Cartesian3.fromDegrees(wrapLon(lon), lat, 1200));
      }
      this._graticule.push(mk(pts, Math.abs(lon) < 1e-9 || Math.abs(lon - 180) < 1e-9));
    }
    for (const e of this._graticule) e.show = this._gratOn;
  }

  _stepFor(spanDeg) {
    const target = spanDeg / 8;
    for (const s of [30, 20, 10, 5, 2, 1, 0.5, 0.2, 0.1]) {
      if (s <= target) return s;
    }
    return 0.1;
  }

  updateGraticule() {
    if (!this.ready) return;
    const c = this.viewer.camera.positionCartographic;
    const d = (c.height + R_MOON_M) / R_MOON_M;
    const span = Math.min(2 * Math.acos(Math.min(1 / d, 1)) / DEG, 180);
    const step = this._stepFor(span);
    if (step !== this._gratStep) this._buildGraticule(step);
  }

  setGraticule(on) {
    this._gratOn = on;
    for (const e of this._graticule) e.show = on;
  }

  /* ── No-ops: Cesium manages its own imagery and level of detail ───── */

  async setTexture() { /* the tileset carries baked imagery */ }
  async setDetailPatch() { /* 3D Tiles refine adaptively */ }
  clearDetailPatch() { }

  /* ── Lifecycle ────────────────────────────────────────────────────── */

  start(onFrame) {
    this.viewer.scene.postRender.addEventListener(() => {
      if (this._autoRotate) {
        this.viewer.camera.rotate(this.C.Cartesian3.UNIT_Z, -0.0008);
      }
      if (onFrame) onFrame();
    });
  }

  resize() { /* Cesium tracks its container automatically */ }

  destroy() {
    try {
      this.clearLabels();
      this.clearCraters();
      this.clearMarker();
      this.viewer?.destroy();
    } catch { /* already gone */ }
    this.viewer = null;
    this.ready = false;
  }

  tileStats() {
    if (!this.tileset) return null;
    const s = this.tileset.statistics;
    let deepest = 0, finest = Infinity;
    try {
      for (const t of this.tileset._selectedTiles ?? []) {
        if (t._depth > deepest) deepest = t._depth;
        const ge = t.geometricError;
        if (Number.isFinite(ge) && ge > 0 && ge < finest) finest = ge;
      }
    } catch { /* internal fields */ }
    return {
      depth: deepest,
      geometricError: Number.isFinite(finest) ? finest : null,
      tiles: s.numberOfTilesTotal,
      memoryMB: this.tileset.totalMemoryUsageInBytes / 1048576,
      pending: s.numberOfPendingRequests,
    };
  }
}
