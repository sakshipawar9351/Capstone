/**
 * Region analysis — the detail view a selection opens into.
 *
 * The globe is for choosing a region; this page is for reading one. Everything
 * the analysis produces and the side panel had no room for lives here: all
 * eight derived layers over the same ground at the same posting, the statistics
 * behind them, what the region can and cannot support, and a planner.
 *
 * The region arrives entirely in the URL, so a tab is a shareable, reloadable
 * reference to a specific piece of the Moon rather than a transient view. Two
 * people can look at the same analysis by exchanging a link.
 */

import { api, fmtCoord, fmtInt, fmtLen } from './api.js';
import { RegionSurface } from './region3d.js';

const $ = (id) => document.getElementById(id);
const q = new URLSearchParams(location.search);

const bounds = {
  south: parseFloat(q.get('south')),
  north: parseFloat(q.get('north')),
  west: parseFloat(q.get('west')),
  east: parseFloat(q.get('east')),
};
const source = q.get('source') || undefined;

// The region page asks for the best data that exists here, not the fastest.
// Measured against the Apollo, Lunokhod and Yutu sites, a 473.8 m posting
// understates 99th-percentile slope by 2.7 to 5.5 times and reports terrain as
// uniformly gentle when it holds slopes past a rover's tip-over limit. The
// globe's preview stays on local data so dragging a box is instant; here the
// reader has committed to one region, and tens of seconds buys a hazard map
// that is about the ground rather than about the gridding.
const state_finest = q.get('finest') !== '0';

const state = { aoi: null, catalogue: null, surface: null, drapeUrl: null };

function layerUrl(layer) {
  return api.layerUrl({
    ...bounds, layer, source, finest: state_finest,
    rover: $('r-rover').value, soil: $('r-soil').value,
  });
}

function fail(msg) {
  $('r-bounds').textContent = msg;
  $('cap-body').innerHTML = `<span style="color:#e07a5a">${msg}</span>`;
}

async function boot() {
  if (Object.values(bounds).some(Number.isNaN)) {
    fail('No region in the URL. Open this page from the globe.');
    return;
  }
  document.title =
    `${bounds.south.toFixed(2)}..${bounds.north.toFixed(2)}° — LunarSerpent`;

  const [opts, cat] = await Promise.all([api.planOptions(), api.layerCatalogue()]);
  state.catalogue = cat;

  $('r-rover').innerHTML = opts.rovers
    .map((r) => `<option value="${r.key}">${r.name}</option>`).join('');
  $('r-soil').innerHTML = opts.soils
    .map((s) => `<option value="${s.key}">${s.label}</option>`).join('');
  // Carry the globe's own choices across, so the tab opens showing the same
  // vehicle and regolith the region was previewed under rather than resetting
  // to a default and quietly answering a different question.
  const has = (sel, v) => v && [...sel.options].some((o) => o.value === v);
  $('r-rover').value = has($('r-rover'), q.get('rover')) ? q.get('rover') : 'viper';
  $('r-soil').value = has($('r-soil'), q.get('soil')) ? q.get('soil') : 'nominal';

  renderLegend(cat);
  buildSurfaceControls(cat);
  $('r-reload').addEventListener('click', run);
  // Rover and regolith are not display settings: they change slope limits,
  // slip, hazard and cost, so every map and statistic below is re-derived.
  $('r-rover').addEventListener('change', run);
  $('r-soil').addEventListener('change', run);
  $('r-plan').addEventListener('click', runPlan);
  await run();
}

async function run() {
  const p = await api.aoiPreview({ ...bounds, source, finest: state_finest });
  if (!p.ok) { fail(p.reason); return; }
  state.aoi = p.aoi;
  const a = p.aoi, c = a.capability;

  $('r-bounds').textContent =
    `${fmtCoord(a.centre.lat, a.centre.lon)} · ` +
    `${a.extent_km[0].toFixed(1)} × ${a.extent_km[1].toFixed(1)} km · ` +
    `${a.shape[0]}×${a.shape[1]} cells at ${a.cell_m} m · ${a.source.product_id}`;

  // Capability before maps: what the region can support governs how every
  // picture below should be read.
  $('cap-body').innerHTML = [
    ['Posting', `${a.cell_m} m`],
    ['Cells', fmtInt(a.cells)],
    ['Source', `${a.source.product_id} (${a.source.kind.replace('_', ' ')})`],
    ['Craters detectable', fmtLen(c.crater_detect_floor_m)],
    ['Craters measurable', fmtLen(c.crater_measure_floor_m)],
    ['Rover footprint', `${c.rover_footprint_px} px`],
    ['Certifies a traverse', c.supports_traverse ? 'yes' : 'no — corridor only'],
    ['Boulders', 'out of reach — see below'],
  ].map(([k, v]) => `<div class="k">${k}</div><div class="v">${v}</div>`).join('');

  const notes = [
    // Scope, stated with a number rather than asserted. Boulders are the
    // classic rover hazard and their absence has to be justified, not just
    // declared — at this posting a 1 m rock is a fraction of one percent of a
    // cell, so no amount of processing recovers it and saying so is the
    // honest answer.
    `<div class="note">${c.boulder_note}</div>`,
    ...a.warnings.map((w) => `<div class="note" style="color:#e9c46a">${w}</div>`),
    ...(a.alternatives || []).map((x) =>
      `<div class="note">Finer available: <b>${x.product_id}</b> at ${x.cell_m} m
       (${x.finer_by}× finer, ${x.access}).</div>`),
  ];
  $('cap-notes').innerHTML = notes.join('');

  renderLayers();
  renderSurface();
  await renderStats();
}

