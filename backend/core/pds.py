"""
PDS3 label parsing and raster access.

The Planetary Data System version 3 format stores a raster as a *detached* pair:
a human-readable ``.LBL`` label describing the array, and a ``.IMG`` file that is
raw, uncompressed, header-free binary.  Byte 0 of the ``.IMG`` is pixel (0, 0).

That structure is why LunarSerpent needs neither GDAL nor rasterio: once the
label has been read, the image is addressable with :func:`numpy.memmap`, which
gives O(1) random access to any window without parsing or loading the file.

Per SRD SR-C8, raster geometry is **always read from the label** when one is
available.  Falling back to the compiled-in product registry is permitted but
emits a warning, because a silent mismatch between assumed and actual geometry
would corrupt every downstream coordinate.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np

__all__ = [
    "PDSLabel",
    "RasterSpec",
    "parse_label",
    "load_label",
    "raster_spec_from_label",
    "open_raster",
]


# ---------------------------------------------------------------------------
# Label parsing
# ---------------------------------------------------------------------------

_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_UNIT = re.compile(r"^\s*([-+0-9.eE]+)\s*<[^>]*>\s*$")


class PDSLabel:
    """A parsed PDS3 label.

    Keys are exposed flat (last definition wins), which is sufficient for the
    products this project reads because the geometry keywords are unique within
    a label.  ``scopes`` retains the ``OBJECT``/``END_OBJECT`` nesting for
    callers that need it.
    """

    def __init__(self, values: dict[str, str], scopes: dict[str, dict[str, str]]):
        self._v = values
        self.scopes = scopes

    # -- access -------------------------------------------------------------

    def __contains__(self, key: str) -> bool:
        return key.upper() in self._v

    def __getitem__(self, key: str) -> str:
        return self._v[key.upper()]

    def get(self, key: str, default=None):
        return self._v.get(key.upper(), default)

    def keys(self):
        return self._v.keys()

    def number(self, key: str, default=None) -> float | None:
        """Return a numeric value, stripping any ``<unit>`` suffix.

        PDS writes dimensioned quantities as ``1737.4 <km>``; a naive ``float()``
        would raise on those.
        """
        raw = self.get(key)
        if raw is None:
            return default
        m = _UNIT.match(raw)
        text = m.group(1) if m else raw.strip()
        try:
            return float(text)
        except ValueError:
            return default

    def integer(self, key: str, default=None) -> int | None:
        v = self.number(key)
        return default if v is None else int(v)

    def __repr__(self) -> str:  # pragma: no cover
        pid = self.get("PRODUCT_ID", "?")
        return f"<PDSLabel {pid} keys={len(self._v)}>"


def parse_label(text: str) -> PDSLabel:
    """Parse PDS3 label text.

    Handles the constructs that appear in LOLA GDR labels: quoted strings
    spanning several lines, ``{...}`` sets, ``/* ... */`` comments, dimensioned
    values, pointer keywords such as ``^IMAGE``, and ``OBJECT`` nesting.
    """
    text = _COMMENT.sub(" ", text)

    values: dict[str, str] = {}
    scopes: dict[str, dict[str, str]] = {}
    stack: list[str] = []

    # Accumulate logical statements: a statement begins at ``KEY =`` and runs
    # until quotes and braces balance, which may take several physical lines.
    statement = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not statement:
            if "=" not in stripped or stripped.startswith("END"):
                if stripped == "END":
                    break
                continue
            statement = stripped
        else:
            statement += " " + stripped

        if statement.count('"') % 2 or statement.count("{") != statement.count("}"):
            continue  # unterminated; keep accumulating

        key, _, value = statement.partition("=")
        key = key.strip().upper()
        value = value.strip()
        statement = ""

        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1].strip()

        if key == "OBJECT":
            stack.append(value)
            scopes.setdefault(value, {})
            continue
        if key == "END_OBJECT":
            if stack:
                stack.pop()
            continue

        values[key] = value
        if stack:
            scopes[stack[-1]][key] = value

    return PDSLabel(values, scopes)


def load_label(source: Path | str) -> PDSLabel:
    """Load a label from a local path or an ``http(s)://`` URL."""
    s = str(source)
    if s.startswith(("http://", "https://")):
        import requests

        resp = requests.get(s, timeout=60)
        resp.raise_for_status()
        return parse_label(resp.text)
    return parse_label(
        Path(source).read_text(encoding="latin-1", errors="replace")
    )


