/**
 * LunarSerpent — application shell.
 *
 * Wires the globe to the analysis API, and owns all interface state.
 *
 * State is held in one plain object with a single `render()` that reads it.
 * That is deliberate: with one source of truth and one place that touches the
 * DOM, the layer panel, the inspector and the globe can never disagree about
 * what is currently displayed.
 */

import { Globe, vec3ToLatLon } from './globe.js';
import { api, fmtCoord, fmtLen, fmtArea, fmtInt } from './api.js';

const $ = (id) => document.getElementById(id);

/* ── State ──────────────────────────────────────────────────────────────── */

const state = {
  basemap: 'wac',
  basemaps: [],
  classes: [],
  classVisible: {},          // classKey -> bool
  showCraters: true,
  minDiameterKm: 20,
  maxDrawn: 800,
  craterStats: { drawn: 0, matching: 0 },
  selection: null,           // { lat, lon }
  busy: false,

  showNames: true,
  // A low floor lets the scale rule drive label selection; raising it is how
  // the user declutters, not how the map decides what matters.
  nameMinDiameterKm: 2,
  maxLabels: 60,

  // Vertical exaggeration for the relief patch. Lunar topography spans ~20 km
  // on a 1737 km radius, so at 1x it is invisible; the factor is always shown
  // because exaggerated relief is a rendering choice, not a measurement.
  //
  // 3x is the default because it makes a crater unmistakably three-dimensional
  // while keeping its proportions readable: Tycho's true aspect is about 1:19
  // (85 km wide, 4.5 km deep) and 3x renders it near 1:6, which still looks
  // like a crater. Past ~12x the surface reads as spikes rather than terrain.
  relief: 3,
  reliefStats: null,
  kinds: [],
  kindVisible: {},

  //: Which renderer is live — 'three' or 'cesium'. Both implement the same
  //: interface, so nothing downstream needs to consult this except the tile
  //: readout, which only one of them can populate.
  renderer: 'three',
};

/** The renderer the application is currently talking to. */
let globe;

/** The Three.js globe, kept alive across switches so it need not rebuild. */
let three = null;

/** The Cesium renderer, constructed on first use rather than at startup. */
let cesium = null;

/**
 * Traverse-planning state.
 *
 * Declared here rather than beside its functions, for the same reason `three`
 * and `cesium` are: `boot()` touches it long before those functions appear in
 * the file, and a `const` referenced above its declaration is a temporal dead
 * zone away from taking the whole application down. It happens to be safe at
 * runtime today — `boot()` is invoked last — but that is a property of one
 * call site, not of the code.
 */
const plan = {
  start: null,
  goal: null,
  picking: null,        // 'start' | 'goal' | null
  dragging: false,      // region rectangle being drawn on the globe
  dragHandlers: null,
  options: null,
  result: null,
  previewTimer: null,
};

/* ── Boot ───────────────────────────────────────────────────────────────── */

async function boot() {
  // Prove which build is running. Stale CSS produces correct code paired with
  // old presentation, which is indistinguishable from a code bug unless the
  // page can state its own version.
  const assetV = new URL(import.meta.url).searchParams.get('v') || 'dev';
  console.info(`[lunarserpent] build ${assetV}`);
  const stamp = document.getElementById('buildstamp');
  if (stamp) stamp.textContent = `build ${assetV}`;

  three = new Globe($('gl'));
  globe = three;
  state.renderer = 'three';
  globe.start(onFrame);

  // Rotation changes what is on screen as much as zoom does, so the detail
  // patch must follow orbiting too, not only altitude.
  wireRenderer(globe);

  bindControls();
  bindSearch();
  bindPanelTabs();
  bindViewpoints();
  buildLandmarks();

  $('rnd-three').addEventListener('click', () => useRenderer('three'));
  $('rnd-cesium').addEventListener('click', () => useRenderer('cesium'));
  updateProvenance();

  // Promise rejections otherwise surface in the console as an opaque "Object".
  window.addEventListener('unhandledrejection', (e) => {
    const r = e.reason;
    console.error('[lunarserpent] unhandled rejection:',
                  r?.message || r?.toString?.() || r, r);
  });

  try {
    setLoading('Checking data sources…');
    const health = await api.health();
    applyHealth(health);

    setLoading('Reading layer catalogue…');
    const meta = await api.layers();
    state.basemaps = meta.basemaps;
    state.classes = meta.crater_classes;
    for (const c of meta.crater_classes) state.classVisible[c.key] = true;
    buildBasemapControls();
    buildClassLegend();

    setLoading('Stitching basemap mosaic — first run only…');
    await loadBasemap(state.basemap);

    setLoading('Querying crater catalogue…');
    await refreshCraters();

    setLoading('Loading IAU named features…');
    try {
      const kinds = await api.featureKinds();
      state.kinds = kinds.kinds;
      for (const k of kinds.kinds) {
        // Satellite craters ("Tycho A", "Copernicus H") outnumber named
        // craters four to one and would swamp the view, so they start hidden.
        state.kindVisible[k.key] = k.key !== 'satellite_crater';
      }
      $('named-count').textContent = fmtInt(kinds.total);
      buildKindLegend();
      await refreshNames(true);
    } catch (err) {
      say(`Named features unavailable: ${err.message}`);
    }

    try {
      buildPlanPanel(await api.planOptions());
    } catch (err) {
      // The globe is still fully usable without the planner, so a failure here
      // degrades one panel rather than the application.
      $('plan-status').textContent = `Planning unavailable: ${err.message}`;
      say(`Planning unavailable: ${err.message}`);
    }

    hideLoading();
    say('Ready. Click a name for full morphometry, or click anywhere to sample.');
  } catch (err) {
    console.error(err);
    setLoading(`Startup failed: ${err.message}`);
    $('st-health').className = 'cell bad';
    say(err.message);
  }
}

function applyHealth(h) {
  const el = $('st-health');
  const ok = h.components?.elevation?.ok && h.components?.craters?.ok;
  el.className = ok ? 'cell ok' : 'cell bad';
  el.title = ok
    ? `Elevation and crater catalogue online — ${fmtInt(h.components.craters.count)} craters`
    : JSON.stringify(h.components);
  if (h.components?.craters?.ok) {
    $('crater-count').textContent = fmtInt(h.components.craters.count);
  }
}

/* ── Basemap ────────────────────────────────────────────────────────────── */

function buildBasemapControls() {
  const box = $('basemaps');
  box.innerHTML = '';
  for (const b of state.basemaps) {
    const id = `bm-${b.key}`;
    const label = document.createElement('label');
    label.innerHTML =
      `<input type="radio" name="basemap" id="${id}" value="${b.key}"` +
      `${b.key === state.basemap ? ' checked' : ''}><span>${b.title}</span>`;
    label.querySelector('input').addEventListener('change', async () => {
      state.basemap = b.key;
      updateProvenance();
      updateCredit();
      say(`Loading ${b.title}…`);
      await loadBasemap(b.key);
      say(`${b.title} active.`);
    });
    box.appendChild(label);
  }
  updateCredit();
}

function updateCredit() {
  const b = state.basemaps.find((x) => x.key === state.basemap);
  $('basemap-credit').innerHTML = b
    ? `${b.description}<br><b>${b.credit}</b> · native ${b.native_m_px} m/px`
    : '';
}

async function loadBasemap(key) {
  busy(true);
  try {
    // The detail patch belongs to the previous layer; drop it so the new
    // basemap is not left showing the old imagery on top.
    globe.clearDetailPatch();
    lod.key = null;
    await globe.setTexture(api.textureUrl(key, 4));
    scheduleLOD();
  } catch (err) {
    // A missing basemap must not leave a blank globe.
    console.warn('basemap failed', err);
    say(`Basemap unavailable (${err.message}) — showing plain sphere.`);
  } finally {
    busy(false);
  }
}

/* ── Craters ────────────────────────────────────────────────────────────── */

function buildClassLegend() {
  const box = $('classes');
  box.innerHTML = '';
  for (const c of state.classes) {
    const row = document.createElement('div');
    row.className = 'item';
    const range = c.max_km === null
      ? `≥ ${c.min_km} km`
      : `${c.min_km}–${c.max_km} km`;
    row.innerHTML =
      `<span class="sw" style="background:${c.colour}"></span>` +
      `<span>${c.label}</span><span class="n">${range}</span>`;
    row.title = c.basis;
    row.style.cursor = 'pointer';
    row.addEventListener('click', () => {
      state.classVisible[c.key] = !state.classVisible[c.key];
      row.style.opacity = state.classVisible[c.key] ? '1' : '0.35';
      globe.setClassVisible(c.key, state.classVisible[c.key]);
    });
    box.appendChild(row);
  }
}

let cratersKey = null;

/**
 * Draw crater rims for the region actually in view.
 *
 * Querying the whole globe regardless of camera made the layer *worse* as you
 * zoomed in: the budget was spent on the largest craters planet-wide, most of
 * them behind the body, while the small craters under the cursor never
 * appeared. Restricting to the visible cap spends the same budget on what is
 * on screen, and the size floor falls with altitude so descending reveals finer
 * structure rather than the same handful of giants.
 */
async function refreshCraters(force = false) {
  if (!state.showCraters) {
    globe.clearCraters();
    return;
  }

  const r = globe.visibleRegion();
  const alt = globe.altitudeKm();
  // Same 2 %-of-view rule the labels use, floored by the user's slider.
  const visibleWidthKm = Math.max(
    2 * alt * Math.tan((38 * Math.PI / 180) / 2), 50);
  const minD = Math.max(state.minDiameterKm, visibleWidthKm * 0.004);

  const key = [
    Math.round(Math.log2(Math.max(minD, 0.5)) * 2),
    state.maxDrawn,
    r.full ? 'global' : `${Math.round(r.centre.lat / 6)}:${Math.round(r.centre.lon / 6)}`,
  ].join('|');
  if (!force && key === cratersKey) return;
  cratersKey = key;

  busy(true);
  try {
    const res = await api.cratersBbox({
      south: r.full ? -90 : r.south,
      north: r.full ? 90 : r.north,
      west: r.full ? 0 : r.west,
      east: r.full ? 360 : r.east,
      minDiameterKm: minD,
      limit: state.maxDrawn,
    });
    const colours = Object.fromEntries(state.classes.map((c) => [c.key, c.colour]));
    const drawn = globe.setCraters(res.craters, colours);
    for (const c of state.classes) {
      globe.setClassVisible(c.key, state.classVisible[c.key]);
    }
    state.craterStats = { drawn, matching: res.total_matching, minD };
    say(`${fmtInt(drawn)} rims drawn · D ≥ ${minD.toFixed(1)} km · ` +
        `${fmtInt(res.total_matching)} in view (${res.query_ms} ms)`);
  } catch (err) {
    say(`Crater query failed: ${err.message}`);
  } finally {
    busy(false);
  }
}

