"""
Verify the planners against properties that must hold regardless of terrain.

The decisive one is optimality: A* with an admissible heuristic must return
*exactly* Dijkstra's cost. If it returns less, the accounting is broken; if it
returns more, the heuristic is inadmissible and every "optimal" path the system
reports is a lie. Nothing else about the planner matters until that holds.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from backend.planning.planners import (  # noqa: E402
    ALGORITHMS, Grid, astar, bfs, dijkstra, dstar_lite, plan, rrt_star,
    theta_star, weighted_astar,
)

npass = nfail = 0


def check(name, ok, detail=""):
    global npass, nfail
    if ok:
        npass += 1
        print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
    else:
        nfail += 1
        print(f"  FAIL  {name}   {detail}")


# ---------------------------------------------------------------------------
print("\nSanity on a uniform open grid\n")

n = 30
uniform = Grid(np.ones((n, n)), cell_m=10.0)
S, G = (2, 2), (27, 27)

d = dijkstra(uniform, S, G)
a = astar(uniform, S, G)

# 25 diagonal steps at sqrt(2), cost = mean of two unit cells = 1.0 each.
expected = 25 * math.sqrt(2.0)
check(f"Dijkstra finds the diagonal, cost {d.cost:.4f}",
      d.found and abs(d.cost - expected) < 1e-9,
      f"expected {expected:.4f}")
check(f"A* matches Dijkstra exactly ({a.cost:.6f})",
      abs(a.cost - d.cost) < 1e-9)
check("A* expands fewer nodes than Dijkstra",
      a.nodes_expanded < d.nodes_expanded,
      f"{a.nodes_expanded} vs {d.nodes_expanded} "
      f"({100 * (1 - a.nodes_expanded / d.nodes_expanded):.0f}% fewer)")

# ---------------------------------------------------------------------------
print("\nOptimality on random weighted terrain — the decisive test\n")

rng = np.random.default_rng(42)
mismatches = []
for trial in range(12):
    cost = rng.uniform(1.0, 25.0, size=(28, 28))
    # Scatter impassable cells so the surface has real structure.
    blocked = rng.random((28, 28)) < 0.14
    cost[blocked] = np.inf
    cost[1, 1] = 1.0
    cost[26, 26] = 1.0
    g = Grid(cost, 10.0)

    dd = dijkstra(g, (1, 1), (26, 26))
    aa = astar(g, (1, 1), (26, 26))
    if not dd.found:
        continue
    if abs(aa.cost - dd.cost) > 1e-6:
        mismatches.append((trial, dd.cost, aa.cost))

check("A* == Dijkstra on 12 random weighted grids",
      not mismatches,
      f"{len(mismatches)} mismatches" if mismatches
      else "heuristic is admissible, path is optimal")

# ---------------------------------------------------------------------------
print("\nEvery algorithm on one shared surface\n")

rng = np.random.default_rng(7)
cost = rng.uniform(1.0, 12.0, size=(40, 40))
wall = np.zeros((40, 40), dtype=bool)
wall[12:28, 18:21] = True          # a barrier with one gap
wall[19:21, 18:21] = False
cost[wall] = np.inf
grid = Grid(cost, 10.0)
S, G = (5, 5), (34, 34)

print(f"  {'algorithm':<20}{'found':>6}{'cost':>10}{'nodes':>8}"
      f"{'ms':>8}{'vs opt':>9}")
print("  " + "-" * 61)

ref = dijkstra(grid, S, G)
results = {}
for key in ALGORITHMS:
    r = plan(grid, S, G, algorithm=key)
    results[key] = r
    ratio = (r.cost / ref.cost) if (r.found and ref.found and ref.cost > 0) else float("nan")
    print(f"  {r.algorithm:<20}{str(r.found):>6}"
          f"{(r.cost if r.found else float('nan')):>10.1f}"
          f"{r.nodes_expanded:>8}{r.runtime_ms:>8.1f}"
          f"{ratio:>8.3f}x")

check("all seven algorithms are registered", len(ALGORITHMS) == 7)
check("every algorithm finds a path through the gap",
      all(r.found for r in results.values()),
      ", ".join(k for k, r in results.items() if not r.found) or "all found")

check("no algorithm beats Dijkstra (would indicate a bug)",
      all(r.cost >= ref.cost - 1e-6 for r in results.values() if r.found),
      "Dijkstra is the lower bound")

check("A* is exactly optimal",
      abs(results["astar"].cost - ref.cost) < 1e-6)
check("Weighted A* is within its stated bound",
      results["weighted_astar"].cost <= ref.cost * 2.5 + 1e-6,
      f"{results['weighted_astar'].cost / ref.cost:.3f}x, bound 2.5x")
check("Weighted A* is faster than A*",
      results["weighted_astar"].nodes_expanded <= results["astar"].nodes_expanded,
      f"{results['weighted_astar'].nodes_expanded} vs "
      f"{results['astar'].nodes_expanded} nodes")
check("BFS costs more than optimal (it ignores weight)",
      results["bfs"].cost > ref.cost,
      f"{results['bfs'].cost / ref.cost:.2f}x — the control")
check("D* Lite is optimal",
      abs(results["dstar_lite"].cost - ref.cost) < 1e-3,
      f"{results['dstar_lite'].cost:.2f} vs {ref.cost:.2f}")
check("Theta* returns fewer waypoints (any-angle)",
      len(results["theta_star"].path) <= len(results["astar"].path),
      f"{len(results['theta_star'].path)} vs {len(results['astar'].path)}")

# ---------------------------------------------------------------------------
print("\nDeterminism — a mission tool must repeat itself\n")

for key in ("dijkstra", "astar", "theta_star", "dstar_lite", "bfs"):
    a1 = plan(grid, S, G, algorithm=key)
    a2 = plan(grid, S, G, algorithm=key)
    check(f"{ALGORITHMS[key][0]:<12} repeats exactly",
          a1.path == a2.path and abs(a1.cost - a2.cost) < 1e-12)

r1 = rrt_star(grid, S, G, seed=1)
r2 = rrt_star(grid, S, G, seed=1)
check("RRT* repeats when seeded", r1.path == r2.path,
      "fixed seed makes a stochastic method reviewable")
r3 = rrt_star(grid, S, G, seed=2)
check("RRT* differs on a different seed", r3.path != r1.path,
      "confirming the seed is what makes it reproducible")

# ---------------------------------------------------------------------------
print("\nRefusals and edge cases\n")

blocked_cost = np.full((10, 10), np.inf)
blocked_cost[0, 0] = 1.0
gb = Grid(blocked_cost, 10.0)
r = plan(gb, (0, 0), (9, 9), algorithm="astar")
check("unreachable goal reports not-found rather than a wrong path",
      not r.found, r.note or "correctly refused")

r = plan(grid, (13, 19), G, algorithm="astar")
check("impassable start is refused with a reason",
      not r.found and "impassable" in r.note, r.note)

same = plan(uniform, (5, 5), (5, 5), algorithm="astar")
check("start == goal returns a zero-cost path",
      same.found and same.cost == 0.0)

# Corner-cutting must be impossible.
cc = np.ones((5, 5))
cc[1, 2] = np.inf
cc[2, 1] = np.inf
gcc = Grid(cc, 10.0)
nb = list(gcc.neighbours(1, 1))
check("diagonal through a blocked corner is refused",
      (2, 2) not in [(r, c) for r, c, _ in nb],
      "a vehicle with width cannot pass between two blocked cells")

print(f"\n{npass} passed, {nfail} failed")
raise SystemExit(1 if nfail else 0)
