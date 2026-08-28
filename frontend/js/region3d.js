/**
 * The selected region as a surface you can look across.
 *
 * Every other panel on this page is an overhead picture, and overhead is the
 * one view that hides what a traverse is about: whether the ground goes up. A
 * 40 deg scarp and a 4 deg ramp can be the same amber on a slope map. Seen
 * edge-on they are obviously not the same thing.
 *
 * What is drawn is the region's own elevation grid — the same array the hazard
 * and cost maps came from, meshed server-side so the picture and the numbers
 * cannot describe slightly different ground.
 *
 * Two things this view refuses to do
 * ----------------------------------
 * It does not light the Moon. The brief rules out illumination effects, and
 * they would be actively misleading here: a shadow cast across a crater floor
 * is indistinguishable from dark regolith, and this page is where someone
 * decides whether that floor is drivable. Shading comes from the surface
 * normal alone — a slope cue, not a sun.
 *
 * It does not hide the vertical exaggeration. Lunar relief is ~20 km on a
 * 1737 km radius; at true scale a crater is invisible, so exaggeration is
 * unavoidable and every planetary tool uses it. What is avoidable is letting a
 * reader forget: the factor is on screen, it starts where the relief is honest
 * for the region's own width, and 1x is always one click away.
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { api } from './api.js';

export class RegionSurface {
  constructor(canvas) {
    this.canvas = canvas;
    this.renderer = new THREE.WebGLRenderer({
      canvas, antialias: true, alpha: false,
    });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0d1015);

    this.camera = new THREE.PerspectiveCamera(45, 1, 1, 5e7);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    // Below the horizon there is nothing but the underside of a heightfield,
    // and it is easy to end up there by accident and think the view broke.
    this.controls.maxPolarAngle = Math.PI * 0.495;

    this.mesh = null;
    this.exaggeration = 1;
    this.meta = null;
    this._raf = null;

    this._onResize = () => this.resize();
    addEventListener('resize', this._onResize);
    this._tick = () => {
      this._raf = requestAnimationFrame(this._tick);
      this.controls.update();
      this.renderer.render(this.scene, this.camera);
    };
  }

  resize() {
    const w = this.canvas.clientWidth || 1;
    const h = this.canvas.clientHeight || 1;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  /** Load a region's surface. Returns the mesh metadata for the caption. */
  async load(bounds, { source, finest, maxVerts } = {}) {
    const m = await api.aoiMesh({ ...bounds, source, finest, maxVerts });
    this.meta = m;

    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(m.positions, 3));
    g.setAttribute('normal', new THREE.BufferAttribute(m.normals, 3));
    g.setIndex(new THREE.BufferAttribute(m.indices, 1));

    // UVs so a drape lands where the ground is. The grid runs north-west first
    // and row-major, matching how the mosaic image is laid out, so v is
    // flipped rather than u.
    const uv = new Float32Array(m.rows * m.cols * 2);
    for (let r = 0, i = 0; r < m.rows; r++) {
      for (let c = 0; c < m.cols; c++, i += 2) {
        uv[i] = c / (m.cols - 1);
        uv[i + 1] = 1 - r / (m.rows - 1);
      }
    }
    g.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
    g.computeBoundingSphere();

    if (this.mesh) {
      this.mesh.geometry.dispose();
      this.scene.remove(this.mesh);
    }
    // MeshBasicMaterial takes no light at all, which would render a flat
    // silhouette. MeshNormalMaterial-style shading from the normal is what
    // gives relief without inventing a sun, so a hemisphere ambient is used:
    // it has no direction and casts nothing, it only brightens upward faces.
    this.material = new THREE.MeshLambertMaterial({
      color: 0xb8bec8, side: THREE.DoubleSide,
    });
    this.mesh = new THREE.Mesh(g, this.material);
    this.scene.add(this.mesh);

    if (!this._lit) {
      this.scene.add(new THREE.HemisphereLight(0xffffff, 0x2a3038, 2.6));
      this._lit = true;
    }

    this.setExaggeration(this.suggestedExaggeration());
    this.frame();
    if (!this._raf) this._tick();
    this.resize();
    return m;
  }

  /**
   * A starting factor that makes the region's relief legible without lying.
   *
   * Aim for the relief to occupy about a sixth of the region's width on
   * screen. A 300 m ridge across 2.5 km needs roughly 1.4x; the same ridge
   * across 100 km needs 55x, and that is exactly the case where a reader most
   * needs to be told the factor.
   */
  suggestedExaggeration() {
    const m = this.meta;
    if (!m || !(m.reliefM > 0)) return 1;
    const width = Math.max(m.extentM.x, m.extentM.y);
    return Math.max(1, Math.min(50, Math.round((width / 6) / m.reliefM)));
  }

  setExaggeration(f) {
    this.exaggeration = f;
    if (this.mesh) this.mesh.scale.z = f;
  }

  /** Drape an image over the surface, or clear it back to plain shading. */
  setDrape(url) {
    if (!this.material) return;
    if (this._tex) { this._tex.dispose(); this._tex = null; }
    if (!url) {
      this.material.map = null;
      this.material.color.setHex(0xb8bec8);
      this.material.needsUpdate = true;
      return;
    }
    const tex = new THREE.TextureLoader().load(url, () => {
      this.material.needsUpdate = true;
    });
    tex.colorSpace = THREE.SRGBColorSpace;
    // One texel per analysed cell: the drape is the same grid as the terrain,
    // so smoothing it would blur a hazard boundary across ground it does not
    // apply to.
    tex.magFilter = THREE.NearestFilter;
    tex.generateMipmaps = true;
    this._tex = tex;
    this.material.map = tex;
    // White, so the texture's own colours survive rather than being tinted.
    this.material.color.setHex(0xffffff);
    this.material.needsUpdate = true;
  }

  /**
   * Put the camera where the whole region is in view, looking from the SW.
   *
   * About 38 deg above the horizon: high enough to read the layout of the
   * ground, low enough that relief still reads as relief. Directly overhead
   * would just reproduce the maps below, which is the one thing this view is
   * not for.
   */
  frame() {
    const m = this.meta;
    if (!m) return;
    const w = Math.max(m.extentM.x, m.extentM.y);
    const d = w * 0.95;
    const el = 38 * Math.PI / 180;
    this.controls.target.set(0, 0, 0);
    this.camera.up.set(0, 0, 1);
    this.camera.position.set(
      -d * Math.cos(el) * 0.707, -d * Math.cos(el) * 0.707, d * Math.sin(el));
    this.camera.near = w / 1000;
    this.camera.far = w * 20;
    this.camera.updateProjectionMatrix();
    this.controls.update();
  }

  dispose() {
    if (this._raf) cancelAnimationFrame(this._raf);
    this._raf = null;
    removeEventListener('resize', this._onResize);
    this.controls.dispose();
    if (this.mesh) this.mesh.geometry.dispose();
    if (this._tex) this._tex.dispose();
    this.material?.dispose();
    this.renderer.dispose();
  }
}