/** Map the slider's 0-100 position onto a logarithmic diameter scale. */
function sliderToDiameter(v) {
  // 0 -> 1 km, 100 -> 1000 km; log spacing matches how crater counts fall off.
  const t = v / 100;
  return Math.round(Math.pow(10, t * 3) * 10) / 10;
}

/* ── Named features ─────────────────────────────────────────────────────── */

function buildKindLegend() {
  const box = $('kinds');
  box.innerHTML = '';
  for (const k of state.kinds) {
    const row = document.createElement('div');
    row.className = 'item';
    row.innerHTML =
      `<span class="sw" style="background:${k.colour}"></span>` +
      `<span>${k.label}</span><span class="n">${fmtInt(k.count)}</span>`;
    row.style.cursor = 'pointer';
    row.style.opacity = state.kindVisible[k.key] ? '1' : '0.35';
    row.addEventListener('click', () => {
      state.kindVisible[k.key] = !state.kindVisible[k.key];
      row.style.opacity = state.kindVisible[k.key] ? '1' : '0.35';
      refreshNames();
    });
    box.appendChild(row);
  }
}

/**
 * Smallest feature worth naming at the current altitude.
 *
 * A map does not show every name at every scale — it shows the names that are
 * legible and meaningful at the scale you are viewing. The rule here is that a
 * feature earns a label once it spans roughly 2 % of the visible width, so
 * zooming out leaves only the maria and giant basins, while descending brings
 * progressively smaller craters into view. The user's slider then acts as a
 * floor on top of this, not a replacement for it.
 */
function autoMinDiameter(altKm) {
  const visibleWidthKm = Math.max(2 * altKm * Math.tan((38 * Math.PI / 180) / 2), 50);
  return Math.max(state.nameMinDiameterKm, visibleWidthKm * 0.02);
}

let namesKey = null;

async function refreshNames(force = false) {
  if (!state.showNames) { globe.clearLabels(); return; }
  const kinds = state.kinds
    .filter((k) => state.kindVisible[k.key])
    .map((k) => k.key);
  if (!kinds.length) { globe.clearLabels(); return; }

  const alt = globe.altitudeKm();
  const minD = autoMinDiameter(alt);
  const r = globe.visibleRegion();

  // Re-query only when the scale or the viewed region has meaningfully moved.
  const key = [
    kinds.join(','),
    Math.round(Math.log2(Math.max(minD, 1)) * 2),
    r.full ? 'global' : `${Math.round(r.centre.lat / 8)}:${Math.round(r.centre.lon / 8)}`,
  ].join('|');
  if (!force && key === namesKey) return;
  namesKey = key;

  try {
    const res = await api.featuresNamed({
      south: r.full ? -90 : r.south,
      north: r.full ? 90 : r.north,
      west: r.full ? 0 : r.west,
      east: r.full ? 360 : r.east,
      minDiameterKm: minD,
      kinds: kinds.join(','),
      limit: state.maxLabels,
    });
    globe.setLabels(res.features, { onClick: (f) => analyseFeature(f) });
    say(`${res.count} names ≥ ${minD.toFixed(0)} km in view`);
  } catch (err) {
    say(`Named-feature query failed: ${err.message}`);
  }
}

/* ── Full scientific analysis of a named feature ────────────────────────── */

async function analyseFeature(f) {
  globe.flyTo(f.lat, f.lon);
  globe.setMarker(f.lat, f.lon);
  state.selection = { lat: f.lat, lon: f.lon };
  $('in-lat').value = f.lat.toFixed(4);
  $('in-lon').value = f.lon.toFixed(4);

  $('inspect-empty').hidden = true;
  const body = $('inspect-body');
  body.hidden = false;
  body.innerHTML = `<div class="empty">Measuring <b>${f.name}</b> from LOLA
    topography…</div>`;

  try {
    const a = await api.featureAnalyse({ name: f.name });
    renderAnalysis(a, f);
    say(`${f.name}: depth ${a.measured.depth_m} m, ` +
        `${a.sampling.pixels_across_diameter} px across (${a.sampling.adequacy})`);
  } catch (err) {
    // A refusal is a real scientific result; present it, do not hide it.
    body.innerHTML =
      `<div class="sec"><h4>${f.name}</h4>
        <div class="kv">
          <div class="r"><span class="k">Type</span><span class="v">${f.kind_label}</span></div>
          <div class="r"><span class="k">Diameter</span><span class="v">${f.diameter_km ?? '—'} km</span></div>
          <div class="r"><span class="k">Centre</span><span class="v">${fmtCoord(f.lat, f.lon)}</span></div>
        </div></div>
       <div class="sec"><div class="warnnote"><b>Cannot measure.</b><br>${err.message}</div></div>` +
      (f.origin ? `<div class="sec"><h4>Etymology</h4>
        <div class="srcnote">${f.origin}</div></div>` : '');
    say(`${f.name}: ${err.message}`);
  }
}

function renderAnalysis(a, f) {
  const m = a.measured, p = a.predicted, s = a.sampling;
  const id = a.identity || f || {};

  const rows = (pairs) => pairs
    .filter(([, v]) => v !== undefined && v !== null)
    .map(([k, v, cls]) =>
      `<div class="r"><span class="k">${k}</span>` +
      `<span class="v${cls ? ' ' + cls : ''}">${v}</span></div>`)
    .join('');

  const m2 = (v) => (v === null || v === undefined ? '—' : `${fmtInt(Math.round(v))} m`);
  const km = (v, d = 2) => (v === null || v === undefined ? '—' : `${v.toFixed(d)} km`);

  let h = '';

  // Identity
  h += `<div class="sec">
    <h4>${id.kind_label || 'Feature'}</h4>
    <div style="font-size:17px;font-weight:650;margin:-2px 0 8px;color:${id.colour || '#e8ecf4'}">
      ${id.name || 'Unnamed'}
    </div>
    <div class="kv">${rows([
      ['Centre', fmtCoord(a.location.lat, a.location.lon)],
      ['Diameter', km(a.diameter_km), 'hi'],
      ['Area', fmtArea(id.area_km2 ?? Math.PI * (a.diameter_km / 2) ** 2)],
      ['Morphology', a.morphology.class],
      ['IAU approved', id.approval_year ?? null],
      ['LAC chart', id.quad ?? null],
    ])}</div>
    <p class="note">${a.morphology.basis}</p>
  </div>`;

  // Vertical structure
  h += `<div class="sec"><h4>Vertical structure — measured</h4>
    <div class="kv">${rows([
      ['Depth (rim → floor)', m2(m.depth_m), 'hi'],
      ['Rim height above terrain', m2(m.rim_height_m)],
      ['Floor below terrain', m2(m.floor_depth_m)],
      ['Rim elevation', m2(m.rim_elevation_m)],
      ['Floor elevation', m2(m.floor_elevation_m)],
      ['Surrounding datum', m2(m.reference_elevation_m)],
      ['Total relief', m2(m.relief_m)],
      ['Depth / diameter', m.depth_diameter_ratio?.toFixed(4)],
      ['Excavated volume', m.volume_km3 !== null
        ? `${fmtInt(Math.round(m.volume_km3))} km³` : null],
    ])}</div></div>`;

  // Slope
  h += `<div class="sec"><h4>Slope</h4>
    <div class="kv">${rows([
      ['Wall slope (profile)', m.wall_slope_deg !== null
        ? `${m.wall_slope_deg.toFixed(2)}°` : null, 'hi'],
      ['Mean interior slope', m.mean_slope_deg !== null
        ? `${m.mean_slope_deg.toFixed(2)}°` : null],
      ['Maximum slope', m.max_slope_deg !== null
        ? `${m.max_slope_deg.toFixed(2)}°` : null],
      ['Measured over baseline', `${fmtInt(Math.round(s.slope_baseline_m))} m`],
    ])}</div>
    <p class="note">Slope is scale-dependent. These values describe the
    ${fmtInt(Math.round(s.slope_baseline_m))} m baseline of the DEM, not the
    metre-scale gradient a rover wheel would meet.</p></div>`;

  // Comparison with published scaling
  const ratio = p.depth_ratio_measured_over_predicted;
  const bar = ratio !== null
    ? Math.max(2, Math.min(100, ratio * 50))
    : 0;
  h += `<div class="sec"><h4>Versus Pike's fresh-crater relation</h4>
    <div class="kv">${rows([
      ['Predicted depth', m2(p.depth_m)],
      ['Measured depth', m2(m.depth_m)],
      ['Ratio', ratio !== null ? ratio.toFixed(2) + '×' : null, 'hi'],
      ['Regime', p.regime],
      ['Predicted rim height', m2(p.rim_height_m)],
    ])}</div>
    <div class="ratiobar"><span style="width:${bar}%"></span>
      <i style="left:50%"></i></div>
    <p class="note">${p.interpretation}</p></div>`;

  // Sampling adequacy — always shown, never buried
  const adCls = s.adequacy === 'good' ? 'srcnote' : 'warnnote';
  h += `<div class="sec"><h4>Sampling adequacy</h4>
    <div class="kv">${rows([
      ['Grid resolution', `${s.resolution_m_px} m/px`],
      ['Cells across diameter', s.pixels_across_diameter?.toFixed(1)],
      ['Verdict', s.adequacy.toUpperCase(), 'hi'],
    ])}</div>
    <div class="${adCls}" style="margin-top:8px">
      ${s.adequacy === 'good'
        ? 'The grid resolves this feature well; measurements are quantitative.'
        : 'Measurements below are approximate at this grid resolution.'}
    </div></div>`;

  if (a.warnings?.length) {
    h += `<div class="sec">${a.warnings
      .map((w) => `<div class="warnnote" style="margin-bottom:6px">${w}</div>`)
      .join('')}</div>`;
  }

  if (id.origin) {
    h += `<div class="sec"><h4>Name origin</h4>
      <div class="srcnote">${id.origin}</div></div>`;
  }

  h += `<div class="sec"><h4>Sources</h4><div class="srcnote">` +
    Object.values(a.sources).map((v) => `• ${v}`).join('<br>') +
    (id.url ? `<br>• <a href="${id.url}" target="_blank"
       rel="noopener" style="color:var(--accent)">IAU Gazetteer entry ↗</a>` : '') +
    `</div></div>`;

  $('inspect-body').innerHTML = h;
}

