"""LunarSerpent readiness audit — verifies what exists, what is complete, what is missing."""
import re
from pathlib import Path

ROOT = Path(r"d:\Lunar_Serpent")
DOCS = ROOT / "docs"
HTML = DOCS / "html"

EXPECTED_DOCS = [
    ("README.md", ROOT, "Overview"),
    ("PRD.md", DOCS, "Product Requirements"),
    ("SRD.md", DOCS, "System Requirements"),
    ("FORMULAS.md", DOCS, "Formulas + proofs"),
    ("DATASETS.md", DOCS, "Dataset catalogue"),
    ("TECHNOLOGY.md", DOCS, "Technology rationale"),
    ("ALGORITHMS.md", DOCS, "Planner comparison"),
    ("SCIENCE_BACKGROUND.md", DOCS, "Lunar science"),
    ("CONTRIBUTIONS.md", DOCS, "Provenance: inherited / adapted / original"),
]

ok = lambda b: "PASS" if b else "FAIL"
issues = []

print("=" * 78)
print("1. DOCUMENTS")
print("=" * 78)
print(f"{'FILE':<26}{'KB':>7}{'LINES':>7}{'ENDS OK':>9}{'HTML':>7}{'MATH':>7}")
print("-" * 78)

for name, parent, _ in EXPECTED_DOCS:
    p = parent / name
    if not p.exists():
        print(f"{name:<26}{'MISSING':>36}")
        issues.append(f"{name} missing")
        continue
    txt = p.read_text(encoding="utf-8")
    lines = txt.count("\n") + 1
    kb = p.stat().st_size / 1024

    # A complete document ends with its revision-history table.
    ends = "Revision history" in txt[-2500:]
    # Truncation markers
    if txt.rstrip().endswith(("...", "TODO", "TBD")):
        ends = False
        issues.append(f"{name} looks truncated")

    hp = HTML / (p.stem + ".html")
    has_html = hp.exists() and hp.stat().st_size > 4000
    if not has_html:
        issues.append(f"{p.stem}.html missing/too small")

    math = len(re.findall(r"\$\$?", txt))

    if not ends:
        issues.append(f"{name} has no revision-history block")

    print(f"{name:<26}{kb:>7.1f}{lines:>7}{ok(ends):>9}{ok(has_html):>7}{math:>7}")

print()
print("=" * 78)
print("2. CROSS-DOCUMENT REFERENCES")
print("=" * 78)
stems = {d[0].replace(".md", "") for d in EXPECTED_DOCS}
bad_refs = 0
for name, parent, _ in EXPECTED_DOCS:
    p = parent / name
    if not p.exists():
        continue
    txt = p.read_text(encoding="utf-8")
    for ref in set(re.findall(r"`?([A-Z_]+)\.md`?", txt)):
        if ref not in stems:
            print(f"  BROKEN  {name} -> {ref}.md")
            issues.append(f"{name} references missing {ref}.md")
            bad_refs += 1
if bad_refs == 0:
    print("  All inter-document references resolve.")

print()
print("=" * 78)
print("3. GENERATED SITE")
print("=" * 78)
for f in ["index.html"]:
    p = ROOT / f
    print(f"  {'PASS' if p.exists() else 'FAIL'}  root {f}  ({p.stat().st_size/1024:.0f} KB)"
          if p.exists() else f"  FAIL  root {f} MISSING")
n_html = len(list(HTML.glob("*.html"))) if HTML.exists() else 0
print(f"  {'PASS' if n_html >= 9 else 'FAIL'}  docs/html/ contains {n_html} pages (expect 9)")

print()
print("=" * 78)
print("4. IMPLEMENTATION STATUS  (Phase 1-4 — not yet started)")
print("=" * 78)
code_dirs = ["backend", "backend/core", "backend/data", "backend/analysis",
             "backend/planning", "backend/api", "frontend", "frontend/js",
             "frontend/css", "tests", "scripts"]
for d in code_dirs:
    p = ROOT / d
    if not p.exists():
        print(f"  {d:<24} MISSING DIR")
        continue
    files = [f for f in p.iterdir() if f.is_file()]
    state = f"{len(files)} file(s)" if files else "EMPTY  <- to build"
    print(f"  {d:<24} {state}")

print()
print("=" * 78)
print("5. SUMMARY")
print("=" * 78)
allf = [f for f in ROOT.rglob("*") if f.is_file()]
total = sum(f.stat().st_size for f in allf)
print(f"  Files on disk      : {len(allf)}")
print(f"  Total size         : {total/1024/1024:.2f} MB")
print(f"  Documentation      : {sum((p/n).stat().st_size for n,p,_ in EXPECTED_DOCS if (p/n).exists())/1024:.0f} KB")
print()
if issues:
    print(f"  ISSUES FOUND: {len(issues)}")
    for i in issues:
        print(f"    - {i}")
else:
    print("  NO ISSUES. Phase 0 deliverables complete and verified.")
