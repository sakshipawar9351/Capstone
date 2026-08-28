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
    this._labelsOn = true;
    this._occluder = null;
    this._route = [];
    this._pins = [];
    this._aoiBox = [];

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
    // Earth's default is a blue base colour; an unloaded Moon tile must
    // not flash blue.
    set(scene.globe, 'baseColor', C.Color.fromCssColorString('#0d1015'));
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

  /**
   * Selenographic coordinate under a pointer event, or null off the limb.
   *
   * `pickPosition` reads the depth buffer, which is what the tileset writes
   * to, so this follows the terrain rather than an idealised sphere. Falls
   * back to an ellipsoid ray where no tile has been drawn yet — otherwise a
   * region could not be started over ground that is still loading.
   */
  pickLatLon(ev) {
    const C = this.C;
    const rect = this.viewer.scene.canvas.getBoundingClientRect();
    const pos = new C.Cartesian2(ev.clientX - rect.left, ev.clientY - rect.top);
    let p = this.viewer.scene.pickPosition(pos);
    if (!C.defined(p)) {
      p = this.viewer.camera.pickEllipsoid(pos, C.Ellipsoid.default);
    }
    return C.defined(p) ? this._toLatLon(p) : null;
  }

  get inputElement() { return this.viewer.scene.canvas; }

  setInteractive(on) {
    const c = this.viewer.scene.screenSpaceCameraController;
    c.enableRotate = on;
    c.enableTranslate = on;
    c.enableTilt = on;
    c.enableLook = on;
    // Zoom is left alone: it is wheel-driven, so it never competes with a drag
    // and staying able to zoom while framing a region is useful.
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
      const pos = C.Cartesian3.fromDegrees(wrapLon(f.lon), f.lat);
      const e = this.viewer.entities.add({
        position: pos,
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
      // Cached so the per-frame horizon test never re-reads the property bag.
      e.__pos = pos;
      this._labels.push(e);
    }
    this._shown = features.length;
    this._labelClick = onClick || null;
    this._cullLabels();
    return this._labels.length;
  }

  /**
   * Hide labels on the far side of the Moon.
   *
   * The Three.js globe does this with a dot-product test against the view
   * direction; Cesium needs it too and does not get it for free. Normally the
   * globe surface would depth-occlude a label behind it, but `scene.globe.show`
   * is false here — the visible body is a 3D Tileset — so nothing writes depth
   * where tiles have not yet refined. Without this, a name on the hemisphere
   * facing away stays drawn, and reads as text pinned to the screen rather than
   * to the ground.
   *
   * `EllipsoidalOccluder` answers exactly the right question: is this point on
   * the ellipsoid visible from the camera, or over the horizon? Cost is one
   * test per label, and the label count is capped well below a hundred.
   */
  _cullLabels() {
    if (!this._labels.length || !this.viewer) return;
    const C = this.C;
    if (!this._occluder) {
      this._occluder = new C.EllipsoidalOccluder(
        C.Ellipsoid.default, this.viewer.scene.camera.positionWC);
    }
    this._occluder.cameraPosition = this.viewer.scene.camera.positionWC;

    let shown = 0;
    for (const e of this._labels) {
      const visible = this._labelsOn && this._occluder.isPointVisible(e.__pos);
      e.show = visible;
      if (visible) shown++;
    }
    this._shown = shown;
  }

  clearLabels() {
    for (const e of this._labels) this.viewer.entities.remove(e);
    this._labels = [];
    this._shown = 0;
  }

  setLabelsVisible(on) {
    // Recorded rather than applied directly, so the horizon test cannot switch
    // a label back on after the user has turned labels off.
    this._labelsOn = on;
    if (!on) {
      for (const e of this._labels) e.show = false;
      this._shown = 0;
    } else {
      this._cullLabels();
    }
  }

  shownLabelCount() { return this._shown; }

  /** Cesium owns no sibling DOM layer; its container is hidden wholesale. */
  setOverlayVisible() { }

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

  /* ── Planning overlays ─────────────────────────────────────────────── */

  /**
   * Draw a planned route, coloured along its length by per-sample risk.
   *
   * Cesium has no per-vertex colour on a clamped polyline, so the route is cut
   * into short runs of near-constant risk and each run drawn separately. Runs
   * rather than one entity per sample: a 2,000-sample route would otherwise
   * become 2,000 entities and the viewer would crawl.
   */
  setRoute(latlons, risk = null) {
    const C = this.C;
    this.clearRoute();
    if (!latlons || latlons.length < 2) return 0;

    const band = (r) => (r == null ? 0 : Math.min(4, Math.floor(r * 5)));
    const colours = ['#35c48a', '#9ccc4f', '#e9c46a', '#e07a5a', '#c1352b'];

    let runStart = 0;
    let runBand = band(risk ? risk[0] : null);
    const flush = (end) => {
      const pts = [];
      for (let i = runStart; i <= end; i++) {
        pts.push(wrapLon(latlons[i][1]), latlons[i][0]);
      }
      if (pts.length < 4) return;
      this._route.push(this.viewer.entities.add({
        polyline: {
          positions: C.Cartesian3.fromDegreesArray(pts),
          width: 4,
          material: C.Color.fromCssColorString(colours[runBand]).withAlpha(0.95),
          clampToGround: true,
        },
      }));
    };

    for (let i = 1; i < latlons.length; i++) {
      const b = band(risk ? risk[i] : null);
      if (b !== runBand) {
        flush(i);                     // overlap by one so runs meet
        runStart = i;
        runBand = b;
      }
    }
    flush(latlons.length - 1);
    return this._route.length;
  }

  clearRoute() {
    for (const e of this._route) this.viewer.entities.remove(e);
    this._route = [];
  }

  setPins(start, goal) {
    const C = this.C;
    this.clearPins();
    const mk = (p, colour, label) => {
      if (!p) return;
      this._pins.push(this.viewer.entities.add({
        position: C.Cartesian3.fromDegrees(wrapLon(p.lon), p.lat),
        point: {
          pixelSize: 13,
          color: C.Color.fromCssColorString(colour),
          outlineColor: C.Color.WHITE,
          outlineWidth: 2,
          heightReference: C.HeightReference.CLAMP_TO_3D_TILE,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
        label: {
          text: label,
          font: '600 12px system-ui, sans-serif',
          fillColor: C.Color.WHITE,
          outlineColor: C.Color.BLACK,
          outlineWidth: 3,
          style: C.LabelStyle.FILL_AND_OUTLINE,
          pixelOffset: new C.Cartesian2(0, -18),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
      }));
    };
    mk(start, '#35c48a', 'START');
    mk(goal, '#e0503a', 'GOAL');
  }

  clearPins() {
    for (const e of this._pins) this.viewer.entities.remove(e);
    this._pins = [];
  }

  /** Outline the selected region, following the ground rather than chording it. */
  setAOIBox(bounds) {
    const C = this.C;
    this.clearAOIBox();
    if (!bounds) return;
    const { south, north, west, east } = bounds;
    const span = ((east - west) % 360 + 360) % 360 || 360;
    const N = 128;

    // Perimeter walked in small steps, not four corners joined: a lat/lon box
    // is not a rectangle on a sphere, and a four-segment outline cuts across
    // the ground it claims to enclose.
    const ring = [];
    for (let i = 0; i <= N; i++) ring.push(wrapLon(west + span * i / N), south);
    for (let i = 0; i <= N; i++) {
      ring.push(wrapLon(west + span), south + (north - south) * i / N);
    }
    for (let i = N; i >= 0; i--) ring.push(wrapLon(west + span * i / N), north);
    for (let i = N; i >= 0; i--) {
      ring.push(wrapLon(west), south + (north - south) * i / N);
    }
    const positions = C.Cartesian3.fromDegreesArray(ring);

    // Tinted face first, so the region reads as an area rather than a wire.
    this._aoiBox.push(this.viewer.entities.add({
      polygon: {
        hierarchy: new C.PolygonHierarchy(positions),
        material: C.Color.fromCssColorString('#4da3ff').withAlpha(0.16),
        classificationType: C.ClassificationType.CESIUM_3D_TILE,
      },
    }));

    // Outlined polyline: a dark casing under a bright core, so the edge holds
    // against both the bright highlands and the shadowed floors.
    this._aoiBox.push(this.viewer.entities.add({
      polyline: {
        positions, width: 7, clampToGround: true,
        material: C.Color.WHITE.withAlpha(0.55),
      },
    }));
    this._aoiBox.push(this.viewer.entities.add({
      polyline: {
        positions, width: 4, clampToGround: true,
        material: C.Color.BLACK,
      },
    }));

    // Corner pips: when the region is small on screen its four edges merge
    // into a single mark, and the extent stops being readable without them.
    for (const [la, lo] of [[south, west], [south, west + span],
                            [north, west], [north, west + span]]) {
      this._aoiBox.push(this.viewer.entities.add({
        position: C.Cartesian3.fromDegrees(wrapLon(lo), la),
        point: {
          pixelSize: 8,
          color: C.Color.BLACK,
          outlineColor: C.Color.WHITE,
          outlineWidth: 2,
          heightReference: C.HeightReference.CLAMP_TO_3D_TILE,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
      }));
    }
  }

  clearAOIBox() {
    for (const e of this._aoiBox) this.viewer.entities.remove(e);
    this._aoiBox = [];
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

  /* ── Surface: relief or resolution, one renderer ──────────────────── */

  /**
   * Choose what draws the Moon's surface.
   *
   * Cesium has always had a globe here — it was simply hidden, because the
   * ion 3D Tileset draws the surface instead. That tileset carries its imagery
   * baked in at 83 m and cannot be re-textured, which is why zooming past
   * roughly 80 m/px went soft and why a finer basemap had no effect on this
   * view. The globe underneath can take any imagery layer we serve.
   *
   * So the two are alternatives rather than layers:
   *
   *   relief    3D Tiles, real topography, imagery fixed at 83 m
   *   imagery   sphere, no relief, but our own basemap to 20.8 m
   *
   * They cannot both draw at once. The tileset carries genuine relief of some
   * kilometres while the globe is a sphere at exactly 1737.4 km, so showing
   * both puts the sphere through every basin floor and buries it under every
   * highland. A blend would need the tileset re-textured through a custom
   * shader, which is a different piece of work.
   */
  /**
   * Terrain built from this project's own DEMs, at the correct datum.
   *
   * `CustomHeightmapTerrainProvider` asks for a lattice of heights per tile
   * and builds the mesh itself, so the surface can come from the same
   * products every measurement in this project comes from. The server picks
   * the finest local source per tile, which is why one globe carries 2 m over
   * the Apollo 15 NAC strip, 10 m near the south pole and 473.8 m elsewhere
   * with no seam handling here: every tile asks the same question.
   *
   * Coarser than the ion tileset almost everywhere, and correct. The tileset
   * was measured at +1,789 m against LOLA; this is LOLA.
   */
  async _scienceTerrain() {
    const C = this.C;
    if (this._sciTerrain) return this._sciTerrain;
    const tilingScheme = new C.GeographicTilingScheme({
      ellipsoid: C.Ellipsoid.MOON,
    });
    this._sciTerrain = new C.CustomHeightmapTerrainProvider({
      width: 65, height: 65,
      tilingScheme,
      ellipsoid: C.Ellipsoid.MOON,
      callback: async (x, y, level) => {
        try {
          const r = await fetch(
            `/api/v1/terrain/tile?x=${x}&y=${y}&level=${level}&width=65&height=65`);
          // Returning undefined tells Cesium this tile has nothing and stops
          // it refining further here, which is the honest answer where no
          // product covers the ground.
          if (!r.ok) return undefined;
          return new Float32Array(await r.arrayBuffer());
        } catch {
          return undefined;
        }
      },
    });
    return this._sciTerrain;
  }

  async setSurface(mode = 'relief') {
    const known = ['relief', 'imagery', 'science'];
    this.surfaceMode = known.includes(mode) ? mode : 'relief';
    const scene = this.viewer?.scene;
    if (!scene) return;
    const onGlobe = this.surfaceMode !== 'relief';
    if (onGlobe && !this._imageryLayer) await this.setBasemap(this._basemapKey);

    // Terrain is a property of the globe, so it only changes when the globe is
    // what draws. Switching back to relief leaves the provider in place rather
    // than tearing it down, so returning to science mode does not re-fetch
    // every tile.
    if (this.surfaceMode === 'science') {
      this.viewer.terrainProvider = await this._scienceTerrain();
    } else if (onGlobe) {
      this.viewer.terrainProvider = new this.C.EllipsoidTerrainProvider();
    }

    try { scene.globe.show = onGlobe; } catch { /* older builds */ }
    if (this.tileset) this.tileset.show = !onGlobe;
    scene.requestRender?.();
  }

  /**
   * Point the globe at one of our own basemap layers.
   *
   * The proxy at `/api/v1/tiles/{layer}/{z}/{y}/{x}` already publishes the
   * WMTS layout Cesium's GeographicTilingScheme expects — 2^(z+1) columns by
   * 2^z rows with y counted from the north — so the tiles map across with no
   * adapter and no reprojection. `maximumLevel` matters: past a layer's own
   * depth the server would answer 404 for every tile and the globe would go
   * black rather than simply stop sharpening.
   */
  async setBasemap(key = 'kaguya_tc', maxZoom = 10) {
    const C = this.C;
    if (!C || !this.viewer) return;
    this._basemapKey = key;
    const layers = this.viewer.imageryLayers;
    if (this._imageryLayer) {
      layers.remove(this._imageryLayer, true);
      this._imageryLayer = null;
    }
    const provider = new C.UrlTemplateImageryProvider({
      url: `/api/v1/tiles/${key}/{z}/{y}/{x}`,
      tilingScheme: new C.GeographicTilingScheme({ ellipsoid: C.Ellipsoid.MOON }),
      tileWidth: 256, tileHeight: 256,
      minimumLevel: 0, maximumLevel: maxZoom,
      credit: 'NASA Trek',
    });
    this._imageryLayer = layers.addImageryProvider(provider);
    this.viewer.scene.requestRender?.();
  }

  /* ── No-ops under the tileset; real under the globe ───────────────── */

  async setTexture() { /* the tileset carries baked imagery; see setBasemap */ }
  async setDetailPatch() { /* 3D Tiles refine adaptively */ }
  clearDetailPatch() { }

  /* ── Lifecycle ────────────────────────────────────────────────────── */

  start(onFrame) {
    // preRender, not postRender: a label hidden after the frame is drawn is
    // hidden one frame too late, which shows as flicker while dragging.
    this.viewer.scene.preRender.addEventListener(() => this._cullLabels());

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
      this.clearRoute();
      this.clearPins();
      this.clearAOIBox();
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