/* ── Selection / inspector ──────────────────────────────────────────────── */

async function select(lat, lon) {
  // An armed picker consumes the click: the user asked to place an endpoint,
  // not to inspect the terrain under it.
  if (plan.picking) {
    setPin(plan.picking, lat, lon);
    say(`${plan.picking === 'start' ? 'Start' : 'Goal'} set to ${fmtCoord(lat, lon)}.`);
    armPicker(plan.picking);
    return;
  }

  state.selection = { lat, lon };
  globe.setMarker(lat, lon);
  $('in-lat').value = lat.toFixed(4);
  $('in-lon').value = lon.toFixed(4);

  $('inspect-empty').hidden = true;
  const body = $('inspect-body');
  body.hidden = false;
  body.innerHTML = `<div class="empty">Sampling ${fmtCoord(lat, lon)}…</div>`;

  try {
    const [terrain, craters] = await Promise.all([
      api.terrainPoint(lat, lon),
      api.cratersAt(lat, lon),
    ]);
    renderInspector(terrain, craters);
    $('st-elev').textContent = `elev ${fmtLen(terrain.elevation_m)}`;
  } catch (err) {
    body.innerHTML = `<div class="warnnote">Sampling failed: ${err.message}</div>`;
  }
}

function renderInspector(t, c) {
  const rows = (pairs) => pairs
    .map(([k, v, hi]) =>
      `<div class="r"><span class="k">${k}</span>` +
      `<span class="v${hi ? ' hi' : ''}">${v}</span></div>`)
    .join('');

  let html = '';

  html += `<div class="sec"><h4>Location</h4><div class="kv">${rows([
    ['Latitude', `${t.lat.toFixed(5)}°`, true],
    ['Longitude', `${t.lon.toFixed(5)}° E`, true],
    ['Elevation', fmtLen(t.elevation_m), true],
    ['Radius', `${(t.radius_m / 1000).toFixed(3)} km`],
  ])}</div></div>`;

  html += `<div class="sec"><h4>Sampling geometry</h4><div class="kv">${rows([
    ['Grid resolution', `${t.resolution_m_px} m/px`],
    ['Cell E–W', fmtLen(t.cell_size_m.east_west)],
    ['Cell N–S', fmtLen(t.cell_size_m.north_south)],
  ])}</div></div>`;

  if (t.warning) {
    html += `<div class="sec"><div class="warnnote">${t.warning}</div></div>`;
  }

  if (c.enclosing?.length) {
    html += `<div class="sec"><h4>Craters containing this point (${c.enclosing.length})</h4>`;
    for (const k of c.enclosing.slice(0, 6)) {
      html += craterCard(k);
    }
    html += `</div>`;
  } else {
    html += `<div class="sec"><h4>Craters containing this point</h4>
      <div class="empty" style="padding:8px 0">None in the catalogue.
      Craters below 1 km are not catalogued — see note below.</div></div>`;
  }

  if (c.nearest) {
    html += `<div class="sec"><h4>Nearest catalogued centre</h4>${craterCard(c.nearest)}</div>`;
  }

  html += `<div class="sec"><div class="srcnote">
    <b>Elevation</b> ${t.source}, sampled at ${t.resolution_m_px} m/px.<br>
    <b>Craters</b> ${c.source} — complete for D ≥ 1 km. Absence of a small
    crater here means it is below the catalogue limit, not that the ground is
    smooth.<br>
    <b>Names</b> ${c.names_source ?? 'IAU Gazetteer'} — most lunar craters have
    never been named, so an ID without a name is expected.</div></div>`;

  $('inspect-body').innerHTML = html;
  bindCraterCards();
}

function craterCard(k) {
  // A named crater leads with its name; an unnamed one leads with its
  // catalogue ID, which is the honest answer — most lunar craters have no name.
  const title = k.named
    ? `<span class="nm">${k.name}</span><span class="cid">${k.id}</span>`
    : `<span class="id">${k.id}</span>`;
  const clickable = k.named ? ' named' : '';
  return `<div class="cratercard${clickable}" style="border-left-color:${k.colour}"
       ${k.named ? `data-name="${k.name}"` : ''}>
    <div class="top">
      <span>${title}</span>
      <span class="cls" style="color:${k.colour}">${k.class_label}</span>
    </div>
    <div class="dims">
      D ${k.diameter_km.toFixed(2)} km · area ${fmtArea(k.area_km2)}<br>
      ${fmtCoord(k.lat, k.lon)}
      ${k.ellipticity ? ` · ellip ${k.ellipticity.toFixed(2)}` : ''}
    </div>
  </div>`;
}

/** Make named crater cards jump to the full morphometry view. */
function bindCraterCards() {
  document.querySelectorAll('.cratercard.named').forEach((el) => {
    el.addEventListener('click', () => gotoFeatureByName(el.dataset.name));
  });
}

/* ── Discover ───────────────────────────────────────────────────────────── */

const discover = { cats: [], active: null, loaded: false };

function bindPanelTabs() {
  for (const tab of document.querySelectorAll('.ptab')) {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.ptab').forEach((t) => t.classList.remove('on'));
      document.querySelectorAll('.ptabpane').forEach((p) => { p.hidden = true; });
      tab.classList.add('on');
      $(tab.dataset.tab).hidden = false;
      // Loaded lazily: each catalogue is only needed once its tab is opened.
      if (tab.dataset.tab === 'tab-discover' && !discover.loaded) loadDiscover();
      if (tab.dataset.tab === 'tab-missions' && !missions.loaded) loadMissions();
      if (tab.dataset.tab === 'tab-science' && !science.loaded) loadScience();
    });
  }
}

async function loadDiscover() {
  const list = $('disc-list');
  list.innerHTML = '<div class="empty">Loading places…</div>';
  try {
    const res = await api.discover();
    discover.cats = res.categories;
    discover.loaded = true;

    const chips = $('disc-cats');
    chips.innerHTML = '';
    for (const c of discover.cats) {
      const b = document.createElement('button');
      b.textContent = c.label;
      b.title = `${c.count} places`;
      b.addEventListener('click', () => showCategory(c.key));
      chips.appendChild(b);
    }
    showCategory(discover.cats[0].key);
  } catch (err) {
    list.innerHTML = `<div class="empty">Could not load: ${err.message}</div>`;
  }
}

function showCategory(key) {
  const cat = discover.cats.find((c) => c.key === key);
  if (!cat) return;
  discover.active = key;

  [...$('disc-cats').children].forEach((b, i) =>
    b.classList.toggle('on', discover.cats[i].key === key));

  $('disc-blurb').textContent = `${cat.blurb}  ·  ${cat.count} places`;

  const list = $('disc-list');
  list.innerHTML = '';
  for (const it of cat.items) {
    const el = document.createElement('div');
    el.className = 'dcard';
    el.style.borderLeftColor = it.colour || 'var(--border-lt)';

    const dm = it.diameter_km
      ? `${it.diameter_km >= 100 ? Math.round(it.diameter_km) : it.diameter_km.toFixed(1)} km`
      : '';

    el.innerHTML =
      `<div class="hd">
         <span class="nm">${it.name}</span>
         <span class="ty">${it.kind_label}</span>
         <span class="dm">${dm}</span>
       </div>` +
      (it.why ? `<div class="wh">${it.why}</div>` : '') +
      `<div class="mt">
         <span>${fmtCoord(it.lat, it.lon)}</span>
         <span class="vis ${it.visibility}" title="${it.visibility_note}">
           ${it.visibility}</span>
       </div>`;

    el.addEventListener('click', () => {
      globe.flyTo(it.lat, it.lon, 900);
      analyseFeature(it);
    });
    list.appendChild(el);
  }
}

/* ── Renderer switching ─────────────────────────────────────────────────────
 *
 * Two renderers, one application. `CesiumRenderer` mirrors the public surface
 * of `Globe`, so everything downstream — panels, inspector, search, layers —
 * calls the same methods and never asks which is active. Switching therefore
 * means swapping one object and replaying the current layer state, not
 * branching at every call site.
 *
 * Cesium is created lazily. It pulls ~5 MB from a CDN and needs a network, so
 * a user who never opens it never pays for it, and a failure there leaves the
 * Three.js globe untouched.
 */

// `three` and `cesium` are declared at the top of the module, beside `globe`.
// They were originally declared here, below boot() — and because `let` bindings
// sit in a temporal dead zone until their declaration is evaluated, boot()'s
// first statement threw ReferenceError and took the whole application down
// before either renderer started. Declaration order matters for `let` in a way
// it does not for `function`.

async function useRenderer(which) {
  if (state.renderer === which) return;

  const btnT = $('rnd-three'), btnC = $('rnd-cesium');
  const canvas = $('gl');
  const container = $('cesiumContainer');

  if (which === 'cesium') {
    btnC.disabled = true;
    btnC.textContent = 'Loading…';
    try {
      if (!cesium) {
        const { CesiumRenderer } = await import('./cesium-renderer.js');
        cesium = new CesiumRenderer(container);
        container.hidden = false;
        await cesium.init();
        wireRenderer(cesium);
        cesium.start(onFrame);
      } else {
        container.hidden = false;
      }
    } catch (err) {
      container.hidden = true;
      btnC.disabled = false;
      btnC.textContent = 'Terrain';
      say(`Terrain view unavailable — ${err.message}`);
      return;
    }
    canvas.style.visibility = 'hidden';
    // The CSS2D labels live in a sibling div, not inside the canvas, so hiding
    // the canvas alone leaves them frozen on screen over the Cesium view.
    three?.setOverlayVisible(false);
    globe = cesium;
    state.renderer = 'cesium';
    syncSurfaceButton();
    btnC.textContent = 'Terrain';
    btnC.disabled = false;
    $('tilestats').hidden = false;
    say('Cesium Moon Terrain — 3D Tiles, adaptive detail.');
  } else {
    if (cesium) container.hidden = true;
    canvas.style.visibility = '';
    three?.setOverlayVisible(true);
    globe = three;
    state.renderer = 'three';
    syncSurfaceButton();
    $('tilestats').hidden = true;
    say('Classic globe — LOLA relief, no external dependency.');
  }

  btnT.classList.toggle('on', which === 'three');
  btnC.classList.toggle('on', which === 'cesium');
  updateProvenance();

  // Replay current state onto the renderer that just became active.
  globe.setGraticule($('btn-grid').classList.contains('on'));
  globe.setLabelsVisible(state.showNames);
  globe.setAutoRotate($('btn-spin').classList.contains('on'));
  if (state.selection) globe.setMarker(state.selection.lat, state.selection.lon);
  namesKey = null;
  cratersKey = null;
  lod.key = null;
  refreshNames(true);
  refreshCraters(true);
}

