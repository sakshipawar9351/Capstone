# LunarSerpent — Path Planning Algorithms: Survey, Comparison and Selection

**Document ID:** LS-DOC-006 · **Version:** 1.0 · **Status:** Baseline
**Date:** 2026-08-04
**Covers:** Project brief **Part 6** — analyse and compare the most-used, most-efficient path planning algorithms; select the best and state why; show outputs from the others too.

---

## 1. Problem formulation

Before comparing algorithms it is necessary to state precisely what problem is being solved,
because the correct choice depends entirely on the problem's structure.

**Given:**
- A cost field $C:\mathcal{S}\to\mathbb{R}^+\cup\{\infty\}$ over the lunar surface $\mathcal{S}$,
  derived in `FORMULAS.md` §6.4, where $C$ is traverse time inflated by a risk multiplier and
  $\infty$ marks impassable cells.
- Start and goal in selenographic coordinates, $(\varphi_s,\lambda_s)$ and $(\varphi_g,\lambda_g)$.
- A rover mobility model $v(\theta)$ (`FORMULAS.md` §7.1).

**Find:** the path $P$ minimising $\int_P C\,ds$.

**The five structural properties that determine the answer:**

| # | Property | Value for this problem | Consequence |
|---|---|---|---|
| 1 | Cost structure | **Weighted continuum**, not binary obstacles | Rules out algorithms that assume free/blocked |
| 2 | Environment | **Static and fully known** in advance | Replanning algorithms lose their main advantage |
| 3 | Dimensionality | **2 DOF** (position on a surface) | Sampling methods lose their main advantage |
| 4 | Optimality requirement | **Hard** — this is mission safety | Rules out non-optimal heuristics as the primary |
| 5 | Reproducibility | **Mandatory** — scientific deliverable | Rules out stochastic algorithms as the primary |

Properties 1, 4 and 5 are the decisive ones, and §4 shows why.

---

## 2. Candidate algorithms surveyed

Eleven algorithms were considered, grouped by family.

### 2.1 Uninformed graph search

**Breadth-First Search (BFS)** — expands by hop count.
- Complexity: $O(V+E)$. Optimal **only** for uniform edge cost.
- *Relevance:* Included as a **baseline** to demonstrate what ignoring terrain cost produces — it finds the fewest-cells route, which on real terrain drives straight over crater rims.

**Dijkstra (1959)** — expands in order of accumulated cost.
- Complexity: $O(E + V\log V)$ with a binary heap.
- **Optimal and complete** for non-negative weights.
- *Relevance:* This is the **optimality reference**. Its cost is by definition the true minimum on the given discretisation, so every other algorithm's result is reported as a ratio to it.

### 2.2 Informed graph search

**A\* (Hart, Nilsson & Raphael 1968)** — Dijkstra guided by a heuristic $h$.
- Complexity: $O(E + V\log V)$ worst case, but expands dramatically fewer nodes in practice.
- **Optimal** iff $h$ is admissible; **no node re-expansion** iff $h$ is consistent. Both are
  *proved* for LunarSerpent's heuristic in `FORMULAS.md` §9.1.

**Weighted A\*** — inflates the heuristic, $f = g + \varepsilon h$, $\varepsilon>1$.
- Faster, but the returned path can cost up to $\varepsilon\times$ optimal.
- *Relevance:* Included to quantify the **speed-vs-optimality trade-off** explicitly.

### 2.3 Any-angle search

**Theta\* (Nash et al. 2007)** — A\* that allows a node's parent to be any ancestor with
line-of-sight, producing paths not constrained to 45° headings.
- Removes the grid-discretisation penalty of up to **+8.24 %** derived in `FORMULAS.md` §9.2.
- ⚠️ **Critical caveat for this project:** the line-of-sight shortcut assumes cost is
  *homogeneous* along the shortcut. On a **weighted** cost field that assumption is false — a
  straight line between two cheap cells may cross expensive ones. Theta\* is therefore
  provably optimal for *binary obstacle* maps but **not** for weighted terrain.

**Lazy Theta\*** — defers line-of-sight checks; fewer checks, same path quality class.

**Field D\* (Ferguson & Stentz 2006)** — interpolates cost across cell edges, giving
any-angle paths that *do* respect a continuously varying cost field.
- The theoretically strongest fit for weighted terrain, at substantially higher implementation
  and runtime complexity.

