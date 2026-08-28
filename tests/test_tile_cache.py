"""
The basemap tile cache honours its budget.

``TILE_CACHE_MAX_BYTES`` was declared in ``config`` from the beginning and no
code ever read it. The cache grew without limit, which nobody noticed because
the WAC mosaic is JPEG and coarse; adding Kaguya — PNG, and four times as many
tiles per unit area — is exactly the change that turns a dormant bug into a
full disk.

The lesson is not "add eviction", it is that a declared limit with no test is
a comment. So these tests drive the eviction directly against a throwaway
directory: over budget in, under budget out, oldest gone first.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import warnings  # noqa: E402

warnings.filterwarnings("ignore")

from backend import main as M  # noqa: E402

npass = nfail = 0


def check(name, ok, detail=""):
    global npass, nfail
    if ok:
        npass += 1
        print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
    else:
        nfail += 1
        print(f"  FAIL  {name}   {detail}")


def make_cache(root: Path, n: int, size: int) -> list[Path]:
    """n tiles of `size` bytes, written oldest-first with distinct mtimes."""
    out = []
    for i in range(n):
        p = root / "wac" / "5" / str(i // 8)
        p.mkdir(parents=True, exist_ok=True)
        f = p / f"{i % 8}.jpg"
        f.write_bytes(b"\0" * size)
        # Explicit mtimes: writing 40 files takes less than a filesystem tick,
        # so without this the "oldest" ordering would be arbitrary and the test
        # would pass or fail by luck.
        import os
        os.utime(f, (1_600_000_000 + i, 1_600_000_000 + i))
        out.append(f)
    return out


def total_bytes(root: Path) -> int:
    return sum(f.stat().st_size for f in root.rglob("*") if f.is_file())


tmp = Path(tempfile.mkdtemp(prefix="ls-tilecache-"))
real_dir, real_cap = M.TILE_CACHE_DIR, M.TILE_CACHE_MAX_BYTES
try:
    # Never point the eviction at the real cache: a test that deletes the
    # user's tiles to prove it can delete tiles has done actual harm.
    M.TILE_CACHE_DIR = tmp
    M.TILE_CACHE_MAX_BYTES = 100_000

    print("\nUnder budget, nothing is touched\n")
    files = make_cache(tmp, 5, 10_000)          # 50 kB against a 100 kB cap
    freed = M._evict_tile_cache()
    check("a cache within its budget is left entirely alone",
          freed == 0 and all(f.exists() for f in files),
          f"{total_bytes(tmp):,} bytes, cap {M.TILE_CACHE_MAX_BYTES:,}")

    print("\nOver budget, the oldest go first\n")
    shutil.rmtree(tmp)
    files = make_cache(tmp, 40, 10_000)         # 400 kB against a 100 kB cap
    before = total_bytes(tmp)
    freed = M._evict_tile_cache()
    after = total_bytes(tmp)

    check("eviction runs when the cache is over its cap", freed > 0,
          f"{before:,} -> {after:,} bytes")
    check("the cache ends under the cap", after <= M.TILE_CACHE_MAX_BYTES,
          f"{after:,} of {M.TILE_CACHE_MAX_BYTES:,}")
    # Down to 80 %, not exactly to the cap: a cache trimmed to precisely its
    # limit would re-sweep on the very next tile, walking the whole tree again.
    check("it sweeps down to 80 % so it does not re-sweep immediately",
          after <= M.TILE_CACHE_MAX_BYTES * 0.85,
          f"{after / M.TILE_CACHE_MAX_BYTES * 100:.0f}% of cap")
    check("the bytes it reports freeing match what actually went",
          freed == before - after, f"reported {freed:,}, real {before - after:,}")

    survivors = [f for f in files if f.exists()]
    evicted = [f for f in files if not f.exists()]
    check("the survivors are the newest, the evicted the oldest",
          bool(survivors) and bool(evicted)
          and min(f.stat().st_mtime for f in survivors)
          > 1_600_000_000 + len(evicted) - 1,
          f"{len(evicted)} oldest evicted, {len(survivors)} newest kept")

    print("\nA read counts as a use\n")
    # Least-recently-*used*, not least-recently-written: the tiles someone
    # keeps coming back to are the ones worth keeping. `_fetch_tile` touches on
    # a cache hit, so an old-but-popular tile must survive a later sweep.
    shutil.rmtree(tmp)
    files = make_cache(tmp, 40, 10_000)
    oldest = files[0]
    oldest.touch()                               # what a cache hit does
    M._evict_tile_cache()
    check("an old tile that was read recently survives", oldest.exists(),
          "otherwise a popular tile is evicted on a schedule and re-fetched forever")

    print("\nThe cache reports itself\n")
    shutil.rmtree(tmp)
    make_cache(tmp, 12, 5_000)
    st = M.tile_cache_stats()
    check("stats count every file", st["files"] == 12, str(st["files"]))
    check("stats total the bytes", st["bytes"] == 60_000, f"{st['bytes']:,}")
    check("stats carry the cap so a caller can show a percentage",
          st["cap_bytes"] == M.TILE_CACHE_MAX_BYTES)
    check("stats break down per layer, so one product's cost is visible",
          st["by_layer"]["wac"]["files"] == 12, str(st["by_layer"]))
finally:
    M.TILE_CACHE_DIR, M.TILE_CACHE_MAX_BYTES = real_dir, real_cap
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n{npass} passed, {nfail} failed")
raise SystemExit(1 if nfail else 0)
