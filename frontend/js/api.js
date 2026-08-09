/** LunarSerpent — typed-ish client for the analysis API. */

const BASE = '/api/v1';

async function get(path, params) {
  const url = new URL(BASE + path, window.location.origin);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null) url.searchParams.set(k, v);
    }
  }
  const res = await fetch(url);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* non-JSON */ }
    throw new Error(`${res.status} — ${detail}`);
  }
  return res.json();
}

export const api = {
  health: () => get('/meta/health'),
  layers: () => get('/meta/layers'),

  textureUrl: (layer, z = 3) => `${BASE}/texture/${layer}?z=${z}`,

  /**
   * Fetch a high-resolution mosaic for one window.
   *
   * Returns a blob URL plus the bounds the server *actually* covered — which
   * are snapped outward to whole tile edges and may differ from what was
   * requested. Placing the patch with the requested bounds instead of these
   * would smear the imagery by up to one tile.
   */
  async mosaic(layer, { south, north, west, east, z }) {
    const url = new URL(`${BASE}/mosaic/${layer}`, window.location.origin);
    url.searchParams.set('south', south);
    url.searchParams.set('north', north);
    url.searchParams.set('west', west);
    url.searchParams.set('east', east);
    url.searchParams.set('z', z);

    const res = await fetch(url);
    if (!res.ok) throw new Error(`mosaic ${res.status}`);
    const blob = await res.blob();
    const h = res.headers;
    return {
      url: URL.createObjectURL(blob),
      bounds: {
        south: parseFloat(h.get('X-Bounds-South')),
        north: parseFloat(h.get('X-Bounds-North')),
        west: parseFloat(h.get('X-Bounds-West')),
        east: parseFloat(h.get('X-Bounds-East')),
      },
      zoom: parseInt(h.get('X-Zoom'), 10),
      tiles: parseInt(h.get('X-Tiles'), 10),
      mPerPx: parseFloat(h.get('X-Metres-Per-Pixel')),
      bytes: blob.size,
    };
  },

  cratersBbox: (o) => get('/craters/bbox', {
    south: o.south, north: o.north, west: o.west, east: o.east,
    min_diameter_km: o.minDiameterKm, limit: o.limit,
  }),
  cratersLargest: (n = 200) => get('/craters/largest', { n }),
  cratersAt: (lat, lon) => get('/craters/at', { lat, lon }),

  featuresNamed: (o) => get('/features/named', {
    south: o.south, north: o.north, west: o.west, east: o.east,
    min_diameter_km: o.minDiameterKm, kinds: o.kinds, limit: o.limit,
  }),
  featureKinds: () => get('/features/kinds'),
  discover: () => get('/discover'),
  cesiumConfig: () => get('/meta/cesium'),
  discoveries: (o = {}) => get('/discoveries', o),
  missions: (o = {}) => get('/missions', o),
  mission: (key) => get(`/missions/${encodeURIComponent(key)}`),
  featureSearch: (q, limit = 20) => get('/features/search', { q, limit }),
  featureAnalyse: (o) => get('/features/analyse', {
    name: o.name, lat: o.lat, lon: o.lon, diameter_km: o.diameterKm,
  }),

  /**
   * Elevation lattice for a region, as raw float32.
   *
   * Row-major, north row first, west column first, edges inclusive — the same
   * vertex order THREE.SphereGeometry produces, so sample i displaces vertex i
   * directly.
   */
  async terrainGrid({ south, north, west, east, width, height }) {
    const url = new URL(`${BASE}/terrain/grid`, window.location.origin);
    for (const [k, v] of Object.entries(
      { south, north, west, east, width, height })) {
      url.searchParams.set(k, v);
    }
    const res = await fetch(url);
    if (!res.ok) throw new Error(`terrain grid ${res.status}`);
    const buf = await res.arrayBuffer();
    const h = res.headers;
    return {
      data: new Float32Array(buf),
      width: parseInt(h.get('X-Width'), 10),
      height: parseInt(h.get('X-Height'), 10),
      minM: parseFloat(h.get('X-Min-M')),
      maxM: parseFloat(h.get('X-Max-M')),
      resolutionM: parseFloat(h.get('X-Resolution-M-Px')),
      source: h.get('X-Source'),
    };
  },

  terrainPoint: (lat, lon) => get('/terrain/point', { lat, lon }),
  terrainWindow: (o) => get('/terrain/window', o),

  distance: (a, b) => get('/geodesy/distance', {
    lat1: a.lat, lon1: a.lon, lat2: b.lat, lon2: b.lon,
  }),
};

/* ── Formatting helpers ─────────────────────────────────────────────────── */

/** Latitude/longitude in the conventional hemispheric form. */
export function fmtCoord(lat, lon) {
  const ns = lat >= 0 ? 'N' : 'S';
  const l = ((lon % 360) + 360) % 360;
  return `${Math.abs(lat).toFixed(3)}°${ns}, ${l.toFixed(3)}°E`;
}

export function fmtLen(m) {
  if (m === null || m === undefined || Number.isNaN(m)) return '—';
  const a = Math.abs(m);
  if (a >= 1000) return `${(m / 1000).toFixed(2)} km`;
  return `${m.toFixed(1)} m`;
}

export function fmtArea(km2) {
  if (km2 === null || km2 === undefined) return '—';
  if (km2 >= 1e6) return `${(km2 / 1e6).toFixed(3)} × 10⁶ km²`;
  if (km2 < 1) return `${(km2 * 1e6).toFixed(0)} m²`;
  return `${km2.toLocaleString(undefined, { maximumFractionDigits: 2 })} km²`;
}

export function fmtInt(n) {
  return n === null || n === undefined ? '—' : n.toLocaleString();
}
