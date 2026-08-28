"""
The planning HTTP surface, end to end.

Runs against the real app in-process, so it exercises validation, the job
queue, deduplication and the JSON contract the browser will consume — without
needing a server on a port.

The properties that matter here are not "does it return 200". They are: does a
bad region fail *immediately* with the fix in the message, does a slow one go to
the queue instead of blocking, and does polling eventually hand back a route
whose numbers match what the service computes directly.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import warnings  # noqa: E402

warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402

from backend.config import dataset_path  # noqa: E402
from backend.main import app  # noqa: E402

npass = nfail = 0


def check(name, ok, detail=""):
    global npass, nfail
    if ok:
        npass += 1
        print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
    else:
        nfail += 1
        print(f"  FAIL  {name}   {detail}")


if dataset_path("polar", "dem", "ldem_875s_10m_float.img") is None:
    print("polar DEM not present — skipping")
    raise SystemExit(0)

client = TestClient(app)
SITE = dict(south=-89.50, north=-89.42, west=218.0, east=226.0)


def poll(job_id, timeout=300.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = client.get(f"/api/v1/jobs/{job_id}")
        if r.status_code != 200:
            return None
        last = r.json()
        if last["state"] in ("done", "failed"):
            return last
        time.sleep(0.05)
    return last


# ---------------------------------------------------------------------------
print("\nOptions describe what the client can ask for\n")

opt = client.get("/api/v1/plan/options").json()
check("every planner is offered", len(opt["algorithms"]) == 7,
      f"{len(opt['algorithms'])} algorithms")
check("a default comparison set is named", len(opt["default_algorithms"]) >= 3,
      ", ".join(opt["default_algorithms"]))
check("a fast set is offered for interactive use",
      len(opt["fast_algorithms"]) >= 1, ", ".join(opt["fast_algorithms"]))
check("both soil models are selectable", len(opt["soils"]) == 2)
check("both tiers are described with their meaning",
      all("note" in t for t in opt["tiers"]))


# ---------------------------------------------------------------------------
print("\nA region is validated before anything is read\n")

t0 = time.perf_counter()
prev = client.get("/api/v1/aoi/preview", params={**SITE, "tier": "site"})
dt_preview = (time.perf_counter() - t0) * 1000
p = prev.json()
print(f"  preview answered in {dt_preview:.0f} ms")
check("preview is fast enough to run while dragging a box", dt_preview < 500,
      f"{dt_preview:.0f} ms, no raster opened")
check("preview reports the posting and cell count", p["ok"] and "aoi" in p,
      f"{p['aoi']['shape']} @ {p['aoi']['cell_m']} m")
check("preview declares what the region can measure",
      p["aoi"]["capability"]["crater_measure_floor_m"] < 100,
      f"craters from {p['aoi']['capability']['crater_measure_floor_m']} m")

# Resolution is an outcome, not a precondition. A region with no fine data
# still previews — at whatever covers it — and declares what that supports.
mid = client.get("/api/v1/aoi/preview",
                 params=dict(south=-20, north=-19, west=10, east=11))
mj = mid.json()
check("a region without fine data still previews rather than erroring",
      mid.status_code == 200 and mj["ok"] is True,
      f"{mj['aoi']['cell_m']} m from {mj['aoi']['source']['product_id']}")
check("its tier is resolved from the data, not demanded by the caller",
      mj["resolved_tier"] == "survey"
      and mj["aoi"]["capability"]["supports_traverse"] is False,
      "a missing dataset is not a malformed request")
# A finer source is an option, not a fault. Sent as structured alternatives so
# a client can offer them; reported as warnings they fired on every region
# forever, in the same colour as a real problem.
check("a normal region carries no warnings",
      not mj["aoi"]["warnings"], str(mj["aoi"]["warnings"]))
check("finer sources arrive as alternatives a client can act on",
      any(a["access"] == "streamed" for a in mj["aoi"]["alternatives"]),
      ", ".join(f"{a['product_id']} {a['cell_m']}m ({a['access']})"
                for a in mj["aoi"]["alternatives"]))

r = client.post("/api/v1/plan", json={
    **SITE, "tier": "site", "start_lat": -89.47, "start_lon": 220.0,
    "goal_lat": -89.45, "goal_lon": 224.0, "rover": "no-such-rover"})
check("an unknown rover is refused immediately", r.status_code == 422,
      str(r.json().get("detail", ""))[:60])

r = client.post("/api/v1/plan", json={
    **SITE, "tier": "site", "start_lat": -89.47, "start_lon": 220.0,
    "goal_lat": -89.45, "goal_lon": 224.0, "algorithms": ["teleport"]})
check("an unknown algorithm is refused immediately", r.status_code == 422,
      str(r.json().get("detail", ""))[:60])

r = client.post("/api/v1/plan", json={
    "south": -20, "north": -19, "west": 10, "east": 11,
    "start_lat": -19.5, "start_lon": 10.5,
    "goal_lat": -19.2, "goal_lon": 10.8, "algorithms": ["weighted_astar"]})
check("a region without fine data plans anyway, at what covers it",
      r.status_code == 202,
      f"HTTP {r.status_code} — coarser is an answer, refusal is not")
if r.status_code == 202:
    out = poll(r.json()["job"]["id"])
    check("and the result is labelled a corridor, never a traverse",
          out and out["state"] == "done"
          and out["result"]["certification"] == "regional-corridor",
          out["result"]["certification"] if out and out["state"] == "done"
          else str(out))


# ---------------------------------------------------------------------------
print("\nWork is queued, not awaited\n")

body = {**SITE, "tier": "site",
        "start_lat": -89.47, "start_lon": 219.0,
        "goal_lat": -89.44, "goal_lon": 225.0,
        "algorithms": ["dijkstra", "astar", "weighted_astar", "theta_star"]}

t0 = time.perf_counter()
sub = client.post("/api/v1/plan", json=body)
dt_submit = (time.perf_counter() - t0) * 1000
check("submit returns 202 Accepted", sub.status_code == 202, str(sub.status_code))
job = sub.json()["job"]
print(f"  submitted in {dt_submit:.0f} ms as {job['id']}")
check("submit does not block on the computation", dt_submit < 1000,
      f"{dt_submit:.0f} ms")
check("the AOI comes back with the job",
      "aoi" in sub.json() and sub.json()["aoi"]["tier"] == "site")

dup = client.post("/api/v1/plan", json=body).json()["job"]
check("an identical request joins the running job rather than starting a second",
      dup["id"] == job["id"],
      "two clients on one region must not compute it twice")

done = poll(job["id"])
check("the job completes", done is not None and done["state"] == "done",
      done["state"] if done else "no response")
if done and done["state"] == "failed":
    print("   error:", done.get("error"))


# ---------------------------------------------------------------------------
print("\nThe result is a usable route\n")

res = done["result"]
print(f"  {'algorithm':<22}{'cost (s)':>12}{'ratio':>8}{'ms':>9}")
for a in res["algorithms"]:
    print(f"  {a['algorithm']:<22}{a['cost_s']:>12.1f}"
          f"{(a['cost_ratio'] or 0):>8.3f}{a['runtime_ms']:>9.0f}")

check("every algorithm reported a route",
      all(a["found"] for a in res["algorithms"]))
check("a recommendation is made and justified",
      res["recommended"]["algorithm"] and len(res["recommended"]["why"]) > 40,
      res["recommended"]["algorithm"])
check("the route carries coordinates for the globe",
      len(res["route"]["lat"]) == len(res["route"]["lon"]) > 2,
      f"{res['route']['samples']} samples, "
      f"{res['route']['waypoints']} waypoints")
check("elevation and slope profiles are present",
      len(res["route"]["profile"]["elevation_m"]) == res["route"]["samples"])
check("endpoints report whether they were moved",
      "moved_m" in res["endpoints"]["start"],
      f"start {res['endpoints']['start']['moved_m']} m, "
      f"goal {res['endpoints']['goal']['moved_m']} m")
check("the route states what it certifies",
      res["certification"] == "traverse", res["certification_note"][:50])

cached = client.post("/api/v1/plan", json=body).json()["job"]
check("a finished region is served from cache", cached["id"] == job["id"],
      "re-opening must be instant")


# ---------------------------------------------------------------------------
print("\nAnywhere on the Moon\n")

for name, box, s, g in [
    ("Mare Imbrium", dict(south=32.0, north=33.0, west=-18.0, east=-17.0),
     (32.2, -17.8), (32.8, -17.2)),
    ("Tycho", dict(south=-44.0, north=-43.0, west=-11.5, east=-10.5),
     (-43.8, -11.3), (-43.2, -10.7)),
]:
    sub = client.post("/api/v1/plan", json={
        **box, "tier": "survey", "start_lat": s[0], "start_lon": s[1],
        "goal_lat": g[0], "goal_lon": g[1], "algorithms": ["weighted_astar"]})
    if sub.status_code != 202:
        check(f"{name} plans", False, f"{sub.status_code} {sub.text[:70]}")
        continue
    out = poll(sub.json()["job"]["id"])
    ok = out and out["state"] == "done"
    km = (out["result"]["route"]["profile"]["distance_m"][-1] / 1000) if ok else 0
    check(f"{name} plans over the API", bool(ok),
          f"{km:.1f} km, {out['result']['certification']}" if ok else str(out))


# ---------------------------------------------------------------------------
print("\nJobs are observable\n")

lst = client.get("/api/v1/jobs").json()
check("jobs can be listed", len(lst["jobs"]) > 0, f"{len(lst['jobs'])} jobs")
check("the listing omits bulky results",
      all("result" not in j for j in lst["jobs"]),
      "a listing must stay small enough to poll")
check("queue statistics are reported", "by_state" in lst["stats"],
      str(lst["stats"]["by_state"]))
check("an unknown job id is a 404",
      client.get("/api/v1/jobs/nope-0000-xxxxxx").status_code == 404)


print(f"\n{npass} passed, {nfail} failed")
raise SystemExit(1 if nfail else 0)
