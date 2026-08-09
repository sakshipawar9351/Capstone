"""
Path planning over a weighted traversability grid.

Seven algorithms behind one interface, so the comparison ALGORITHMS.md calls
for is a fair one: identical cost surface, identical start and goal, identical
neighbour model, identical accounting of expansions and runtime. Any difference
in the results is then a property of the algorithm rather than of its harness.

The cost surface
----------------
``hazard.analyse_traversability`` produces ``cost_s``: the seconds required to
cross each cell, already inflated by risk, and ``inf`` where the terrain exceeds
the vehicle's static stability. Impassable cells are therefore excluded
structurally — no planner has to be told to avoid them, and none can be tuned
into crossing one.

Edge cost
---------
Moving between adjacent cells costs the mean of their two cell costs, scaled by
the geometric step length (1 or √2 cells):

.. math:: c(a,b) = \\tfrac{1}{2}\\bigl(C_a + C_b\\bigr)\\,\\lVert b-a \\rVert

Using the mean rather than the destination's cost alone makes the cost
symmetric — ``c(a,b) = c(b,a)`` — which Dijkstra and A* both assume, and which
keeps a route's cost independent of the direction it is driven.

Admissible heuristic
--------------------
A* is optimal only if its heuristic never overestimates. On a weighted grid the
cheapest conceivable travel is the straight-line distance multiplied by the
lowest per-cell cost anywhere on the map:

.. math:: h(n) = \\lVert n - goal \\rVert \\cdot \\min_{c \\in \\text{grid}} C_c

That bound is loose — real routes cost more — but it is guaranteed not to
exceed the true remaining cost, which is what optimality requires. A heuristic
tuned to be tighter and occasionally wrong would produce paths that look
plausible and are not optimal, and nothing in the output would reveal it.

References
----------
Dijkstra, E. W. (1959), Numerische Mathematik 1, 269-271.
Hart, P. E., Nilsson, N. J. & Raphael, B. (1968), IEEE Trans. SSC 4(2), 100-107.
Pohl, I. (1970), Artificial Intelligence 1(3-4), 193-204.  [Weighted A*]
Daniel, K. et al. (2010), JAIR 39, 533-579.  [Theta*]
Koenig, S. & Likhachev, M. (2005), IEEE Trans. Robotics 21(3), 354-363. [D* Lite]
Karaman, S. & Frazzoli, S. (2011), IJRR 30(7), 846-894.  [RRT*]
"""

from __future__ import annotations

import heapq
import math
import time
from dataclasses import dataclass, field

import numpy as np

__all__ = [
    "Grid", "PlanResult", "ALGORITHMS",
    "bfs", "dijkstra", "astar", "weighted_astar", "theta_star",
    "dstar_lite", "rrt_star", "plan",
]

SQRT2 = math.sqrt(2.0)