/* ── The region as a surface ───────────────────────────────────────────── */

function buildSurfaceControls(cat) {
  // Imagery first, because "what does this place look like" is the question
  // the 3D view is usually opened to answer; the analysis layers follow,
  // because draping hazard over relief is what turns two pictures into one
  // judgement — a red patch on a map is a warning, a red patch on a wall is
  // a reason.
  $('r3d-drape').innerHTML =
    '<option value="photo">Kaguya imagery (20.8 m)</option>' +
    '<option value="">Plain relief shading</option>' +
    cat.layers.filter((l) => l.key !== 'elevation')
      .map((l) => `<option value="${l.key}">${l.label}</option>`).join('');
  // Honour a drape named in the URL, so a link can point at one reading of the
  // region — "look at the hazard classes draped over the relief" — rather than
  // at the region and a set of clicks to perform once you arrive.
  const want = q.get('drape');
  const opts = [...$('r3d-drape').options].map((o) => o.value);
  $('r3d-drape').value =
    want !== null && opts.includes(want) ? want : 'photo';

  $('r3d-drape').addEventListener('change', applyDrape);
  $('r3d-exag').addEventListener('input', (ev) => {
    setExag(Number(ev.target.value));
  });
  $('r3d-true').addEventListener('click', () => {
    $('r3d-exag').value = 1;
    setExag(1);
  });
  $('r3d-reset').addEventListener('click', () => state.surface?.frame());
}

function setExag(f) {
  state.surface?.setExaggeration(f);
  const el = $('r3d-vx');
  el.textContent = `${f}× vertical`;
  el.classList.toggle('true', f === 1);
}

async function renderSurface() {
  const st = $('r3d-status');
  st.className = '';
  st.textContent = 'building the surface…';
  try {
    if (!state.surface) state.surface = new RegionSurface($('r3d'));
    const m = await state.surface.load(bounds, { source, finest: state_finest });
    st.className = 'gone';

    const f = state.surface.exaggeration;
    $('r3d-exag').value = Math.min(60, f);
    setExag(f);

    await applyDrape();
    writeSurfaceCaption();
  } catch (e) {
    st.className = 'err';
    st.textContent = e.message;
  }
}

/**
 * Say what was actually drawn, including where the picture is finer than the
 * measurement.
 *
 * This is the caption that matters most on the page. A 20.8 m orthomosaic
 * draped over a 474 m DEM looks like detailed terrain, and it is not: the
 * craters visible in the imagery are *not* in the elevation model, so they are
 * not in the slope map, not in the hazard classes, and not in any route
 * planned across them. Someone reading relief into that drape would be reading
 * a landscape the analysis has never seen. So when the two postings differ by
 * more than about double, the caption says so in as many words.
 */
function writeSurfaceCaption() {
  const m = state.surface?.meta;
  if (!m) return;
  const drawn = m.stride > 1
    ? `drawn at ${m.cellM.toFixed(0)} m from ${m.nativeCellM.toFixed(0)} m data `
      + `(every ${m.stride}${['', 'st', 'nd', 'rd'][m.stride] || 'th'} cell, `
      + 'sampled not averaged, so scarps survive)'
    : `every analysed cell, at ${m.cellM.toFixed(0)} m`;

  let text =
    `${fmtInt(m.indices.length / 3)} triangles · ${drawn} · `
    + `${m.reliefM.toFixed(0)} m of relief across `
    + `${(Math.max(m.extentM.x, m.extentM.y) / 1000).toFixed(1)} km · `
    + `${m.source}. Shading comes from the surface normal, not from a sun — `
    + 'there is no illumination model here, so nothing is hidden in shadow.';

  const d = state.drapeInfo;
  const el = $('r3d-cap');
  el.textContent = text;
  if (d?.mPerPx && d.mPerPx * 2 < m.cellM) {
    const warn = document.createElement('span');
    warn.className = 'mismatch';
    warn.textContent =
      ` The ${d.label} is ${(m.cellM / d.mPerPx).toFixed(0)}× finer than the `
      + `elevation model beneath it. Craters you can see in it are not in the `
      + `${m.cellM.toFixed(0)} m DEM, so they are not in the slope, hazard or `
      + `cost maps either, and no route avoids them. Read this drape as a `
      + `photograph laid over the terrain, not as measured relief.`;
    el.appendChild(warn);
  }
}

