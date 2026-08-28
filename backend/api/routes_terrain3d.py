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