#: 8-connected neighbourhood with step lengths.
NEIGHBOURS = (
    (-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
    (-1, -1, SQRT2), (-1, 1, SQRT2), (1, -1, SQRT2), (1, 1, SQRT2),
)


# ---------------------------------------------------------------------------
# Grid
# ---------------------------------------------------------------------------

@dataclass
class Grid:
    """A weighted traversability surface."""

    cost: np.ndarray          # seconds to cross each cell; inf = impassable
    cell_m: float             # ground size of one cell

    def __post_init__(self):
        self.cost = np.asarray(self.cost, dtype=np.float64)
        self.h, self.w = self.cost.shape
        finite = self.cost[np.isfinite(self.cost)]
        if finite.size == 0:
            raise ValueError("cost surface is entirely impassable")
        self._min_cost = float(finite.min())

    def passable(self, r: int, c: int) -> bool:
        return (0 <= r < self.h and 0 <= c < self.w
                and math.isfinite(self.cost[r, c]))

    def neighbours(self, r: int, c: int):
        """Passable 8-neighbours and the cost of reaching each.

        Diagonal moves are refused when both orthogonal neighbours are blocked,
        which would otherwise let a path slip through the corner between two
        impassable cells — geometrically impossible for a vehicle with width.
        """
        for dr, dc, step in NEIGHBOURS:
            nr, nc = r + dr, c + dc
            if not self.passable(nr, nc):
                continue
            if dr and dc:
                if not (self.passable(r + dr, c) or self.passable(r, c + dc)):
                    continue
            yield nr, nc, self.edge_cost(r, c, nr, nc, step)

    def edge_cost(self, r, c, nr, nc, step=None) -> float:
        if step is None:
            step = math.hypot(nr - r, nc - c)
        return 0.5 * (self.cost[r, c] + self.cost[nr, nc]) * step

    def heuristic(self, a, b) -> float:
        """Admissible: straight-line distance at the cheapest cost anywhere."""
        return math.hypot(a[0] - b[0], a[1] - b[1]) * self._min_cost

    def line_of_sight(self, a, b) -> tuple[bool, float]:
        """Bresenham traversal between two cells.

        Returns whether every cell on the line is passable, and the accumulated
        cost of travelling it. Theta* needs both: visibility alone is not enough
        on a weighted surface, because a clear line may still be more expensive
        than going around.
        """
        r0, c0 = a
        r1, c1 = b
        dr, dc = abs(r1 - r0), abs(c1 - c0)
        sr = 1 if r1 > r0 else -1
        sc = 1 if c1 > c0 else -1
        err = dr - dc
        r, c = r0, c0
        cells = [(r, c)]

        while (r, c) != (r1, c1):
            e2 = 2 * err
            if e2 > -dc:
                err -= dc
                r += sr
            if e2 < dr:
                err += dr
                c += sc
            if not self.passable(r, c):
                return False, math.inf
            cells.append((r, c))

        # Cost by the trapezoid rule along the traversed cells, scaled to the
        # true Euclidean separation rather than the number of steps.
        if len(cells) < 2:
            return True, 0.0
        total = 0.0
        for (ra, ca), (rb, cb) in zip(cells, cells[1:]):
            total += self.edge_cost(ra, ca, rb, cb)
        geo = math.hypot(r1 - r0, c1 - c0)
        walked = sum(math.hypot(rb - ra, cb - ca)
                     for (ra, ca), (rb, cb) in zip(cells, cells[1:]))
        if walked > 0:
            total *= geo / walked
        return True, total


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class PlanResult:
    """One planner's output, with the accounting needed to compare it."""

    algorithm: str
    found: bool
    path: list[tuple[int, int]] = field(default_factory=list)
    cost: float = math.inf
    nodes_expanded: int = 0
    peak_open: int = 0
    runtime_ms: float = 0.0
    optimal: bool | None = None      # guaranteed optimal by construction?
    deterministic: bool = True
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "algorithm": self.algorithm,
            "found": self.found,
            "cost_s": None if math.isinf(self.cost) else round(self.cost, 3),
            "waypoints": len(self.path),
            "nodes_expanded": self.nodes_expanded,
            "peak_open_set": self.peak_open,
            "runtime_ms": round(self.runtime_ms, 3),
            "optimal_by_construction": self.optimal,
            "deterministic": self.deterministic,
            "note": self.note,
        }


def _reconstruct(came, node):
    out = [node]
    while node in came:
        node = came[node]
        out.append(node)
    return out[::-1]


def _path_cost(grid: Grid, path) -> float:
    if len(path) < 2:
        return 0.0
    return sum(grid.edge_cost(a[0], a[1], b[0], b[1])
               for a, b in zip(path, path[1:]))


# ---------------------------------------------------------------------------
# 1. Breadth-first search — baseline
# ---------------------------------------------------------------------------

def bfs(grid: Grid, start, goal) -> PlanResult:
    """Fewest cells, ignoring cost.

    Included precisely because it is wrong for this problem: it treats a
    boulder field and a smooth plain as equally cheap. Its path is the control
    that shows what weighting the terrain actually buys.
    """
    t0 = time.perf_counter()
    from collections import deque

    q = deque([start])
    came, seen = {}, {start}
    expanded, peak = 0, 1

    while q:
        peak = max(peak, len(q))
        cur = q.popleft()
        expanded += 1
        if cur == goal:
            path = _reconstruct(came, cur)
            return PlanResult("BFS", True, path, _path_cost(grid, path),
                              expanded, peak,
                              (time.perf_counter() - t0) * 1e3,
                              optimal=False,
                              note="Minimises cell count, not cost")
        for nr, nc, _ in grid.neighbours(*cur):
            if (nr, nc) not in seen:
                seen.add((nr, nc))
                came[(nr, nc)] = cur
                q.append((nr, nc))

    return PlanResult("BFS", False, nodes_expanded=expanded, peak_open=peak,
                      runtime_ms=(time.perf_counter() - t0) * 1e3,
                      optimal=False)


# ---------------------------------------------------------------------------
# 2. Dijkstra — the optimality reference
# ---------------------------------------------------------------------------