async function applyDrape() {
  const surf = state.surface;
  if (!surf?.meta) return;
  const choice = $('r3d-drape').value;

  if (state.drapeUrl) { URL.revokeObjectURL(state.drapeUrl); state.drapeUrl = null; }
  state.drapeInfo = null;
  if (!choice) { surf.setDrape(null); writeSurfaceCaption(); return; }

  if (choice !== 'photo') {
    // An analysis layer is the analysed grid itself, so it is never finer than
    // the terrain it is draped on and needs no caveat.
    surf.setDrape(layerUrl(choice));
    state.drapeInfo = { label: choice, mPerPx: surf.meta.cellM };
    writeSurfaceCaption();
    return;
  }

  // Imagery is fetched rather than linked so the *covered* bounds can be
  // checked. The mosaic snaps outward to whole tiles, so the patch is wider
  // than the region; the excess is cropped here, because stretching the whole
  // tile-aligned image across the mesh would slide the imagery off the ground
  // it belongs to by up to one tile.
  try {
    const m = await api.mosaic('kaguya_tc', { ...bounds, z: 10 });
    state.drapeUrl = await cropToBounds(m.url, m.bounds, bounds);
    URL.revokeObjectURL(m.url);
    surf.setDrape(state.drapeUrl);
    state.drapeInfo = { label: 'Kaguya orthomosaic', mPerPx: m.mPerPx };
  } catch (e) {
    surf.setDrape(null);
    state.drapeInfo = { label: 'imagery', error: e.message };
  }
  writeSurfaceCaption();
}

/** Cut the AOI's own footprint out of a tile-aligned mosaic. */
function cropToBounds(url, got, want) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const fx = (lon) => (lon - got.west) / (got.east - got.west);
      const fy = (lat) => (got.north - lat) / (got.north - got.south);
      const x0 = fx(want.west) * img.width, x1 = fx(want.east) * img.width;
      const y0 = fy(want.north) * img.height, y1 = fy(want.south) * img.height;
      const cv = document.createElement('canvas');
      cv.width = Math.max(1, Math.round(x1 - x0));
      cv.height = Math.max(1, Math.round(y1 - y0));
      cv.getContext('2d').drawImage(
        img, x0, y0, x1 - x0, y1 - y0, 0, 0, cv.width, cv.height);
      cv.toBlob((b) => resolve(URL.createObjectURL(b)), 'image/png');
    };
    img.onerror = () => reject(new Error('the imagery patch failed to decode'));
    img.src = url;
  });
}

function renderLayers() {
  const grid = $('r-layers');
  grid.innerHTML = '';
  for (const l of state.catalogue.layers) {
    const el = document.createElement('div');
    el.className = 'layer';
    // The ramp comes from the server, per layer, because they are not all
    // drawn the same way — elevation is a neutral relief ramp and hillshade is
    // grey. One hardcoded key under every picture would caption three of the
    // eight with colours that never appear in them.
    const ramp = l.ramp
      ? `<div class="ramp" style="background:linear-gradient(90deg,${l.ramp})"></div>`
      : '';
    el.innerHTML =
      `<img alt="${l.label} map of this region" loading="lazy">` +
      `<div class="cap"><b>${l.label}</b>` +
      `<div class="rng">rendering…</div>${ramp}` +
      `<div class="why">${l.note}</div></div>`;
    grid.appendChild(el);

    const img = el.querySelector('img');
    const rng = el.querySelector('.rng');
    // fetch rather than src=, so the scaling range in the headers can be shown
    // beside the picture — a colour with no numbers attached is decoration.
    fetch(layerUrl(l.key))
      .then(async (res) => {
        if (!res.ok) throw new Error((await res.json()).detail || res.status);
        const lo = res.headers.get('X-Range-Low');
        const hi = res.headers.get('X-Range-High');
        const unit = res.headers.get('X-Unit');
        rng.textContent = `${lo} .. ${hi} ${unit}`;
        img.src = URL.createObjectURL(await res.blob());
      })
      .catch((e) => { el.className = 'layer err'; el.textContent = `${l.label}: ${e.message}`; });
  }
}