/**
 * Update the provenance badge.
 *
 * The renderer decides what you see; it does not decide what anything measures.
 * Cesium Moon Terrain publishes no resolution, no vertical accuracy and no
 * reference frame — its own announcement claims suitability for "analysis and
 * measurements" without quoting a single figure — so it is presented here as a
 * viewing surface only. Every elevation, slope, depth and distance this system
 * reports comes from LOLA, whose vertical quantisation is 0.5 m and whose frame
 * is stated in its PDS label. Saying so on screen is the difference between a
 * visualisation and an instrument.
 */
function updateProvenance() {
  const el = $('provenance');
  const cesiumOn = state.renderer === 'cesium';
  el.classList.toggle('cesium', cesiumOn);

  $('pv-name').textContent = cesiumOn
    ? 'Cesium Moon Terrain' : 'Classic globe';

  if (cesiumOn) {
    const s = cesium?.tileStats?.();
    const detail = s?.geometricError
      ? (s.geometricError < 1000 ? `${s.geometricError.toFixed(0)} m`
                                 : `${(s.geometricError / 1000).toFixed(1)} km`)
      : 'streaming…';
    if (cesium?.surfaceMode === 'science') {
      const b = state.basemaps.find((x) => x.key === state.basemap);
      $('pv-surface').textContent =
        `${b?.title || state.basemap} · ${b?.served_m_px ?? '?'} m/px`;
      $('pv-shape').textContent =
        'LOLA terrain · finest local per tile · citable';
    } else if (cesium?.surfaceMode === 'imagery') {
      const b = state.basemaps.find((x) => x.key === state.basemap);
      $('pv-surface').textContent =
        `${b?.title || state.basemap} · ${b?.served_m_px ?? '?'} m/px`;
      $('pv-shape').textContent =
        'sphere · 1737.4 km · no relief in this mode';
    } else {
      // `geometricError` is a level-of-detail threshold — the screen-space
      // error at which a tile subdivides — not the posting of any dataset.
      // Labelling it "83 m" under "Surface" invited exactly the reading it
      // does not support.
      $('pv-surface').textContent = `3D Tiles · LOD ${detail} (not a resolution)`;
      // Measured, not assumed. 240 samples of this tileset's own surface
      // against LOLA LDEM_64 give a mean offset of +1,789 m and a best fit of
      // 1.060 x LOLA + 1,824 m. At the Apollo 15 site it reads +234 m where
      // LOLA and the LROC NAC stereo DTM — different instruments, different
      // pipelines — agree on -1924 m to within one metre. It is the right
      // terrain in the wrong place vertically, so it is a view, never a
      // measurement.
      $('pv-shape').textContent =
        'view only · +1.8 km vs LOLA · do not measure from this';
    }
  } else {
    const b = state.basemaps.find((x) => x.key === state.basemap);
    const bm = b?.title || 'LROC WAC Global Mosaic';
    const res = b?.native_m_px;
    $('pv-surface').textContent = res ? `${bm} · ${res} m/px` : bm;
    $('pv-shape').textContent = state.relief > 0
      ? `LOLA LDEM_64 · 474 m/px · ${state.relief}x vertical`
      : 'true sphere (relief off)';
  }
  // Unchanged by the renderer, deliberately.
  $('pv-measure').textContent = 'LOLA · ±0.5 m · DE421';
}

/** Attach the shared pick/hover handlers to a renderer. */
function wireRenderer(r) {
  r.onPick(({ lat, lon }) => select(lat, lon));
  r.onHover((c) => {
    $('st-coord').textContent = c ? fmtCoord(c.lat, c.lon) : '— , —';
  });
  r.controls.addEventListener('change', scheduleLOD);
}

/** Named viewpoints, offered in the Places panel rather than the toolbar. */
const VIEWPOINTS = {
  npole: { lat: 89.5, lon: 0, km: 900, msg: 'North pole — 90°N.' },
  spole: {
    lat: -89.5, lon: 0, km: 900,
    msg: 'South pole — 90°S. Permanently shadowed floors here hold water ice.',
  },
  nearside: { lat: 0, lon: 0, km: 6000, msg: 'Nearside — the face Earth always sees.' },
  farside: {
    lat: 0, lon: 180, km: 6000,
    msg: 'Farside — never visible from Earth; first imaged by Luna 3 in 1959.',
  },
};

function bindViewpoints() {
  for (const b of document.querySelectorAll('.viewbtn')) {
    b.addEventListener('click', () => {
      const v = VIEWPOINTS[b.dataset.view];
      if (!v) return;
      // Cesium can look straight down at a pole; the Three.js camera cannot
      // without losing its up-vector, so it simply flies overhead instead.
      if (globe.flyToPole && (b.dataset.view === 'npole' || b.dataset.view === 'spole')) {
        globe.flyToPole(b.dataset.view === 'npole');
      } else {
        globe.flyTo(v.lat, v.lon, v.km);
      }
      say(v.msg);
    });
  }
}

function updateTileStats() {
  if (state.renderer !== 'cesium' || !cesium?.tileStats) return;
  const s = cesium.tileStats();
  if (!s) return;
  const detail = s.geometricError
    ? (s.geometricError < 1000
        ? `${s.geometricError.toFixed(0)} m`
        : `${(s.geometricError / 1000).toFixed(1)} km`)
    : '—';
  $('tilestats').innerHTML =
    `<span class="lbl">tile detail</span> <b>${detail}</b><br>` +
    `<span class="lbl">refinement</span> level ${s.depth}<br>` +
    `<span class="lbl">loaded</span> ${s.tiles.toLocaleString()} · ` +
    `${s.memoryMB.toFixed(0)} MB` +
    (s.pending ? `<br><span class="busy">${s.pending} loading…</span>` : '');
}

/* ── Discoveries ────────────────────────────────────────────────────────── */

const science = { all: [], cats: [], filter: 'all', loaded: false, open: null };

async function loadScience() {
  const list = $('sci-list');
  list.innerHTML = '<div class="empty">Loading…</div>';
  try {
    const res = await api.discoveries();
    science.all = res.discoveries;
    science.cats = res.categories;
    science.loaded = true;

    const s = res.statistics;
    $('sci-legend').innerHTML =
      `<span class="st-established"><i class="st-established"></i>
         ${s.by_status.established} established</span>
       <span class="st-evolving"><i class="st-evolving"></i>
         ${s.by_status.evolving} evolving</span>
       <span class="st-contested"><i class="st-contested"></i>
         ${s.by_status.contested} contested</span>
       <span style="margin-left:auto">${s.mappable} mappable</span>`;

    const box = $('sci-cats');
    box.innerHTML = '';
    for (const [key, label] of [['all', 'All'],
                                ...res.categories.map((c) => [c.key, c.label])]) {
      const b = document.createElement('button');
      b.textContent = label;
      b.dataset.key = key;
      b.addEventListener('click', () => { science.filter = key; renderScience(); });
      box.appendChild(b);
    }
    renderScience();
  } catch (err) {
    list.innerHTML = `<div class="empty">Could not load: ${err.message}</div>`;
  }
}

function renderScience() {
  const shown = science.filter === 'all'
    ? science.all
    : science.all.filter((d) => d.category === science.filter);

  [...$('sci-cats').children].forEach((b) => {
    b.classList.toggle('on', b.dataset.key === science.filter);
  });

  const cat = science.cats.find((c) => c.key === science.filter);
  $('sci-blurb').textContent = cat
    ? `${cat.blurb}  ·  ${shown.length} findings`
    : `${shown.length} findings, 1959–2023`;

  const list = $('sci-list');
  list.innerHTML = '';
  for (const d of shown) {
    const el = document.createElement('div');
    el.className = `scard ${d.status}`;
    el.innerHTML = scienceCardHTML(d);
    el.addEventListener('click', (e) => {
      if (e.target.closest('.pin')) return;
      science.open = science.open === d.key ? null : d.key;
      renderScience();
    });
    list.appendChild(el);
  }

  list.querySelectorAll('.pin').forEach((b) => {
    b.addEventListener('click', (e) => {
      e.stopPropagation();
      const d = science.all.find((x) => x.key === b.dataset.key);
      globe.flyTo(d.lat, d.lon, 800);
      globe.setMarker(d.lat, d.lon);
      select(d.lat, d.lon);
      say(`${d.title} — ${d.place}`);
    });
  });
}

function scienceCardHTML(d) {
  const open = science.open === d.key;
  let h = `<div class="hd">
      <span class="ti">${d.title}</span>
      <span class="yr">${d.year}</span>
    </div>
    <div class="ms">${d.flag} ${d.mission} · ${d.instrument}</div>
    <div class="hl">${d.headline}</div>
    ${d.value ? `<div class="val">${d.value}</div>` : ''}
    <div class="foot">
      <span class="st-${d.status}">● ${d.status}</span>
      ${d.mappable
        ? `<button class="pin" data-key="${d.key}">📍 ${d.place}</button>`
        : '<span style="color:var(--fg-faint)">global property</span>'}
    </div>`;
  if (open) {
    h += `<div class="dt">${d.detail}</div>
          <div class="rf">${d.refs.join(' · ')}</div>`;
  }
  return h;
}

/* ── Missions ───────────────────────────────────────────────────────────── */

const missions = { all: [], stats: null, filter: 'all', loaded: false, open: null };