def dijkstra(grid: Grid, start, goal) -> PlanResult:
    """Uniform-cost search. Optimal, and the yardstick every other result is
    measured against: any algorithm returning a lower cost has a bug."""
    t0 = time.perf_counter()
    g = {start: 0.0}
    came = {}
    open_heap = [(0.0, start)]
    closed = set()
    expanded, peak = 0, 1

    while open_heap:
        peak = max(peak, len(open_heap))
        d, cur = heapq.heappop(open_heap)
        if cur in closed:
            continue
        closed.add(cur)
        expanded += 1
        if cur == goal:
            path = _reconstruct(came, cur)
            return PlanResult("Dijkstra", True, path, d, expanded, peak,
                              (time.perf_counter() - t0) * 1e3, optimal=True,
                              note="Optimal reference")
        for nr, nc, w in grid.neighbours(*cur):
            nd = d + w
            if nd < g.get((nr, nc), math.inf):
                g[(nr, nc)] = nd
                came[(nr, nc)] = cur
                heapq.heappush(open_heap, (nd, (nr, nc)))

    return PlanResult("Dijkstra", False, nodes_expanded=expanded, peak_open=peak,
                      runtime_ms=(time.perf_counter() - t0) * 1e3, optimal=True)


# ---------------------------------------------------------------------------
# 3. A* — the selected algorithm
# ---------------------------------------------------------------------------

def astar(grid: Grid, start, goal, weight: float = 1.0,
          name: str = "A*") -> PlanResult:
    """A* with an admissible heuristic.

    ``weight`` > 1 gives Weighted A*: faster, and bounded within a factor
    ``weight`` of optimal (Pohl 1970). At 1.0 the result is optimal.

    Ties in *f* are broken toward larger *g* — deeper nodes first — which cuts
    expansions substantially on grids with many equal-cost routes, without
    affecting the cost of the path returned.
    """
    t0 = time.perf_counter()
    g = {start: 0.0}
    came = {}
    h0 = grid.heuristic(start, goal)
    open_heap = [(weight * h0, -0.0, start)]
    closed = set()
    expanded, peak = 0, 1

    while open_heap:
        peak = max(peak, len(open_heap))
        f, neg_g, cur = heapq.heappop(open_heap)
        if cur in closed:
            continue
        closed.add(cur)
        expanded += 1

        if cur == goal:
            path = _reconstruct(came, cur)
            return PlanResult(name, True, path, g[cur], expanded, peak,
                              (time.perf_counter() - t0) * 1e3,
                              optimal=(weight == 1.0),
                              note=("Optimal" if weight == 1.0
                                    else f"Bounded suboptimal, <= {weight}x optimal"))

        for nr, nc, w in grid.neighbours(*cur):
            ng = g[cur] + w
            if ng < g.get((nr, nc), math.inf):
                g[(nr, nc)] = ng
                came[(nr, nc)] = cur
                f = ng + weight * grid.heuristic((nr, nc), goal)
                heapq.heappush(open_heap, (f, -ng, (nr, nc)))

    return PlanResult(name, False, nodes_expanded=expanded, peak_open=peak,
                      runtime_ms=(time.perf_counter() - t0) * 1e3,
                      optimal=(weight == 1.0))


def weighted_astar(grid: Grid, start, goal, weight: float = 2.5) -> PlanResult:
    return astar(grid, start, goal, weight=weight,
                 name=f"Weighted A* (w={weight})")


# ---------------------------------------------------------------------------
# 4. Theta* — any-angle
# ---------------------------------------------------------------------------