### 2.4 Incremental replanning

**D\* Lite (Koenig & Likhachev 2002)** — repairs an existing solution when edge costs change,
rather than replanning from scratch.
- Complexity per repair is proportional to the *changed* region, not the whole map.
- *Relevance:* The environment here is static, so D\* Lite offers no advantage for initial
  planning. It becomes essential for the **operational** case — a rover discovering an
  unmapped boulder mid-traverse. Included for that scenario.

### 2.5 Sampling-based

**RRT (LaValle 1998)** — grows a tree by random sampling.
- Probabilistically complete; **not** optimal — converges to arbitrarily suboptimal paths.

**RRT\* (Karaman & Frazzoli 2011)** — adds rewiring; **asymptotically optimal**.
- Converges to the optimum only as samples $\to\infty$; any finite run is suboptimal by an
  unknown margin.
- ⚠️ **Stochastic** — different runs give different paths. For a scientific deliverable that
  must be reproducible, this is disqualifying for the primary planner.

**PRM (Kavraki et al. 1996)** — builds a reusable roadmap.
- Efficient for **many** queries in one static environment; the roadmap construction cost is
  amortised.

### 2.6 Reactive

**Artificial Potential Fields (Khatib 1986)** — gradient descent on attraction/repulsion.
- $O(1)$ per step, but suffers **local minima** and is neither complete nor optimal.
- *Relevance:* Included only to demonstrate the failure mode — it becomes trapped in concave
  crater walls, which is exactly the terrain this project must handle.

---

## 3. Comparison matrix

| Algorithm | Optimal? | Complete? | Deterministic? | Handles weighted cost? | Any-angle? | Complexity | Verdict |
|---|---|---|---|---|---|---|---|
| BFS | ✗ (uniform only) | ✓ | ✓ | ✗ | ✗ | $O(V+E)$ | Baseline only |
| **Dijkstra** | ✓ | ✓ | ✓ | ✓ | ✗ | $O(E+V\log V)$ | **Reference** |
| **A\*** | ✓ | ✓ | ✓ | ✓ | ✗ | $O(E+V\log V)$ | **★ SELECTED** |
| Weighted A\* | ✗ ($\le\varepsilon\cdot$opt) | ✓ | ✓ | ✓ | ✗ | faster | Trade-off study |
| Theta\* | ✓ binary / ✗ weighted | ✓ | ✓ | ⚠️ partial | ✓ | $O(E+V\log V)\cdot$LOS | Comparison |
| Lazy Theta\* | as Theta\* | ✓ | ✓ | ⚠️ partial | ✓ | faster LOS | Comparison |
| Field D\* | ✓ | ✓ | ✓ | ✓ | ✓ | high | Future work |
| D\* Lite | ✓ | ✓ | ✓ | ✓ | ✗ | repair-local | **Replanning role** |
| RRT | ✗ | prob. | ✗ | ⚠️ | ✓ | $O(n\log n)$ | Comparison |
| RRT\* | asymptotic | prob. | ✗ | ⚠️ | ✓ | $O(n\log n)$ | Comparison |
| PRM | asymptotic | prob. | ✗ | ⚠️ | ✓ | build+query | Comparison |
| Potential fields | ✗ | ✗ | ✓ | ✓ | ✓ | $O(1)$/step | Failure demo |

---

## 4. Selection: **A\* on an 8-connected weighted grid, with cost-validated path smoothing**

### 4.1 The decision

**Primary planner: A\*.** With a great-circle/$v_{\max}$ heuristic proved admissible *and*
consistent in `FORMULAS.md` §9.1.

**Post-process: cost-validated shortcut smoothing.** Candidate shortcuts between non-adjacent
waypoints are accepted **only if the actual line-integrated cost along the shortcut is lower
than the original sub-path.** This recovers most of the any-angle benefit *without* Theta\*'s
false homogeneity assumption.

**Replanning: D\* Lite**, for the operational case of newly-discovered hazards.

### 4.2 Why A\* — five reasons, mapped to the problem's structure

**1. The cost field is weighted, not binary.** This is the decisive point that eliminates the
any-angle family as primary. Theta\*'s line-of-sight shortcut is optimal only when the terrain
between two points is uniform. Here cost varies *continuously* with slope, roughness and
crater proximity, so a straight shortcut can silently cross a hazard. A\* evaluates **every
cell it traverses**, so the reported cost is the cost actually incurred.