const OUTCOME_CLASS = { success: 'ok', partial: 'partial', failure: 'fail' };
const KIND_LABEL = {
  impact: 'Impact', landing: 'Soft landing', rover: 'Rover',
  sample_return: 'Sample return', crewed: 'Crewed',
};

async function loadMissions() {
  const list = $('mis-list');
  list.innerHTML = '<div class="empty">Loading missions…</div>';
  try {
    const res = await api.missions();
    missions.all = res.missions;
    missions.stats = res.statistics;
    missions.loaded = true;

    const s = res.statistics;
    $('mis-stats').innerHTML = `
      <div class="s"><b>${s.total_missions}</b><span>missions</span></div>
      <div class="s"><b>${s.countries}</b><span>countries</span></div>
      <div class="s"><b>${s.people_landed}</b><span>people</span></div>
      <div class="s"><b>${s.total_sample_mass_kg}</b><span>kg returned</span></div>
      <div class="s"><b>${Math.round(s.total_traverse_km)}</b><span>km driven</span></div>
      <div class="s"><b>${s.year_range[0]}–${String(s.year_range[1]).slice(2)}</b><span>span</span></div>`;

    const filters = [
      ['all', 'All'],
      ...res.countries.map((c) => [`country:${c.country}`, `${c.flag} ${c.country}`]),
      ['kind:crewed', 'Crewed'],
      ['kind:rover', 'Rovers'],
      ['kind:sample_return', 'Sample return'],
      ['outcome:failure', 'Failed'],
    ];
    const box = $('mis-filters');
    box.innerHTML = '';
    for (const [key, label] of filters) {
      const b = document.createElement('button');
      b.textContent = label;
      b.dataset.key = key;      // the filter itself, not its label text
      b.addEventListener('click', () => { missions.filter = key; renderMissions(); });
      box.appendChild(b);
    }
    renderMissions();
  } catch (err) {
    list.innerHTML = `<div class="empty">Could not load: ${err.message}</div>`;
  }
}

function renderMissions() {
  const [field, value] = missions.filter.split(':');
  const shown = missions.filter === 'all'
    ? missions.all
    : missions.all.filter((m) => m[field] === value);

  [...$('mis-filters').children].forEach((b) => {
    b.classList.toggle('on', b.dataset.key === missions.filter);
  });

  const list = $('mis-list');
  list.innerHTML = '';
  for (const m of shown) {
    const el = document.createElement('div');
    el.className = `mcard ${OUTCOME_CLASS[m.outcome]}`;
    el.innerHTML = missionCardHTML(m);
    el.addEventListener('click', (e) => {
      if (e.target.closest('.mgo')) return;
      missions.open = missions.open === m.key ? null : m.key;
      renderMissions();
    });
    list.appendChild(el);
  }

  // Wire the fly-to buttons after the cards exist.
  list.querySelectorAll('.mgo').forEach((b) => {
    b.addEventListener('click', (e) => {
      e.stopPropagation();
      const m = missions.all.find((x) => x.key === b.dataset.key);
      globe.flyTo(m.lat, m.lon, 600);
      globe.setMarker(m.lat, m.lon);
      select(m.lat, m.lon);
      say(`${m.name} — ${m.site}`);
    });
  });
}

function missionCardHTML(m) {
  const open = missions.open === m.key;
  const firsts = m.achievements.filter((a) => /^first/i.test(a)).length;

  let h = `<div class="hd">
      <span class="fl">${m.flag}</span>
      <span class="nm">${m.name}</span>
      <span class="yr">${m.year}</span>
    </div>
    <div class="ag">${m.agency} · ${m.country}</div>
    <div class="sm">${m.summary}</div>
    <div class="tags">
      <span class="tg">${KIND_LABEL[m.kind] || m.kind}</span>
      <span class="tg">${m.outcome}</span>
      ${firsts ? `<span class="tg first">${firsts} first${firsts > 1 ? 's' : ''}</span>` : ''}
      ${m.sample_mass_g ? `<span class="tg">${(m.sample_mass_g / 1000).toFixed(m.sample_mass_g < 1000 ? 2 : 1)} kg</span>` : ''}
      ${m.traverse_km ? `<span class="tg">${m.traverse_km} km driven</span>` : ''}
    </div>`;

  if (open) {
    h += `<div class="mdetail">
      <ul>${m.achievements.map((a) => `<li>${a}</li>`).join('')}</ul>
      <div class="kv">
        ${m.crew.length ? `<div class="r"><span class="k">Crew</span><span class="v">${m.crew.join(', ')}</span></div>` : ''}
        <div class="r"><span class="k">Landed</span><span class="v">${m.arrival}</span></div>
        <div class="r"><span class="k">Site</span><span class="v">${m.site}</span></div>
        <div class="r"><span class="k">Position</span><span class="v">${fmtCoord(m.lat, m.lon)}</span></div>
        <div class="r"><span class="k">Coordinates</span>
          <span class="v prec ${m.coord_precision}">${m.coord_precision}</span></div>
        ${m.surface_duration ? `<div class="r"><span class="k">Duration</span><span class="v">${m.surface_duration}</span></div>` : ''}
      </div>
      <button class="mgo" data-key="${m.key}"
        style="margin-top:8px;width:100%">Fly to landing site →</button>
      <div class="ref">${m.refs.join(' · ')}</div>
    </div>`;
  }
  return h;
}

/* ── Search + landmarks ─────────────────────────────────────────────────── */

/** Well-known features, as a one-click entry into 1.3 M anonymous rows. */
const LANDMARKS = [
  'Tycho', 'Copernicus', 'Clavius', 'Aristarchus', 'Plato',
  'Kepler', 'Grimaldi', 'Theophilus', 'Petavius', 'Gassendi',
  'Shackleton', 'Apollo', 'Hertzsprung', 'Korolev', 'Schrodinger',
];

function buildLandmarks() {
  const box = $('landmarks');
  box.innerHTML = '';
  for (const nm of LANDMARKS) {
    const b = document.createElement('button');
    b.textContent = nm;
    b.addEventListener('click', () => gotoFeatureByName(nm));
    box.appendChild(b);
  }
}

async function gotoFeatureByName(name) {
  try {
    const r = await api.featureSearch(name, 1);
    if (!r.results.length) { say(`No feature named "${name}".`); return; }
    const f = r.results[0];
    globe.flyTo(f.lat, f.lon, 900);
    await analyseFeature(f);
  } catch (err) {
    say(`Lookup failed: ${err.message}`);
  }
}

function bindSearch() {
  const input = $('in-search');
  const panel = $('suggest');
  let items = [], active = -1, timer = null;

  const close = () => { panel.hidden = true; active = -1; };

  const render = () => {
    if (!items.length) {
      panel.innerHTML = '<div class="none">No matching feature.</div>';
      panel.hidden = false;
      return;
    }
    panel.innerHTML = items.map((f, i) =>
      `<div class="s${i === active ? ' act' : ''}" data-i="${i}">
         <b>${f.name}</b>
         <span class="k">${f.kind_label}</span>
         <span class="d">${f.diameter_km ? f.diameter_km.toFixed(1) + ' km' : ''}</span>
       </div>`).join('');
    panel.hidden = false;
    panel.querySelectorAll('.s').forEach((el) => {
      el.addEventListener('click', () => {
        const f = items[+el.dataset.i];
        input.value = f.name;
        close();
        globe.flyTo(f.lat, f.lon, 900);
        analyseFeature(f);
      });
    });
  };

  input.addEventListener('input', () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 2) { close(); return; }
    // Debounced so a fast typist does not fire a request per keystroke.
    timer = setTimeout(async () => {
      try {
        const r = await api.featureSearch(q, 12);
        items = r.results;
        active = items.length ? 0 : -1;
        render();
      } catch { close(); }
    }, 160);
  });

  input.addEventListener('keydown', (e) => {
    if (panel.hidden) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault(); active = Math.min(active + 1, items.length - 1); render();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault(); active = Math.max(active - 1, 0); render();
    } else if (e.key === 'Enter' && active >= 0) {
      e.preventDefault();
      const f = items[active];
      input.value = f.name;
      close();
      globe.flyTo(f.lat, f.lon, 900);
      analyseFeature(f);
    } else if (e.key === 'Escape') {
      close();
    }
  });

  document.addEventListener('click', (e) => {
    if (!e.target.closest('.search')) close();
  });
}

/* ── Controls ───────────────────────────────────────────────────────────── */

