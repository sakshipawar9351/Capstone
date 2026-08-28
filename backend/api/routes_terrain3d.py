"""
The selected region as a 3D surface — FR-1.17.

Every map the region page draws is an overhead picture, and an overhead picture
of terrain hides the one thing a traverse is about: whether the ground goes up.
A 40 deg scarp and a 4 deg ramp can be the same shade of amber on a slope map
read at a glance. Seen edge-on they are not remotely the same object.

So this serves the region's own elevation grid as a mesh the browser can render
directly: positions, indices and normals, computed once here rather than in
JavaScript. That choice is not about speed. It is that the mesh must be built
from the *same array the analysis ran on* — if the browser resampled the DEM
again to draw it, the picture and the numbers would describe slightly different
ground, and every slope the user checked by eye against the render would be
answering a question about a surface that was never analysed.

Geometry, and what is honest about it
------------------------------------
Vertices sit at true local metres from the AOI centre — the same azimuthal
equidistant frame ``aoi_window`` resamples into — so x and y are real distances
and the mesh is not distorted by a projection. Height is the DEM value with the
region's own mean removed, because 1,737 km of radius carries no information
about the 300 m of relief anyone wants to see.

Vertical exaggeration is applied **in the client**, never here. The numbers
that leave this module are metres; a factor baked into them would travel into
screenshots and reports as if it were measurement. The client shows the factor
on screen for the same reason.

Budget
------
A full site AOI is 2.25 M cells. As float32 positions that is 27 MB before
indices, which is not a thing to push through a browser for a view. The grid is
decimated to at most ``MAX_MESH_VERTS`` and the decimation is *reported*, so the
page can say "drawn at 20 m from 10 m data" rather than implying it is showing
every measurement. Decimation strides rather than averages: an averaged mesh
would quietly smooth away the scarps this view exists to reveal.
"""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException, Query, Response

from ..config import API_PREFIX
from ..core.aoi import AOIUnavailable, plan_aoi
from ..core.aoi_window import read_aoi

router = APIRouter(prefix=API_PREFIX, tags=["terrain3d"])

#: About 360 k triangles at the cap — comfortable for an integrated GPU, and
#: 4.2 MB of float32 positions, which downloads in well under a second locally.
MAX_MESH_VERTS = 180_000