**2. Optimality is proved, not assumed.** With an admissible and consistent heuristic, A\*
returns a provably minimum-cost path on the discretisation and never re-expands a node. For a
mission-safety deliverable, "provably optimal" and "empirically good" are not
interchangeable. RRT\* offers only *asymptotic* optimality — no finite run carries a bound.

**3. Determinism is mandatory.** A capstone must be reproducible: the same inputs must give
the same route every time, and a reviewer must be able to verify it. Every sampling method
fails this test. A\* is fully deterministic given a tie-breaking rule (LunarSerpent breaks
ties by lower $h$, which biases expansion toward the goal and is itself deterministic).

**4. The problem is low-dimensional.** Sampling methods exist to defeat the curse of
dimensionality in configuration spaces of 6+ DOF. Here the state space is 2-D and modest —
a 1000×1000 AOI is $10^6$ cells, trivially searchable exhaustively. Using RRT\* here would
accept stochasticity and suboptimality to solve a problem that does not exist.

**5. It degenerates gracefully.** Setting $h\equiv 0$ turns A\* into Dijkstra, so the same
implementation produces the optimality reference — guaranteeing the comparison is
apples-to-apples rather than confounded by differing cost accounting.

### 4.3 Honest statement of A\*'s limitation

A\* on an 8-connected grid inherits the discretisation penalty of up to **+8.24 %** in path
length (`FORMULAS.md` §9.2). This is real and is **not concealed**: the benchmark reports A\*'s
path length both before and after smoothing, and against Theta\* and Field D\* references. The
selection rests on the argument that a *correctly-costed* path 8 % longer is preferable to a
*shorter path whose cost is unverified* — and that smoothing recovers most of the difference
anyway.

---

## 5. Why all algorithms are still computed and displayed

The brief requires outputs from the other algorithms, not only the selected one. This is good
scientific practice and each serves a distinct purpose:

| Algorithm | What its output demonstrates |
|---|---|
| **Dijkstra** | The true optimal cost — every other result is reported as a ratio to it |
| **A\*** | Same cost as Dijkstra (validating the heuristic) with far fewer node expansions |
| **BFS** | What ignoring terrain produces — a route that drives over crater rims |
| **Weighted A\*** | The quantified speed-vs-optimality curve as $\varepsilon$ varies |
| **Theta\*** | A geometrically shorter path, and whether its cost is genuinely lower once integrated |
| **RRT\*** | Run-to-run variance — showing directly why stochastic methods were rejected |
| **Potential fields** | The local-minimum trap inside a crater — a concrete failure case |
| **D\* Lite** | Repair cost when a new hazard appears mid-traverse |

Showing A\* alone would be an assertion. Showing all eight makes the selection an
**empirical result**.

---

## 6. Benchmark protocol

To make the comparison fair and reproducible, every algorithm is run under identical
conditions and the following are recorded.

**Controlled variables:** identical cost surface, identical start/goal, identical
connectivity (8-connected where applicable), identical hazard parameters, single-threaded,
same machine.

**Metrics recorded per run:**

| Metric | Why it is recorded |
|---|---|
| Path cost | Primary quality measure; ratio to Dijkstra = optimality gap |
| Path length (m) | Geometric length, 3-D per `FORMULAS.md` §2.2 |
| Traverse time (s) | From the mobility model §7.1 |
| Energy (J) | Often the binding mission constraint |
| Nodes expanded | The true measure of search efficiency, machine-independent |
| Peak open-set size | Memory behaviour |
| Wall-clock (ms) | Practical runtime; reported as median of 5 runs |
| Max / mean slope | Safety characterisation |
| Safety score | `FORMULAS.md` §6.5 |
| Craters intersected / avoided | Direct answer to the brief's reporting requirement |
| Success | Whether a path was found at all |

**Test scenarios**, chosen to exercise different regimes:

1. **Open mare** — gentle terrain; tests baseline efficiency where few obstacles exist.
2. **Dense crater field** — many small obstacles; tests obstacle negotiation.
3. **Highland traverse** — sustained steep slopes; tests the mobility model's binding limits.
4. **Crater-rim crossing** — start and goal separated by a rim; the case where potential
   fields are expected to fail and where the detour-vs-climb trade-off is sharpest.