# ---------------------------------------------------------------------------
# Raster geometry
# ---------------------------------------------------------------------------

#: PDS ``SAMPLE_TYPE`` -> NumPy byte-order character.
_BYTE_ORDER = {
    "LSB_INTEGER": "<i",
    "MSB_INTEGER": ">i",
    "LSB_UNSIGNED_INTEGER": "<u",
    "MSB_UNSIGNED_INTEGER": ">u",
    "UNSIGNED_INTEGER": "<u",
    "INTEGER": ">i",
    "PC_REAL": "<f",
    "IEEE_REAL": ">f",
    "FLOAT": ">f",
    "REAL": ">f",
}


@dataclass(frozen=True)
class RasterSpec:
    """Everything needed to read and interpret a PDS3 raster."""

    width: int                 # LINE_SAMPLES
    height: int                # LINES
    dtype: str                 # NumPy dtype string, e.g. '<i2'
    scaling_factor: float      # DN -> physical units
    offset: float              # additive offset (reference radius for LOLA)
    unit: str = "METER"
    product_id: str = ""
    map_resolution_ppd: float | None = None
    map_scale_m_px: float | None = None
    source: str = "label"      # 'label' or 'registry'

    #: The label's declared MINIMUM/MAXIMUM digital numbers, where present.
    #: For products the label describes as a *resampling* to pixel registration,
    #: these bound the **source** grid: interpolation can contract an extreme
    #: but never extend one, so observed values must lie within these bounds.
    #: Values outside them indicate a wrong dtype, byte order, or corrupt file.
    declared_min_dn: float | None = None
    declared_max_dn: float | None = None

    @property
    def nbytes(self) -> int:
        return self.width * self.height * np.dtype(self.dtype).itemsize

    @property
    def itemsize(self) -> int:
        return np.dtype(self.dtype).itemsize

    def to_metres(self, dn):
        """Convert raw digital numbers to elevation in metres.

        ``HEIGHT = DN * SCALING_FACTOR`` — quoted from the LOLA label.  The
        ``OFFSET`` is *not* added here: it converts to planetary radius, not to
        elevation, and this project's vertical datum is the reference sphere.
        """
        return np.asarray(dn, dtype=np.float32) * self.scaling_factor

    def to_radius(self, dn):
        """Convert digital numbers to planetary radius in metres."""
        return np.asarray(dn, dtype=np.float64) * self.scaling_factor + self.offset


def raster_spec_from_label(label: PDSLabel) -> RasterSpec:
    """Derive a :class:`RasterSpec` from a parsed label.

    Raises
    ------
    ValueError
        If the label lacks the geometry keywords, or declares a sample type
        this reader does not implement.  Guessing would risk silently
        misreading the array.
    """
    width = label.integer("LINE_SAMPLES")
    height = label.integer("LINES")
    if not width or not height:
        raise ValueError("label has no LINE_SAMPLES / LINES")

    sample_type = (label.get("SAMPLE_TYPE") or "").strip().upper()
    bits = label.integer("SAMPLE_BITS", 16) or 16
    if sample_type not in _BYTE_ORDER:
        raise ValueError(f"unsupported SAMPLE_TYPE {sample_type!r}")
    if bits % 8:
        raise ValueError(f"SAMPLE_BITS={bits} is not a whole number of bytes")

    dtype = f"{_BYTE_ORDER[sample_type]}{bits // 8}"

    return RasterSpec(
        width=width,
        height=height,
        dtype=dtype,
        scaling_factor=label.number("SCALING_FACTOR", 1.0) or 1.0,
        offset=label.number("OFFSET", 0.0) or 0.0,
        unit=(label.get("UNIT") or "METER").strip().upper(),
        product_id=(label.get("PRODUCT_ID") or "").strip(),
        map_resolution_ppd=label.number("MAP_RESOLUTION"),
        map_scale_m_px=label.number("MAP_SCALE"),
        source="label",
        declared_min_dn=label.number("MINIMUM"),
        declared_max_dn=label.number("MAXIMUM"),
    )