function bindControls() {
  $('btn-goto').addEventListener('click', () => {
    const lat = parseFloat($('in-lat').value);
    const lon = parseFloat($('in-lon').value);
    if (Number.isNaN(lat) || Number.isNaN(lon)) {
      say('Enter a numeric latitude and longitude.');
      return;
    }
    if (lat < -90 || lat > 90) {
      say('Latitude must lie within ±90°.');
      return;
    }
    globe.flyTo(lat, lon);
    select(lat, lon);
  });

  for (const id of ['in-lat', 'in-lon']) {
    $(id).addEventListener('keydown', (e) => {
      if (e.key === 'Enter') $('btn-goto').click();
    });
  }

  // Names toggle — mirrors the checkbox in the layers panel, so the two can
  // never disagree about whether names are on.
  const nameBtn = $('btn-names');
  const nameBox = $('lyr-names');
  const setNames = (on) => {
    state.showNames = on;
    nameBtn.classList.toggle('on', on);
    nameBox.checked = on;
    globe.setLabelsVisible(on);
    if (on) refreshNames(true);
    say(on ? 'Feature names shown.' : 'Feature names hidden.');
  };
  nameBtn.addEventListener('click', () => setNames(!state.showNames));
  nameBox.addEventListener('change', (e) => setNames(e.target.checked));

  const spin = $('btn-spin');
  spin.addEventListener('click', () => {
    const on = spin.classList.toggle('on');
    globe.setAutoRotate(on);
    // Detail streaming is suspended while spinning; refresh once on stop so
    // the view the user settles on is the sharp one.
    if (!on) { lod.key = null; scheduleLOD(); }
    else say('Auto-rotating — detail streaming paused.');
  });

  $('btn-zin').addEventListener('click', () => globe.zoomBy(0.7));
  $('btn-zout').addEventListener('click', () => globe.zoomBy(1 / 0.7));

  const rel = $('rng-relief');
  rel.addEventListener('input', () => {
    state.relief = +rel.value;
    $('out-relief').textContent = state.relief === 0 ? 'off' : `${state.relief}×`;
  });
  rel.addEventListener('change', () => {
    lod.key = null;          // force the patch to rebuild with new geometry
    scheduleLOD();
  });

  const grid = $('btn-grid');
  grid.addEventListener('click', () => {
    const on = grid.classList.toggle('on');
    globe.setGraticule(on);
  });

  $('btn-reset').addEventListener('click', () => {
    globe.reset();
    say('View reset.');
  });

  $('btn-close-inspect').addEventListener('click', () => {
    state.selection = null;
    globe.clearMarker();
    $('inspect-body').hidden = true;
    $('inspect-empty').hidden = false;
    $('st-elev').textContent = '—';
  });

  $('lyr-craters').addEventListener('change', (e) => {
    state.showCraters = e.target.checked;
    refreshCraters();
  });

  const diam = $('rng-mindiam');
  diam.addEventListener('input', () => {
    state.minDiameterKm = sliderToDiameter(+diam.value);
    $('out-mindiam').textContent = `${state.minDiameterKm} km`;
  });
  diam.addEventListener('change', refreshCraters);
  state.minDiameterKm = sliderToDiameter(+diam.value);
  $('out-mindiam').textContent = `${state.minDiameterKm} km`;

  const draw = $('rng-maxdraw');
  draw.addEventListener('input', () => {
    state.maxDrawn = +draw.value;
    $('out-maxdraw').textContent = state.maxDrawn;
  });
  draw.addEventListener('change', refreshCraters);

  // ── named features ──
  const nd = $('rng-namediam');
  nd.addEventListener('input', () => {
    state.nameMinDiameterKm = sliderToDiameter(+nd.value);
    $('out-namediam').textContent = `≥ ${state.nameMinDiameterKm} km`;
  });
  nd.addEventListener('change', () => refreshNames(true));
  state.nameMinDiameterKm = sliderToDiameter(+nd.value);
  $('out-namediam').textContent = `≥ ${state.nameMinDiameterKm} km`;

  const ml = $('rng-maxlabels');
  ml.addEventListener('input', () => {
    state.maxLabels = +ml.value;
    $('out-maxlabels').textContent = state.maxLabels;
  });
  ml.addEventListener('change', () => refreshNames(true));
}

/* ── Level of detail ────────────────────────────────────────────────────────
 *
 * The base texture is one 8192 x 4096 mosaic of the whole Moon — 1333 m/px.
 * That is fine when the whole disc is in view and hopeless once you descend,
 * because the screen can resolve far finer than the texture carries. Moon Trek
 * holds imagery down to 83 m/px, but the full globe at that depth is 131 072
 * tiles (~1.5 GB), so it can only be fetched for the region actually on screen.
 *
 * This controller watches the camera, works out the ground resolution the
 * screen can resolve, picks the shallowest zoom that satisfies it, and swaps a
 * detail patch over the base sphere.
 */

const lod = {
  timer: null,
  inflight: false,
  key: null,
  MIN_ALT_KM: 900,     // above this the base texture is already sufficient
};

/**
 * Auto-rotation emits a 'change' event every frame and never settles, so a
 * plain debounce never fires its trailing call — it just re-arms forever while
 * the camera keeps moving, issuing a fresh mosaic request every debounce
 * period. Left running for a minute that is over two hundred requests for
 * imagery nobody looks at.
 *
 * Detail streaming is therefore suspended while auto-rotation is on, and
 * resumed once when it stops. The base texture still covers the whole globe,
 * so the spinning view remains complete — just not progressively refined,
 * which is the correct trade for a view that is not being inspected.
 */
function lodSuspended() {
  return globe.controls.autoRotate;
}

/** Shallowest WMTS level whose ground sample is finer than what we can see. */
function zoomForResolution(mPerPx) {
  const CIRC = 2 * Math.PI * 1737400;
  for (let z = 0; z <= 8; z++) {
    if (CIRC / (Math.pow(2, z + 1) * 256) <= mPerPx) return z;
  }
  return 8;
}

function scheduleLOD() {
  if (lod.timer) clearTimeout(lod.timer);
  // Wait for the camera to settle: firing mid-drag would queue requests for
  // windows the user has already flown past.
  lod.timer = setTimeout(updateLOD, 260);
}

async function updateLOD() {
  // Cesium streams 3D Tiles that refine on their own; stitching a detail patch
  // for it would fetch imagery it already has at higher resolution. Labels and
  // crater rims still need refreshing, so those run either way.
  if (state.renderer === 'cesium') {
    refreshNames();
    refreshCraters();
    return;
  }
  if (lodSuspended()) return;
  if (lod.inflight) { scheduleLOD(); return; }

  const alt = globe.altitudeKm();
  if (alt > lod.MIN_ALT_KM) {
    if (lod.key) { globe.clearDetailPatch(); lod.key = null; say('Base mosaic.'); }
    refreshNames();
    refreshCraters();
    return;
  }

  const r = globe.visibleRegion();
  if (r.full) return;

  const z = zoomForResolution(r.mPerPx);
  // Quantise the window so small camera nudges do not force a refetch.
  const q = Math.max((r.north - r.south) / 4, 0.05);
  const key = [z,
    Math.round(r.centre.lat / q),
    Math.round(r.centre.lon / q),
    state.relief].join(':');
  if (key === lod.key) return;

  lod.inflight = true;
  try {
    const m = await api.mosaic(state.basemap, {
      south: r.south, north: r.north, west: r.west, east: r.east, z,
    });

    // Elevation is fetched for the bounds the server actually covered, not the
    // bounds requested, so the lattice registers exactly to the imagery.
    let relief = null;
    if (state.relief > 0) {
      try {
        const seg = 129;
        const g = await api.terrainGrid({ ...m.bounds, width: seg, height: seg });
        relief = { ...g, exaggeration: state.relief };
        state.reliefStats = { minM: g.minM, maxM: g.maxM, res: g.resolutionM };
      } catch (e) {
        console.warn('relief unavailable', e);
      }
    }

    await globe.setDetailPatch(m.url, m.bounds, relief);
    URL.revokeObjectURL(m.url);
    lod.key = key;

    const rl = relief
      ? ` · relief ${state.relief}× (${Math.round(relief.minM)}…${Math.round(relief.maxM)} m)`
      : '';
    say(`z=${m.zoom} · ${m.mPerPx.toFixed(0)} m/px · ${m.tiles} tiles · ` +
        `${(m.bytes / 1024).toFixed(0)} KB${rl}`);
  } catch (err) {
    console.warn('LOD failed', err);
  } finally {
    lod.inflight = false;
  }
  // Labels and rims follow the same scale logic as the imagery.
  refreshNames();
  refreshCraters();
}

/* ── Chrome helpers ─────────────────────────────────────────────────────── */

let lastAlt = -1;

/**
 * Fit a scale bar to a round distance.
 *
 * The bar is sized from a 1-2-5 series so its label is always a number a reader
 * can halve or double in their head, rather than an arbitrary "137 km" that
 * happens to fit 120 pixels.
 */
function updateScaleBar() {
  const mpp = globe.metresPerPixel();
  if (!Number.isFinite(mpp) || mpp <= 0) return;

  const targetPx = 130;
  const raw = mpp * targetPx;
  const pow = Math.pow(10, Math.floor(Math.log10(raw)));
  const mant = raw / pow;
  const nice = (mant >= 5 ? 5 : mant >= 2 ? 2 : 1) * pow;

  const px = nice / mpp;
  $('scalebar').querySelector('.bar').style.width = `${px.toFixed(1)}px`;
  $('scale-label').textContent = nice >= 1000
    ? `${(nice / 1000).toLocaleString(undefined, { maximumFractionDigits: 0 })} km`
    : `${nice.toFixed(nice < 10 ? 1 : 0)} m`;
}

function onFrame() {
  const alt = globe.altitudeKm();
  $('st-alt').textContent = `alt ${alt < 10 ? alt.toFixed(2) : Math.round(alt)} km`;

  // Only react to real movement, not to every frame.
  if (lastAlt < 0 || Math.abs(alt - lastAlt) / Math.max(alt, 1) > 0.02) {
    lastAlt = alt;
    updateScaleBar();
    globe.updateGraticule();
    scheduleLOD();
  }
  if (state.renderer === 'cesium') { updateTileStats(); updateProvenance(); }

  // Report labels actually drawn, not labels fetched — collision culling
  // typically removes a third of them, and claiming otherwise is a small lie
  // told in a status bar.
  if (state.showNames) {
    const shown = globe.shownLabelCount();
    if (shown !== state.lastShown) {
      state.lastShown = shown;
      $('named-count').textContent = `${shown} shown`;
    }
  }
}

function say(msg) { $('st-msg').textContent = msg; }

function busy(on) {
  state.busy = on;
  document.body.style.cursor = on ? 'progress' : '';
}

function setLoading(msg) {
  $('loading').classList.remove('gone');
  $('loading-msg').textContent = msg;
}

function hideLoading() {
  $('loading').classList.add('gone');
  setTimeout(() => { $('loading').style.display = 'none'; }, 450);
}

/* ── Traverse planning ──────────────────────────────────────────────────
 *
 * The engine behind this panel was tested long before it had a UI. What the
 * panel adds is the two things a user cannot supply through an API: a region
 * chosen by looking at the Moon, and endpoints chosen by pointing at it.
 */

function planBounds() {
  const n = parseFloat($('aoi-n').value);
  const s = parseFloat($('aoi-s').value);
  const w = parseFloat($('aoi-w').value);
  const e = parseFloat($('aoi-e').value);
  if ([n, s, w, e].some(Number.isNaN)) return null;
  const b = { south: Math.min(s, n), north: Math.max(s, n), west: w, east: e };
  // Empty means "best local data". Resolution is decided by what covers the
  // region, not demanded up front — asking for detail the data cannot supply
  // is not an error, it is just a coarser answer.
  //
  // 'survey' asks for something deliberately coarser; anything else names a
  // source directly, which is how the streamed 30 m product is chosen without
  // it becoming the default and making every analysis a hundred times slower.
  const t = $('aoi-tier').value;
  if (t === 'survey') b.tier = t;
  else if (t) b.source = t;
  return b;
}