def _stride_for(rows: int, cols: int, budget: int) -> int:
    """Smallest stride that brings the vertex count under the budget."""
    s = 1
    while ((rows + s - 1) // s) * ((cols + s - 1) // s) > budget:
        s += 1
    return s


@router.get("/aoi/mesh")
def aoi_mesh(
    south: float = Query(..., ge=-90, le=90),
    north: float = Query(..., ge=-90, le=90),
    west: float = Query(...),
    east: float = Query(...),
    source: str | None = Query(None),
    finest: bool = Query(False),
    max_verts: int = Query(MAX_MESH_VERTS, ge=1024, le=400_000),
) -> Response:
    """The region's elevation as a triangle mesh, as raw little-endian binary.

    The body is three concatenated arrays, in order, with their lengths in the
    headers:

    ``positions``  float32, 3 per vertex — x east, y north, z up, all metres
    ``normals``    float32, 3 per vertex — unit, for shading
    ``indices``    uint32, 3 per triangle

    Binary rather than JSON because it is the same numbers either way and this
    is a quarter of the size with no parse step. Row-major from the north-west
    corner, which is how ``AOIWindow`` stores the grid, so a caller can index
    a vertex from a cell without a lookup table.
    """
    try:
        aoi = plan_aoi(south, north, west, east, source=source,
                       finest=finest)
    except AOIUnavailable as e:
        raise HTTPException(422, str(e)) from e

    win = read_aoi(aoi)
    z = win.elevation
    stride = _stride_for(*z.shape, max_verts)
    z = z[::stride, ::stride]
    rows, cols = z.shape
    if rows < 2 or cols < 2:
        raise HTTPException(422, "region is too small to build a surface from")

    cell = win.cell_m * stride

    # Gaps are real: a DEM with unmeasured cells must not be shown as a hole at
    # sea level. They are filled with the region mean for geometry and reported
    # so the client can grey them, rather than being drawn as flat ground the
    # rover could cross.
    valid = np.isfinite(z)
    if not valid.any():
        raise HTTPException(422, "no elevation was measured anywhere in this region")
    mean = float(z[valid].mean())
    zf = np.where(valid, z, mean).astype(np.float64)

    # Local metres from the region centre — the same frame the analysis used, so
    # a distance measured on this mesh is the distance the planner costed.
    xs = (np.arange(cols) - (cols - 1) / 2.0) * cell
    ys = ((rows - 1) / 2.0 - np.arange(rows)) * cell
    gx, gy = np.meshgrid(xs, ys)

    positions = np.empty((rows, cols, 3), dtype=np.float32)
    positions[..., 0] = gx
    positions[..., 1] = gy
    positions[..., 2] = zf - mean          # relief about the region's own mean

    # Normals from the same central differences the slope operator uses, so the
    # shading agrees with the slope map beside it instead of merely resembling
    # it. Edges fall back to one-sided differences via `edge_order=1`.
    dzdy, dzdx = np.gradient(zf, cell, edge_order=1)
    n = np.empty((rows, cols, 3), dtype=np.float64)
    n[..., 0] = -dzdx
    n[..., 1] = dzdy                       # y runs north, rows run south
    n[..., 2] = 1.0
    n /= np.linalg.norm(n, axis=2, keepdims=True)

    # Two triangles per quad, wound counter-clockwise seen from above.
    r0 = np.arange(rows - 1)[:, None]
    c0 = np.arange(cols - 1)[None, :]
    tl = (r0 * cols + c0).astype(np.uint32)
    tr, bl, br = tl + 1, tl + cols, tl + cols + 1
    idx = np.empty((rows - 1, cols - 1, 6), dtype=np.uint32)
    idx[..., 0], idx[..., 1], idx[..., 2] = tl, bl, br
    idx[..., 3], idx[..., 4], idx[..., 5] = tl, br, tr

    body = (positions.tobytes() + n.astype(np.float32).tobytes()
            + idx.tobytes())

    lo, hi = float(z[valid].min()), float(z[valid].max())
    return Response(
        content=body, media_type="application/octet-stream",
        headers={
            "Cache-Control": "public, max-age=600",
            "X-Vertices": str(rows * cols),
            "X-Triangles": str((rows - 1) * (cols - 1) * 2),
            "X-Rows": str(rows),
            "X-Cols": str(cols),
            "X-Cell-M": f"{cell:.4f}",
            "X-Native-Cell-M": f"{win.cell_m:.4f}",
            "X-Stride": str(stride),
            "X-Extent-M": f"{cols * cell:.2f},{rows * cell:.2f}",
            "X-Relief-M": f"{hi - lo:.2f}",
            "X-Min-M": f"{lo:.2f}",
            "X-Max-M": f"{hi:.2f}",
            "X-Mean-M": f"{mean:.2f}",
            "X-Valid-Fraction": f"{float(valid.mean()):.5f}",
            "X-Source": aoi.source.product_id,
            "X-Centre": f"{aoi.centre[0]:.6f},{aoi.centre[1]:.6f}",
            "Access-Control-Expose-Headers": (
                "X-Vertices,X-Triangles,X-Rows,X-Cols,X-Cell-M,X-Native-Cell-M,"
                "X-Stride,X-Extent-M,X-Relief-M,X-Min-M,X-Max-M,X-Mean-M,"
                "X-Valid-Fraction,X-Source,X-Centre"),
        },
    )

# There is deliberately no drape endpoint here. The imagery a region is draped
# with comes from the existing `/mosaic/{layer}`, which already snaps to whole
# tiles and reports the bounds it actually covered — and the client must place
# the texture at *those* bounds, not the ones it asked for, or the imagery
# slides off the terrain by up to one tile. Wrapping it would have meant
# either passing that subtlety through a second time or hiding it, and hiding
# it is how imagery ends up confidently misregistered.


class _SpecOnly:
    """The one attribute `_open_source` needs, without planning a region."""

    def __init__(self, spec):
        self.source = spec


def _tile_source(south, north, west, east):
    """Finest product on disk that covers this tile, or None.

    Streamed sources are excluded: a camera pulls tiles continuously and a
    45 s fetch per tile would stall the view rather than sharpen it.
    """
    from ..core.aoi import SOURCES, _covers

    ok = [s for s in SOURCES.values()
          if not s.streamed and s.validated and s.available
          and _covers(s, south, north, west, east)]
    return min(ok, key=lambda s: s.cell_m) if ok else None


# ---------------------------------------------------------------------------
# Terrain tiles for Cesium
# ---------------------------------------------------------------------------

@router.get("/terrain/tile")
def terrain_tile(
    x: int = Query(..., ge=0),
    y: int = Query(..., ge=0),
    level: int = Query(..., ge=0, le=18),
    width: int = Query(65, ge=17, le=129),
    height: int = Query(65, ge=17, le=129),
) -> Response:
    r"""One heightmap tile, from the finest local product covering it.

    Cesium's ``CustomHeightmapTerrainProvider`` asks for a rectangular lattice
    of heights per tile and builds the surface itself. That makes it possible
    to give the Terrain globe topography this project can actually stand
    behind, instead of the ion tileset — which was measured at +1,789 m against
    LOLA over 240 samples, and reads +234 m at the Apollo 15 site where LOLA
    and the LROC NAC stereo DTM agree on -1924 m to within a metre.

    The trade is honest and worth stating: the ion mesh carries 83 m geometric
    detail and is a kilometre and a half out; this is coarser almost
    everywhere and correct. For a picture the first is prettier. For anything
    with a number attached, only the second is usable.

    Resolution is per tile rather than global. ``plan_aoi`` picks the finest
    *local* product covering each rectangle, so the same globe draws 2 m over
    the Apollo 15 NAC strip, 10 m near the south pole and 473.8 m across the
    rest of the Moon — each region at the best topography actually held for it,
    with no seams to manage because every tile is asked the same question.

    Streamed sources are excluded deliberately. A camera demands tiles
    continuously and a 45 s fetch would stall the view; ``finest`` stays off so
    only what is on disk is eligible.
    """
    import numpy as np

    from ..core.aoi_window import _bilinear, _open_source

    # Cesium's GeographicTilingScheme: 2^(level+1) columns by 2^level rows over
    # the whole sphere, x eastward from -180, y southward from +90.
    cols, rows = 2 ** (level + 1), 2 ** level
    if x >= cols or y >= rows:
        raise HTTPException(422, f"tile {x}/{y} is outside level {level} "
                                 f"({cols}x{rows})")
    west = -180.0 + 360.0 * x / cols
    east = -180.0 + 360.0 * (x + 1) / cols
    north = 90.0 - 180.0 * y / rows
    south = 90.0 - 180.0 * (y + 1) / rows

    # Source selection only — deliberately not `plan_aoi`.
    #
    # A terrain tile is a lat/lon rectangle, and at low levels it is a whole
    # hemisphere. `plan_aoi` would refuse that, correctly: it plans an analysis
    # region on an azimuthal projection whose square-cell premise fails past
    # about 1,300 km. None of that applies here, because nothing is being
    # measured — the samples are read straight off the source's own grid.
    spec = _tile_source(max(south, -89.999), min(north, 89.999),
                        west % 360.0, east % 360.0)
    if spec is None:
        raise HTTPException(422, "no local product covers this tile")
    try:
        src = _open_source(_SpecOnly(spec))
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(422, str(e)) from e

    lats = np.linspace(north, south, height, dtype=np.float64)
    lons = np.linspace(west, east, width, dtype=np.float64)
    glat, glon = np.meshgrid(lats, lons % 360.0, indexing="ij")

    sr, sc = src.rowcol(glat, glon)
    sr = np.asarray(sr, dtype=np.float64)
    sc = np.asarray(sc, dtype=np.float64)

    r0 = max(int(np.floor(np.nanmin(sr))) - 2, 0)
    r1 = min(int(np.ceil(np.nanmax(sr))) + 3, src.height)
    if getattr(src, "wraps", False):
        # A tile spanning the seam has columns at both ends of the grid. Read
        # the whole row span rather than two blocks: at these tile sizes it is
        # a few thousand columns, and the alternative is seam-handling code
        # that would be exercised on one tile in every 2^(level+1).
        c0, c1 = 0, src.width
    else:
        c0 = max(int(np.floor(np.nanmin(sc))) - 2, 0)
        c1 = min(int(np.ceil(np.nanmax(sc))) + 3, src.width)

    block = src.read(r0, r1, c0, c1)
    if block.size == 0:
        raise HTTPException(422, "no data for this tile")

    grid = _bilinear(block, sr - r0, sc - c0)
    # Cesium cannot render NaN. Unmeasured ground becomes the reference sphere,
    # which is flat and obviously featureless rather than a spike or a hole.
    grid = np.nan_to_num(grid, nan=0.0, posinf=0.0, neginf=0.0)
    out = np.ascontiguousarray(grid, dtype="<f4")

    return Response(
        content=out.tobytes(),
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "public, max-age=86400",
            "X-Width": str(width), "X-Height": str(height),
            "X-Source": spec.product_id,
            "X-Cell-M": f"{spec.cell_m:.2f}",
            "X-Bounds": f"{south:.6f},{north:.6f},{west:.6f},{east:.6f}",
            "Access-Control-Expose-Headers":
                "X-Width,X-Height,X-Source,X-Cell-M,X-Bounds",
        },
    )