def spec_from_registry(product) -> RasterSpec:
    """Fallback spec built from :mod:`backend.config` when no label is present.

    Emits a warning (SRD SR-C8): assumed geometry that disagrees with the file
    would corrupt every coordinate derived from it.
    """
    warnings.warn(
        f"No PDS label for {product.product_id}; using compiled-in registry "
        f"geometry. Verify against the .LBL if results look wrong.",
        RuntimeWarning,
        stacklevel=2,
    )
    return RasterSpec(
        width=product.width,
        height=product.height,
        dtype=product.dtype,
        scaling_factor=product.scaling_factor,
        offset=product.offset_m,
        product_id=product.product_id,
        map_resolution_ppd=float(product.ppd),
        map_scale_m_px=product.scale_m_px,
        source="registry",
    )


# ---------------------------------------------------------------------------
# Raster access
# ---------------------------------------------------------------------------

def open_raster(img_path: Path | str, spec: RasterSpec) -> np.memmap:
    """Memory-map a PDS3 ``.IMG`` as a 2-D array of raw digital numbers.

    The file is opened read-only; nothing in this system ever writes to source
    data (SRD SR-D3).  Because PDS3 images are header-free, the mapping is a
    direct view of the file's bytes with no copy and no parse.

    Raises
    ------
    FileNotFoundError
        If the image is absent.
    ValueError
        If the file size disagrees with the declared geometry — which means the
        label and image do not belong together, or the file is truncated.
        Returning zeros in that case would look like flat terrain.
    """
    path = Path(img_path)
    if not path.exists():
        raise FileNotFoundError(f"PDS image not found: {path}")

    actual = path.stat().st_size
    if actual < spec.nbytes:
        raise ValueError(
            f"{path.name} is {actual} bytes but the label declares "
            f"{spec.width}x{spec.height}x{spec.itemsize} = {spec.nbytes} bytes. "
            "File is truncated or the label does not match this image."
        )
    if actual > spec.nbytes:
        warnings.warn(
            f"{path.name} is {actual - spec.nbytes} bytes larger than the "
            "declared array; reading the leading array only.",
            RuntimeWarning,
            stacklevel=2,
        )

    return np.memmap(
        path, dtype=spec.dtype, mode="r", shape=(spec.height, spec.width)
    )


# ---------------------------------------------------------------------------
# Self-verification
# ---------------------------------------------------------------------------

def _self_test() -> int:
    """Verify the parser against the real LDEM_16 label, if available."""
    from ..config import DEM_PRODUCTS, dataset_path

    failures = 0

    def check(name, got, want):
        nonlocal failures
        ok = got == want
        failures += 0 if ok else 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {got!r}"
              + ("" if ok else f"  (expected {want!r})"))

    lbl = dataset_path("lola_dem", "LDEM_16.LBL")
    if lbl is None:
        print("LDEM_16.LBL not available locally — skipping label test.")
        print("(Drive not mounted, or dataset root not found.)")
        return 0

    print(f"Parsing {lbl}")
    label = load_label(lbl)
    print(f"  parsed {len(list(label.keys()))} keywords\n")

    print("Label keyword extraction")
    check("PRODUCT_ID", label.get("PRODUCT_ID"), "LDEM_16")
    check("LINES", label.integer("LINES"), 2880)
    check("LINE_SAMPLES", label.integer("LINE_SAMPLES"), 5760)
    check("SAMPLE_TYPE", label.get("SAMPLE_TYPE"), "LSB_INTEGER")
    check("SAMPLE_BITS", label.integer("SAMPLE_BITS"), 16)
    check("SCALING_FACTOR", label.number("SCALING_FACTOR"), 0.5)
    check("OFFSET", label.number("OFFSET"), 1737400.0)
    check("MAP_RESOLUTION (dimensioned)", label.number("MAP_RESOLUTION"), 16.0)
    check("MAP_SCALE (dimensioned)", label.number("MAP_SCALE"), 1895.21)
    check("A_AXIS_RADIUS (dimensioned)", label.number("A_AXIS_RADIUS"), 1737.4)

    print("\nDerived RasterSpec")
    spec = raster_spec_from_label(label)
    check("dtype", spec.dtype, "<i2")
    check("nbytes", spec.nbytes, 5760 * 2880 * 2)
    check("source", spec.source, "label")

    print("\nAgreement with compiled-in registry")
    reg = DEM_PRODUCTS["ldem_16"]
    check("width", spec.width, reg.width)
    check("height", spec.height, reg.height)
    check("scaling_factor", spec.scaling_factor, reg.scaling_factor)

    print(f"\n{'ALL CHECKS PASSED' if failures == 0 else f'{failures} FAILURE(S)'}")
    return failures


if __name__ == "__main__":
    raise SystemExit(_self_test())