/**
 * Open the selected region in its own tab.
 *
 * The region travels in the URL rather than in memory, so the tab is a
 * reloadable, shareable reference to a specific piece of the Moon instead of a
 * view that dies with this session. It also means the globe keeps its own
 * state: choosing a region and reading one are different tasks, and the panel
 * here is too small to be the place a region is read carefully.
 */
function openRegionTab() {
  const b = planBounds();
  if (!b) { say('Set a region first.'); return; }
  const p = new URLSearchParams({
    south: b.south, north: b.north, west: b.west, east: b.east,
    rover: $('p-rover').value, soil: $('p-soil').value,
  });
  if (b.source) p.set('source', b.source);
  window.open(`region.html?${p}`, '_blank', 'noopener');
}


/**
 * Offer the places where topography finer than any global product exists.
 *
 * The Cesium globe cannot be re-textured from a local DEM — its surface is a
 * baked 3D Tileset — so the globe's role is to say *where* the detail is. The
 * footprints are small: the Apollo 15 strip is 28.6 x 5.1 km, which at full
 * zoom is a sliver, and nobody would find it by panning.
 */
async function buildHiResMenu() {
  const sel = $('aoi-hires');
  try {
    const { sites } = await api.coverage();
    if (!sites.length) { sel.style.display = 'none'; return; }
    sel.innerHTML = '<option value="">Jump to high-resolution data…</option>'
      + sites.map((s, i) =>
          `<option value="${i}">${s.cell_m} m · ${s.product_id.replace(/_/g, ' ')}`
          + `${s.supports_traverse ? ' — certifies a traverse' : ''}</option>`).join('');
    sel.addEventListener('change', () => {
      const s = sites[sel.value];
      if (!s) return;
      const b = s.bounds;
      // Land inside the footprint rather than on its edge: a box snapped to the
      // exact bounds has its border cells outside the data on every side.
      const padLat = (b.north - b.south) * 0.25;
      const padLon = (b.east - b.west) * 0.15;
      $('aoi-n').value = (b.north - padLat).toFixed(4);
      $('aoi-s').value = (b.south + padLat).toFixed(4);
      $('aoi-w').value = (b.west + padLon).toFixed(4);
      $('aoi-e').value = (b.east - padLon).toFixed(4);
      refreshAOIPreview();
      globe.flyTo?.(s.centre.lat, s.centre.lon);
      say(`${s.product_id} — ${s.cell_m} m. Open the region to see it.`);
    });
  } catch {
    sel.style.display = 'none';
  }
}


/**
 * Switch the Terrain view between relief and resolution.
 *
 * Only meaningful on Cesium: the Classic globe already draws our basemap over
 * LOLA relief and has nothing to trade. The button therefore appears only when
 * Cesium is live, rather than sitting inert on the other renderer.
 */
async function toggleSurface() {
  if (state.renderer !== 'cesium' || !cesium) return;
  // relief -> science -> imagery -> relief. Science sits next to relief on
  // purpose: they are the two that draw topography, and the interesting
  // comparison is between them.
  const order = ['relief', 'science', 'imagery'];
  const next = order[(order.indexOf(cesium.surfaceMode || 'relief') + 1) % 3];
  const b = state.basemaps.find((x) => x.key === state.basemap);
  if (next !== 'relief') await cesium.setBasemap(state.basemap, b?.max_zoom ?? 8);
  await cesium.setSurface(next);
  syncSurfaceButton();
  const bm = `${b?.title || state.basemap} at ${b?.served_m_px ?? '?'} m/px`;
  say({
    relief:  '3D Tiles relief — 83 m imagery, +1.8 km vs LOLA. View only.',
    science: `LOLA terrain at the correct datum, ${bm}. 2 m at Apollo 15, `
             + '10 m at the south pole, 473.8 m elsewhere.',
    imagery: `${bm} — sphere, no relief.`,
  }[next]);
  updateProvenance?.();
}

function syncSurfaceButton() {
  const btn = $('btn-surface');
  if (!btn) return;
  const on = state.renderer === 'cesium';
  btn.hidden = !on;
  if (!on) return;
  const m = cesium?.surfaceMode || 'relief';
  btn.textContent = { relief: 'Relief', science: 'Science', imagery: 'Imagery' }[m];
  btn.classList.toggle('on', m !== 'relief');
}

/** Ask what the region can support, and show it before anything is computed. */
async function refreshAOIPreview() {
  const b = planBounds();
  const el = $('aoi-preview');
  $('btn-aoi-open').disabled = true;
  if (!b) { el.textContent = 'Enter four bounds.'; return; }

  globe.setAOIBox(b);
  try {
    const p = await api.aoiPreview(b);
    if (!p.ok) {
      // Not an error: a region that cannot support the tier is a normal
      // answer, and the reason carries the fix.
      el.innerHTML = `<span style="color:#e9c46a">${p.reason}</span>`;
      return;
    }
    $('btn-aoi-open').disabled = false;
    const a = p.aoi, c = a.capability;
    el.innerHTML =
      `<b>${a.shape[0]} × ${a.shape[1]}</b> cells at <b>${a.cell_m} m</b> ` +
      `(${fmtInt(a.cells)} total) from ${a.source.product_id}<br>` +
      `Craters measurable from <b>${c.crater_measure_floor_m} m</b> · ` +
      `${c.supports_traverse ? 'can certify a traverse'
                             : 'corridor only — too coarse to certify a drive'}` +
      // Warnings only. Finer sources arrive as `alternatives`, and the
      // resolution menu directly above already lists them — repeating that in
      // alarm colour on every single region is how a reader learns to ignore
      // the notices that do matter.
      a.warnings.map((w) => `<br><span style="color:#e9c46a">${w}</span>`).join('');
  } catch (err) {
    el.textContent = err.message;
  }
}

function schedulePreview() {
  clearTimeout(plan.previewTimer);
  plan.previewTimer = setTimeout(refreshAOIPreview, 250);
}

function setPin(which, lat, lon) {
  plan[which] = { lat, lon };
  $(which === 'start' ? 's-lat' : 'g-lat').value = lat.toFixed(4);
  $(which === 'start' ? 's-lon' : 'g-lon').value = lon.toFixed(4);
  globe.setPins(plan.start, plan.goal);
}

function readPinInputs() {
  const rd = (a, b) => {
    const la = parseFloat($(a).value), lo = parseFloat($(b).value);
    return (Number.isNaN(la) || Number.isNaN(lo)) ? null : { lat: la, lon: lo };
  };
  plan.start = rd('s-lat', 's-lon');
  plan.goal = rd('g-lat', 'g-lon');
  globe.setPins(plan.start, plan.goal);
}

/**
 * Drag a rectangle on the globe to define the region.
 *
 * Written once against `pickLatLon` / `setInteractive` rather than twice per
 * renderer. Both expose the same two methods, so this works on the Classic
 * globe and the Cesium terrain without knowing which is live — and a region
 * drawn in one view is still there after switching to the other.
 *
 * The camera is suspended for the duration: dragging a box and orbiting are
 * the same gesture, and without this the Moon turns under the pointer and the
 * box lands somewhere nobody chose.
 */
function armRegionDrag() {
  plan.dragging = !plan.dragging;
  $('btn-aoi-drag').classList.toggle('armed', plan.dragging);

  if (!plan.dragging) {
    detachRegionDrag();
    say('Region drawing cancelled.');
    return;
  }

  // Placing a pin and drawing a region are different intents; arming one must
  // disarm the other or the next click means two things at once.
  if (plan.picking) armPicker(plan.picking);

  globe.setInteractive(false);
  const el = globe.inputElement;
  let anchor = null;

  const finish = (ok) => {
    detachRegionDrag();
    plan.dragging = false;
    $('btn-aoi-drag').classList.remove('armed');
    say(ok ? 'Region selected.' : 'Region drawing cancelled.');
  };

  const onDown = (ev) => {
    const c = globe.pickLatLon(ev);
    if (!c) { say('Start the drag on the lit surface, not off the limb.'); return; }
    anchor = c;
    ev.preventDefault();
  };

  const onMove = (ev) => {
    if (!anchor) return;
    const c = globe.pickLatLon(ev);
    if (!c) return;
    applyDraggedBounds(anchor, c, false);
  };

  const onUp = (ev) => {
    if (!anchor) { finish(false); return; }
    const c = globe.pickLatLon(ev) || anchor;
    applyDraggedBounds(anchor, c, true);
    anchor = null;
    finish(true);
  };

  const onKey = (ev) => { if (ev.key === 'Escape') { anchor = null; finish(false); } };

  plan.dragHandlers = { el, onDown, onMove, onUp, onKey };
  el.addEventListener('pointerdown', onDown);
  el.addEventListener('pointermove', onMove);
  el.addEventListener('pointerup', onUp);
  window.addEventListener('keydown', onKey);
  el.style.cursor = 'crosshair';
  say('Drag a rectangle on the Moon. Esc to cancel.');
}

function detachRegionDrag() {
  const h = plan.dragHandlers;
  if (!h) return;
  h.el.removeEventListener('pointerdown', h.onDown);
  h.el.removeEventListener('pointermove', h.onMove);
  h.el.removeEventListener('pointerup', h.onUp);
  window.removeEventListener('keydown', h.onKey);
  h.el.style.cursor = '';
  plan.dragHandlers = null;
  globe.setInteractive(true);
}

/**
 * Turn two dragged corners into bounds.
 *
 * Longitude takes the *short way round*: two points 10 degrees apart must give
 * a 10 degree region, not the 350 degree one that sorting the raw values would
 * produce whenever the drag happens to straddle the 0/360 seam.
 */
function applyDraggedBounds(a, b, commit) {
  const south = Math.min(a.lat, b.lat);
  const north = Math.max(a.lat, b.lat);
  let west = a.lon, east = b.lon;
  const forward = ((east - west) % 360 + 360) % 360;
  if (forward > 180) { const t = west; west = east; east = t; }

  $('aoi-s').value = south.toFixed(3);
  $('aoi-n').value = north.toFixed(3);
  $('aoi-w').value = west.toFixed(3);
  $('aoi-e').value = east.toFixed(3);

  // While dragging, only redraw the box — the preview is a network call and
  // firing one per pointer-move would flood the server for no benefit.
  globe.setAOIBox({ south, north, west, east });
  if (commit) refreshAOIPreview();
}