def theta_star(grid: Grid, start, goal) -> PlanResult:
    """Any-angle search: parents may be any visible ancestor, not only a
    neighbour, so paths are not confined to 45° increments.

    Note the honest caveat carried into the result: on a *weighted* surface
    Theta* is not optimal. Replacing two grid steps with a straight line can
    cross cells the grid path avoided, and the line-of-sight test accepts it
    whenever the direct cost is lower — which is a local decision, not a global
    one. It produces shorter, more natural routes and gives up the optimality
    guarantee to do so.
    """
    t0 = time.perf_counter()
    g = {start: 0.0}
    parent = {start: start}
    open_heap = [(grid.heuristic(start, goal), start)]
    closed = set()
    expanded, peak = 0, 1

    while open_heap:
        peak = max(peak, len(open_heap))
        _, cur = heapq.heappop(open_heap)
        if cur in closed:
            continue
        closed.add(cur)
        expanded += 1

        if cur == goal:
            path = [cur]
            while parent[path[-1]] != path[-1]:
                path.append(parent[path[-1]])
            path.reverse()
            return PlanResult("Theta*", True, path, _path_cost(grid, path),
                              expanded, peak,
                              (time.perf_counter() - t0) * 1e3,
                              optimal=False,
                              note="Any-angle; not optimal on weighted terrain")

        for nr, nc, w in grid.neighbours(*cur):
            nb = (nr, nc)
            if nb in closed:
                continue
            p = parent[cur]
            visible, los_cost = grid.line_of_sight(p, nb)
            if visible and g[p] + los_cost < g.get(nb, math.inf):
                g[nb] = g[p] + los_cost
                parent[nb] = p
                heapq.heappush(open_heap, (g[nb] + grid.heuristic(nb, goal), nb))
            elif g[cur] + w < g.get(nb, math.inf):
                g[nb] = g[cur] + w
                parent[nb] = cur
                heapq.heappush(open_heap, (g[nb] + grid.heuristic(nb, goal), nb))

    return PlanResult("Theta*", False, nodes_expanded=expanded, peak_open=peak,
                      runtime_ms=(time.perf_counter() - t0) * 1e3, optimal=False)


# ---------------------------------------------------------------------------
# 5. D* Lite — incremental replanning
# ---------------------------------------------------------------------------

def dstar_lite(grid: Grid, start, goal) -> PlanResult:
    """Koenig & Likhachev's incremental search.

    On a first, complete plan D* Lite does the same work as A* — its value is
    in what happens *next*. When terrain changes ahead of a rover, it repairs
    only the affected region instead of replanning from scratch, which is the
    difference between a vehicle that can react to a newly-seen boulder and one
    that must stop and recompute its entire route.
    """
    t0 = time.perf_counter()
    INF = math.inf
    gv, rhs = {}, {}
    km = 0.0
    expanded, peak = 0, 1

    def G(s):
        return gv.get(s, INF)

    def R(s):
        return rhs.get(s, INF)

    rhs[goal] = 0.0

    def key(s):
        k = min(G(s), R(s))
        return (k + grid.heuristic(start, s) + km, k)

    U = [(key(goal), goal)]

    def update(s):
        if s != goal:
            best = INF
            for nr, nc, w in grid.neighbours(*s):
                best = min(best, G((nr, nc)) + w)
            rhs[s] = best
        for i, (_, node) in enumerate(U):
            if node == s:
                U.pop(i)
                heapq.heapify(U)
                break
        if G(s) != R(s):
            heapq.heappush(U, (key(s), s))

    while U:
        peak = max(peak, len(U))
        k_old, u = heapq.heappop(U)
        if k_old > key(u) or (G(start) == R(start) and R(start) < INF):
            if k_old > key(u):
                heapq.heappush(U, (key(u), u))
                continue
            break
        expanded += 1
        if G(u) > R(u):
            gv[u] = R(u)
            for nr, nc, _ in grid.neighbours(*u):
                update((nr, nc))
        else:
            gv[u] = INF
            update(u)
            for nr, nc, _ in grid.neighbours(*u):
                update((nr, nc))
        if expanded > grid.h * grid.w * 4:
            break                              # guard against pathological input

    if R(start) == INF:
        return PlanResult("D* Lite", False, nodes_expanded=expanded,
                          peak_open=peak,
                          runtime_ms=(time.perf_counter() - t0) * 1e3,
                          optimal=True)

    # Walk the gradient from start to goal.
    path = [start]
    cur = start
    guard = 0
    while cur != goal and guard < grid.h * grid.w:
        guard += 1
        best, bnode = INF, None
        for nr, nc, w in grid.neighbours(*cur):
            v = w + G((nr, nc))
            if v < best:
                best, bnode = v, (nr, nc)
        if bnode is None:
            break
        cur = bnode
        path.append(cur)

    found = path[-1] == goal
    return PlanResult("D* Lite", found, path if found else [],
                      _path_cost(grid, path) if found else INF,
                      expanded, peak, (time.perf_counter() - t0) * 1e3,
                      optimal=True,
                      note="Optimal; repairs locally when terrain changes")


# ---------------------------------------------------------------------------
# 6. RRT* — sampling-based
# ---------------------------------------------------------------------------

