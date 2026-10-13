#!/usr/bin/env python3
"""Compare ordered control/treatment route geometry and cost from frozen site JSON."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

def normalise_route(route):
    if not isinstance(route, list) or not route:
        raise ValueError("route must be a non-empty list")
    points = []
    for point in route:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            raise ValueError(f"invalid route point: {point!r}")
        points.append([round(float(point[0]), 9), round(float(point[1]), 9)])
    return points

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    source = Path(args.input)
    data = json.loads(source.read_text(encoding="utf-8"))
    sites = data.get("sites", [])
    if not isinstance(sites, list) or not sites:
        raise SystemExit("ERROR: JSON must contain a non-empty 'sites' array")
    results, seen = [], set()
    for site in sites:
        for key in ("site_id", "input_hashes", "control", "treatment"):
            if key not in site:
                raise SystemExit(f"ERROR: site missing {key}")
        if site["site_id"] in seen:
            raise SystemExit(f"ERROR: duplicate site_id {site['site_id']}")
        seen.add(site["site_id"])
        control, treatment = site["control"], site["treatment"]
        for label, record in (("control", control), ("treatment", treatment)):
            if record.get("route_cost") is None or not record.get("config_hash"):
                raise SystemExit(f"ERROR: {site['site_id']} {label} route_cost/config_hash missing")
        c_route, t_route = normalise_route(control.get("route")), normalise_route(treatment.get("route"))
        c_cost, t_cost = float(control["route_cost"]), float(treatment["route_cost"])
        results.append({"site_id": site["site_id"], "input_hashes": site["input_hashes"],
            "control_route_points": len(c_route), "treatment_route_points": len(t_route),
            "exact_ordered_route_match_at_1e-9": c_route == t_route,
            "control_route_cost": c_cost, "treatment_route_cost": t_cost,
            "relative_cost_change_pct": ((t_cost - c_cost) / c_cost * 100) if c_cost else None,
            "control_config_hash": control["config_hash"], "treatment_config_hash": treatment["config_hash"]})
    report = {"input": str(source),
        "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "site_count": len(results),
        "all_routes_identical": all(x["exact_ordered_route_match_at_1e-9"] for x in results),
        "sites": results,
        "warning": "Equal route costs do not imply equal route geometry. Verify input hashes and configs before interpreting this comparison."}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"site_count": report["site_count"],
        "all_routes_identical": report["all_routes_identical"], "output": str(out)}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