async function renderStats() {
  const box = $('r-stats');
  box.textContent = 'analysing…';
  try {
    const sub = await api.submitAnalysis({
      ...bounds, source, finest: state_finest,
      rover: $('r-rover').value, soil: $('r-soil').value,
    });
    const job = await api.awaitJob(sub.job.id, {
      onProgress: (j) => { box.textContent = `${j.message}… ${j.elapsed_s}s`; },
    });
    const t = job.result.traversability, w = job.result.window;
    if (!w.valid) {
      box.innerHTML = '<span style="color:#e07a5a">No elevation was returned ' +
        'for this region — every cell is unmeasured.</span>';
      return;
    }
    const rows = [
      [`${w.relief_m.toFixed(0)} m`, 'relief'],
      [`${w.min_m.toFixed(0)} .. ${w.max_m.toFixed(0)} m`, 'elevation range'],
      [`${t.slope_deg.mean.toFixed(2)}°`, 'mean slope'],
      [`${t.slope_deg.max.toFixed(1)}°`, 'max slope'],
      [`${t.slope_deg.p99.toFixed(1)}°`, '99th percentile slope'],
      [`${(t.passable_fraction * 100).toFixed(2)}%`, 'passable'],
      [`${(t.slip.p90).toFixed(3)}`, 'slip, 90th percentile'],
      [`${(t.binding_constraint.traction * 100).toFixed(1)}%`, 'traction-bound cells'],
    ];
    box.innerHTML = rows
      .map(([v, l]) => `<div class="s"><div class="v">${v}</div><div class="l">${l}</div></div>`)
      .join('');
  } catch (e) {
    box.innerHTML = `<span style="color:#e07a5a">${e.message}</span>`;
  }
}

function renderLegend(cat) {
  $('r-legend').innerHTML = cat.hazard_classes.map((h) =>
    `<div class="li"><span class="sw" style="background:${h.colour}"></span>` +
    `<span class="lt">${h.label}<small>${h.meaning}</small></span></div>`).join('');
}

async function runPlan() {
  const rd = (a, b) => {
    const la = parseFloat($(a).value), lo = parseFloat($(b).value);
    return (Number.isNaN(la) || Number.isNaN(lo)) ? null : [la, lo];
  };
  const s = rd('r-slat', 'r-slon');
  const g = rd('r-glat', 'r-glon');
  if (!s || !g) { $('r-planstatus').textContent = 'Enter both endpoints.'; return; }

  $('r-plan').disabled = true;
  $('r-planout').hidden = true;
  try {
    const sub = await api.submitPlan({
      ...bounds, source, finest: state_finest,
      start_lat: s[0], start_lon: s[1], goal_lat: g[0], goal_lon: g[1],
      rover: $('r-rover').value, soil: $('r-soil').value,
    });
    const job = await api.awaitJob(sub.job.id, {
      onProgress: (j) => {
        $('r-planstatus').textContent =
          `${j.message} — ${Math.round(j.progress * 100)}% (${j.elapsed_s}s)`;
      },
    });
    const r = job.result;
    $('r-planout').hidden = false;
    $('r-cert').className = `cert ${r.certification === 'traverse' ? 'traverse' : 'corridor'}`;
    $('r-cert').textContent =
      r.certification === 'traverse' ? 'Rover traverse' : 'Regional corridor only';
    $('r-rec').innerHTML = `<b>${r.recommended.algorithm}</b> — ${r.recommended.why}`;
    $('r-table').innerHTML =
      '<tr><th>Algorithm</th><th>Cost s</th><th>×opt</th><th>Nodes</th></tr>' +
      r.algorithms.map((a) => `
        <tr class="${a.key === r.recommended.key ? 'rec' : ''}">
          <td>${a.algorithm}</td><td>${a.found ? a.cost_s.toFixed(0) : '—'}</td>
          <td>${a.cost_ratio ?? '—'}</td><td>${fmtInt(a.nodes_expanded)}</td>
        </tr>`).join('');
    const km = r.route.profile.distance_m[r.route.profile.distance_m.length - 1] / 1000;
    $('r-planstatus').textContent =
      `${km.toFixed(2)} km, ${r.route.waypoints} waypoints, done in ${job.elapsed_s}s.`;
  } catch (e) {
    $('r-planstatus').innerHTML = `<span style="color:#e07a5a">${e.message}</span>`;
  } finally {
    $('r-plan').disabled = false;
  }
}

boot();