def rrt_star(grid: Grid, start, goal, iterations: int = 4000,
             step: float = 8.0, radius: float = 16.0,
             seed: int = 0) -> PlanResult:
    """Rapidly-exploring Random Tree with rewiring (Karaman & Frazzoli 2011).

    Asymptotically optimal — it converges to the best path given unlimited
    samples — but not optimal at any finite budget, and **not deterministic**
    unless the seed is fixed. The seed is fixed here, because a mission tool
    that returns a different route each time it is asked cannot be reviewed.
    That reproducibility is a deliberate constraint, not a property of RRT*.
    """
    t0 = time.perf_counter()
    rng = np.random.default_rng(seed)
    nodes = [start]
    parent = {0: None}
    cost = {0: 0.0}
    expanded, goal_idx = 0, None

    def nearest(p):
        d = [(nodes[i][0] - p[0]) ** 2 + (nodes[i][1] - p[1]) ** 2
             for i in range(len(nodes))]
        return int(np.argmin(d))

    def steer(a, b):
        dr, dc = b[0] - a[0], b[1] - a[1]
        dist = math.hypot(dr, dc)
        if dist <= step:
            return b
        return (int(round(a[0] + dr / dist * step)),
                int(round(a[1] + dc / dist * step)))

    for _ in range(iterations):
        expanded += 1
        # Goal biasing: without it the tree wanders and rarely arrives.
        if rng.random() < 0.08:
            sample = goal
        else:
            sample = (int(rng.integers(0, grid.h)), int(rng.integers(0, grid.w)))
        if not grid.passable(*sample):
            continue

        ni = nearest(sample)
        new = steer(nodes[ni], sample)
        if not grid.passable(*new) or new in nodes:
            continue
        ok, c = grid.line_of_sight(nodes[ni], new)
        if not ok:
            continue

        # Choose the cheapest parent within the rewiring radius.
        best_i, best_c = ni, cost[ni] + c
        near = [i for i in range(len(nodes))
                if math.hypot(nodes[i][0] - new[0], nodes[i][1] - new[1]) <= radius]
        for i in near:
            ok2, c2 = grid.line_of_sight(nodes[i], new)
            if ok2 and cost[i] + c2 < best_c:
                best_i, best_c = i, cost[i] + c2

        nodes.append(new)
        idx = len(nodes) - 1
        parent[idx] = best_i
        cost[idx] = best_c

        # Rewire neighbours that would now be cheaper through the new node.
        for i in near:
            ok3, c3 = grid.line_of_sight(new, nodes[i])
            if ok3 and best_c + c3 < cost[i]:
                parent[i] = idx
                cost[i] = best_c + c3

        if math.hypot(new[0] - goal[0], new[1] - goal[1]) <= step:
            ok4, c4 = grid.line_of_sight(new, goal)
            if ok4:
                nodes.append(goal)
                gi = len(nodes) - 1
                parent[gi] = idx
                cost[gi] = best_c + c4
                goal_idx = gi

    if goal_idx is None:
        return PlanResult("RRT*", False, nodes_expanded=expanded,
                          peak_open=len(nodes),
                          runtime_ms=(time.perf_counter() - t0) * 1e3,
                          optimal=False, deterministic=False,
                          note=f"No path in {iterations} samples")

    path, i = [], goal_idx
    while i is not None:
        path.append(nodes[i])
        i = parent[i]
    path.reverse()

    return PlanResult("RRT*", True, path, _path_cost(grid, path),
                      expanded, len(nodes),
                      (time.perf_counter() - t0) * 1e3,
                      optimal=False, deterministic=False,
                      note=f"Asymptotically optimal; {iterations} samples, seed {seed}")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ALGORITHMS = {
    "bfs": ("BFS", bfs),
    "dijkstra": ("Dijkstra", dijkstra),
    "astar": ("A*", astar),
    "weighted_astar": ("Weighted A*", weighted_astar),
    "theta_star": ("Theta*", theta_star),
    "dstar_lite": ("D* Lite", dstar_lite),
    "rrt_star": ("RRT*", rrt_star),
}


def plan(grid: Grid, start, goal, algorithm: str = "astar", **kw) -> PlanResult:
    if algorithm not in ALGORITHMS:
        raise KeyError(f"unknown algorithm {algorithm!r}; "
                       f"have {sorted(ALGORITHMS)}")
    if not grid.passable(*start):
        return PlanResult(ALGORITHMS[algorithm][0], False,
                          note="start cell is impassable")
    if not grid.passable(*goal):
        return PlanResult(ALGORITHMS[algorithm][0], False,
                          note="goal cell is impassable")
    return ALGORITHMS[algorithm][1](grid, start, goal, **kw)