5. **Polar site** — high latitude; tests the $\cos\varphi$ cell-size correction of
   `FORMULAS.md` §2.4 and the projection switch above 85°.

**Statistical treatment.** Deterministic algorithms are run 5× and the **median** wall-clock
is reported (path is identical by construction). Stochastic algorithms (RRT, RRT\*, PRM) are
run **30×** with mean ± standard deviation on every metric — the variance is itself a
reported result supporting §4.2 reason 3.

---

## 7. Complexity summary

With $V$ cells, $E \approx 8V$ for an 8-connected grid, $b$ the branching factor, $d$ the
solution depth, and $\varepsilon^*$ the heuristic's relative error:

| Algorithm | Time | Space | Note |
|---|---|---|---|
| BFS | $O(V+E)$ | $O(V)$ | Optimal only for uniform cost |
| Dijkstra | $O(E+V\log V)$ | $O(V)$ | Binary heap |
| A\* | $O(b^{\varepsilon^* d})$ | $O(V)$ | Approaches $O(d)$ as $h\to h^*$ |
| Theta\* | A\* × LOS cost | $O(V)$ | LOS is $O(\max(\Delta x,\Delta y))$ per check |
| D\* Lite | $O(k\log V)$ per repair | $O(V)$ | $k$ = affected nodes |
| RRT\* | $O(n\log n)$ | $O(n)$ | $n$ = samples |

The practical significance: A\*'s advantage over Dijkstra grows with map size, because
Dijkstra expands an area $\propto d^2$ (a disc around the start) while A\* with a good
heuristic expands closer to $\propto d$ (an ellipse elongated toward the goal). On the
polar-site scenario this is expected to be a large factor — a prediction the benchmark tests
rather than assumes.

---

## 8. References

1. Dijkstra, E. W. (1959), *A note on two problems in connexion with graphs*, Numerische
   Mathematik **1**, 269–271. DOI: [10.1007/BF01386390](https://doi.org/10.1007/BF01386390)
2. Hart, P. E., Nilsson, N. J. & Raphael, B. (1968), *A Formal Basis for the Heuristic
   Determination of Minimum Cost Paths*, IEEE Trans. SSC **4**(2), 100–107.
   DOI: [10.1109/TSSC.1968.300136](https://doi.org/10.1109/TSSC.1968.300136)
3. Nash, A., Daniel, K., Koenig, S. & Felner, A. (2007), *Theta\*: Any-Angle Path Planning on
   Grids*, Proc. AAAI, 1177–1183.
4. Koenig, S. & Likhachev, M. (2002), *D\* Lite*, Proc. AAAI, 476–483.
5. Ferguson, D. & Stentz, A. (2006), *Using interpolation to improve path planning: The Field
   D\* algorithm*, Journal of Field Robotics **23**(2), 79–101.
   DOI: [10.1002/rob.20109](https://doi.org/10.1002/rob.20109)
6. LaValle, S. M. (1998), *Rapidly-exploring random trees: A new tool for path planning*,
   TR 98-11, Iowa State University.
7. Karaman, S. & Frazzoli, E. (2011), *Sampling-based algorithms for optimal motion planning*,
   Int. J. Robotics Research **30**(7), 846–894.
   DOI: [10.1177/0278364911406761](https://doi.org/10.1177/0278364911406761)
8. Kavraki, L. E., Svestka, P., Latombe, J.-C. & Overmars, M. H. (1996), *Probabilistic
   roadmaps for path planning in high-dimensional configuration spaces*, IEEE Trans. Robotics
   and Automation **12**(4), 566–580. DOI: [10.1109/70.508439](https://doi.org/10.1109/70.508439)
9. Khatib, O. (1986), *Real-time obstacle avoidance for manipulators and mobile robots*,
   Int. J. Robotics Research **5**(1), 90–98. DOI: [10.1177/027836498600500106](https://doi.org/10.1177/027836498600500106)
10. Pearl, J. (1984), *Heuristics: Intelligent Search Strategies for Computer Problem Solving*,
    Addison-Wesley.

---

## 9. Revision history

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-08-04 | Baseline. Eleven algorithms surveyed; A\* selected with cost-validated smoothing; benchmark protocol defined. Benchmark *results* will be appended once the engine is implemented. |