function armPicker(which) {
  // Drawing a region and placing a pin both consume the next click on the
  // globe, so arming either has to disarm the other.
  if (plan.dragging) armRegionDrag();

  plan.picking = plan.picking === which ? null : which;
  $('btn-pick-start').classList.toggle('armed', plan.picking === 'start');
  $('btn-pick-goal').classList.toggle('armed', plan.picking === 'goal');
  say(plan.picking
    ? `Click the Moon to place the ${plan.picking}.`
    : 'Picking cancelled.');
}

async function runPlan() {
  const b = planBounds();
  if (!b) { say('Set the region bounds first.'); return; }
  readPinInputs();
  if (!plan.start || !plan.goal) { say('Set both a start and a goal.'); return; }

  const choice = $('p-algos').value;
  const algorithms =
    choice === 'fast' ? plan.options.fast_algorithms
    : choice === 'all' ? plan.options.algorithms.map((a) => a.key)
    : plan.options.default_algorithms;

  const body = {
    ...b,
    start_lat: plan.start.lat, start_lon: plan.start.lon,
    goal_lat: plan.goal.lat, goal_lon: plan.goal.lon,
    rover: $('p-rover').value,
    soil: $('p-soil').value,
    risk_aversion: parseFloat($('p-gamma').value),
    algorithms,
  };

  const btn = $('btn-plan');
  btn.disabled = true;
  $('plan-out').hidden = true;
  $('plan-status').textContent = 'Submitting…';

  try {
    const sub = await api.submitPlan(body);
    const job = await api.awaitJob(sub.job.id, {
      onProgress: (j) => {
        $('plan-status').textContent =
          `${j.message} — ${Math.round(j.progress * 100)}% (${j.elapsed_s}s)`;
      },
    });
    plan.result = job.result;
    renderPlan(job.result);
    $('plan-status').textContent = `Done in ${job.elapsed_s}s.`;
  } catch (err) {
    $('plan-status').innerHTML = `<span style="color:#e07a5a">${err.message}</span>`;
    say(err.message);
  } finally {
    btn.disabled = false;
  }
}

function renderPlan(r) {
  $('plan-out').hidden = false;

  const traverse = r.certification === 'traverse';
  const cert = $('plan-cert');
  cert.className = `cert ${traverse ? 'traverse' : 'corridor'}`;
  cert.textContent = traverse ? 'Rover traverse' : 'Regional corridor only';

  $('plan-rec').innerHTML =
    `<b>${r.recommended.algorithm}</b> — ${r.recommended.why}` +
    (traverse ? '' : `<br><br>${r.certification_note}`);

  // Draw before the numbers: the map is what the eye checks first.
  const latlon = r.route.lat.map((la, i) => [la, r.route.lon[i]]);
  globe.setRoute(latlon, r.route.profile.risk);
  globe.setPins(
    { lat: r.endpoints.start.used.lat, lon: r.endpoints.start.used.lon },
    { lat: r.endpoints.goal.used.lat, lon: r.endpoints.goal.used.lon },
  );

  const best = r.algorithms.find((a) => a.key === r.recommended.key);
  const m = best?.metrics || {};
  const prof = r.route.profile;
  const km = prof.distance_m[prof.distance_m.length - 1] / 1000;
  const moved = r.endpoints.start.moved_m + r.endpoints.goal.moved_m;

  const rows = [
    ['Distance', `${km.toFixed(2)} km`],
    ['Waypoints', `${r.route.waypoints} (${r.route.samples} samples)`],
    ['Max slope', `${Math.max(...prof.slope_deg).toFixed(1)}°`],
    ['Peak risk', Math.max(...prof.risk).toFixed(3)],
    ['Peak slip', `${(Math.max(...prof.slip) * 100).toFixed(1)}%`],
    ['Rover / soil', `${r.rover} · ${r.soil.split('(')[0].trim()}`],
  ];
  if (m.safety) rows.push(['Safety score', `${m.safety.score} — ${m.safety.limiting_factor}`]);
  if (m.time_s) rows.push(['Traverse time', `${(m.time_s / 3600).toFixed(1)} h`]);
  if (moved > 0) {
    rows.push(['Endpoints moved', `${moved.toFixed(0)} m onto passable ground`]);
  }
  $('plan-summary').innerHTML = rows
    .map(([k, v]) => `<div class="k">${k}</div><div class="v">${v}</div>`).join('');

  const t = $('plan-table');
  t.innerHTML =
    '<tr><th>Algorithm</th><th>Cost s</th><th>×opt</th><th>ms</th><th>Nodes</th></tr>'
    + r.algorithms.map((a) => `
      <tr class="${a.key === r.recommended.key ? 'rec' : ''}">
        <td>${a.algorithm}</td>
        <td>${a.found ? a.cost_s.toFixed(0) : '—'}</td>
        <td>${a.cost_ratio ?? '—'}</td>
        <td>${a.runtime_ms.toFixed(0)}</td>
        <td>${fmtInt(a.nodes_expanded)}</td>
      </tr>`).join('');

  drawProfile(prof);
  say(`Route planned: ${km.toFixed(2)} km, ${r.certification}.`);
}

/**
 * Elevation and slope against distance (FR-4.5 / 4.6).
 *
 * Plotted against ground distance rather than sample index: any-angle routes
 * have unevenly spaced waypoints, and indexing them would stretch the sparse
 * stretches and compress the dense ones — exactly where the terrain matters.
 */
function drawProfile(p) {
  const cv = $('plan-profile');
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth || 300, H = 150;
  cv.width = W * dpr; cv.height = H * dpr;
  const g = cv.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, W, H);

  const d = p.distance_m, e = p.elevation_m, s = p.slope_deg;
  if (!d || d.length < 2) return;
  const pad = { l: 34, r: 30, t: 8, b: 18 };
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const dmax = d[d.length - 1] || 1;
  const emin = Math.min(...e), emax = Math.max(...e);
  const espan = (emax - emin) || 1;
  const smax = Math.max(10, Math.max(...s));

  const X = (v) => pad.l + (v / dmax) * iw;
  const Ye = (v) => pad.t + ih - ((v - emin) / espan) * ih;
  const Ys = (v) => pad.t + ih - (v / smax) * ih;

  g.strokeStyle = 'rgba(255,255,255,.08)';
  g.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = pad.t + (ih * i) / 4;
    g.beginPath(); g.moveTo(pad.l, y); g.lineTo(W - pad.r, y); g.stroke();
  }

  // Elevation as a filled band — the shape of the ground.
  g.beginPath();
  g.moveTo(X(d[0]), pad.t + ih);
  for (let i = 0; i < d.length; i++) g.lineTo(X(d[i]), Ye(e[i]));
  g.lineTo(X(d[d.length - 1]), pad.t + ih);
  g.closePath();
  g.fillStyle = 'rgba(125,192,255,.16)';
  g.fill();
  g.beginPath();
  for (let i = 0; i < d.length; i++) {
    (i ? g.lineTo : g.moveTo).call(g, X(d[i]), Ye(e[i]));
  }
  g.strokeStyle = '#7dc0ff'; g.lineWidth = 1.4; g.stroke();

  // Slope on its own scale, so a gentle climb and a scarp are distinguishable.
  g.beginPath();
  for (let i = 0; i < d.length; i++) {
    (i ? g.lineTo : g.moveTo).call(g, X(d[i]), Ys(s[i]));
  }
  g.strokeStyle = '#e9c46a'; g.lineWidth = 1.1; g.stroke();

  g.fillStyle = '#8a93a3';
  g.font = '9px ui-monospace, monospace';
  g.fillText(`${emax.toFixed(0)} m`, 2, pad.t + 7);
  g.fillText(`${emin.toFixed(0)} m`, 2, pad.t + ih);
  g.fillText(`${smax.toFixed(0)}°`, W - pad.r + 3, pad.t + 7);
  g.fillText('0°', W - pad.r + 3, pad.t + ih);
  g.fillText(`${(dmax / 1000).toFixed(1)} km`, W - pad.r - 26, H - 5);
  g.fillText('0', pad.l, H - 5);

  $('profile-legend').innerHTML =
    '<span style="color:#7dc0ff">— elevation</span> &nbsp; ' +
    '<span style="color:#e9c46a">— slope</span> &nbsp; ' +
    `sampled every ${(dmax / (d.length - 1)).toFixed(0)} m along the ground`;
}

function buildPlanPanel(opts) {
  plan.options = opts;

  $('p-rover').innerHTML = opts.rovers
    .map((r) => `<option value="${r.key}">${r.name}</option>`).join('');
  $('p-rover').value = 'viper';
  $('p-soil').innerHTML = opts.soils
    .map((s) => `<option value="${s.key}">${s.label}</option>`).join('');
  $('p-gamma').value = opts.risk_aversion_default;
  $('out-gamma').textContent = Number(opts.risk_aversion_default).toFixed(1);

  for (const id of ['aoi-n', 'aoi-s', 'aoi-w', 'aoi-e']) {
    $(id).addEventListener('input', schedulePreview);
  }
  $('aoi-tier').addEventListener('change', refreshAOIPreview);
  $('btn-aoi-view').addEventListener('click', () => {
    const v = globe.visibleRegion();
    if (!v) { say('Zoom in until a region is in view.'); return; }
    $('aoi-n').value = v.north.toFixed(3);
    $('aoi-s').value = v.south.toFixed(3);
    $('aoi-w').value = v.west.toFixed(3);
    $('aoi-e').value = v.east.toFixed(3);
    refreshAOIPreview();
  });

  $('btn-aoi-open').addEventListener('click', openRegionTab);
  $('btn-surface')?.addEventListener('click', toggleSurface);
  buildHiResMenu();
  $('btn-aoi-drag').addEventListener('click', armRegionDrag);
  $('btn-pick-start').addEventListener('click', () => armPicker('start'));
  $('btn-pick-goal').addEventListener('click', () => armPicker('goal'));
  for (const id of ['s-lat', 's-lon', 'g-lat', 'g-lon']) {
    $(id).addEventListener('change', readPinInputs);
  }
  $('p-gamma').addEventListener('input', (ev) => {
    $('out-gamma').textContent = Number(ev.target.value).toFixed(1);
  });
  $('btn-plan').addEventListener('click', runPlan);

  refreshAOIPreview();
}

boot();
