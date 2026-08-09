"""
LunarSerpent — documentation site builder.

Converts every Markdown file in ``docs/`` into a styled, cross-linked HTML page
under ``docs/html/``, with a shared sidebar, per-page table of contents and
KaTeX-typeset mathematics.

Run:  python scripts/build_docs.py
Then open:  docs/html/index.html

Design notes
------------
* Mathematics is *protected* from the Markdown parser before conversion and
  restored afterwards.  Without this, ``$d/D$`` and ``x_i`` get mangled into
  emphasis markup and the equations render as garbage.
* Both light and dark themes are supported and follow the OS preference, with a
  manual toggle that persists in ``localStorage``.
* Wide tables scroll inside their own container so the page body never scrolls
  horizontally.
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

try:
    import markdown
except ImportError:  # pragma: no cover
    sys.exit("markdown is required:  python -m pip install markdown")

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
OUT = DOCS / "html"

# Order and presentation of the navigation sidebar.
NAV: list[tuple[str, str, str]] = [
    # (filename stem, short title, one-line description)
    ("README", "Overview", "What LunarSerpent is and how to run it"),
    ("PRD", "PRD", "Product requirements — goals, features, acceptance"),
    ("SRD", "SRD", "System requirements — architecture and interfaces"),
    ("FORMULAS", "Formulas", "Every equation with proof and citation"),
    ("DATASETS", "Datasets", "Data sources, access methods and provenance"),
    ("TECHNOLOGY", "Technology", "Stack selection and justification"),
    ("ALGORITHMS", "Algorithms", "Path planner survey, comparison, selection"),
    ("SCIENCE_BACKGROUND", "Lunar Science", "Surface science and exploration insights"),
]

MATH_BLOCK = re.compile(r"\$\$(.+?)\$\$", re.S)
MATH_INLINE = re.compile(r"(?<![\\$])\$(?!\s)([^$\n]+?)(?<!\s)\$(?!\$)")


def protect_math(text: str) -> tuple[str, list[str]]:
    """Replace math with opaque placeholders so Markdown cannot corrupt it."""
    store: list[str] = []

    def stash(m: re.Match, display: bool) -> str:
        store.append((m.group(1), display))  # type: ignore[arg-type]
        return f"\x00MATH{len(store) - 1}\x00"

    text = MATH_BLOCK.sub(lambda m: stash(m, True), text)
    text = MATH_INLINE.sub(lambda m: stash(m, False), text)
    return text, store


def restore_math(html_text: str, store: list) -> str:
    """Put the math back, escaped, wrapped for KaTeX auto-render."""
    for i, (expr, display) in enumerate(store):
        esc = html.escape(expr)
        rendered = (
            f'<div class="math-block">\\[{esc}\\]</div>'
            if display
            else f'<span class="math-inline">\\({esc}\\)</span>'
        )
        # The placeholder may have been wrapped in <p> by the parser.
        html_text = html_text.replace(f"<p>\x00MATH{i}\x00</p>", rendered)
        html_text = html_text.replace(f"\x00MATH{i}\x00", rendered)
    return html_text


def rewrite_links(html_text: str) -> str:
    """Point inter-document .md links at their generated .html counterparts."""
    return re.sub(
        r'href="([A-Za-z_0-9]+)\.md((?:#[^"]*)?)"',
        r'href="\1.html\2"',
        html_text,
    )


CSS = """
:root{
  --bg:#0d1117; --bg-alt:#161b22; --bg-code:#1c2128;
  --fg:#e6edf3; --fg-dim:#9198a1; --fg-faint:#6e7681;
  --accent:#58a6ff; --accent-dim:#1f6feb; --border:#30363d;
  --ok:#3fb950; --warn:#d29922; --bad:#f85149;
  --sidebar:290px;
}
:root[data-theme="light"]{
  --bg:#ffffff; --bg-alt:#f6f8fa; --bg-code:#f6f8fa;
  --fg:#1f2328; --fg-dim:#59636e; --fg-faint:#818b98;
  --accent:#0969da; --accent-dim:#0550ae; --border:#d1d9e0;
  --ok:#1a7f37; --warn:#9a6700; --bad:#cf222e;
}
@media (prefers-color-scheme: light){
  :root:not([data-theme="dark"]){
    --bg:#ffffff; --bg-alt:#f6f8fa; --bg-code:#f6f8fa;
    --fg:#1f2328; --fg-dim:#59636e; --fg-faint:#818b98;
    --accent:#0969da; --accent-dim:#0550ae; --border:#d1d9e0;
    --ok:#1a7f37; --warn:#9a6700; --bad:#cf222e;
  }
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{
  margin:0; background:var(--bg); color:var(--fg);
  font:16px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif;
  -webkit-font-smoothing:antialiased;
}
a{color:var(--accent); text-decoration:none}
a:hover{text-decoration:underline}

/* ---------- layout ---------- */
.wrap{display:flex; min-height:100vh}
.sidebar{
  width:var(--sidebar); flex:0 0 var(--sidebar); background:var(--bg-alt);
  border-right:1px solid var(--border); padding:24px 0; position:sticky; top:0;
  height:100vh; overflow-y:auto;
}
.brand{padding:0 24px 20px; border-bottom:1px solid var(--border); margin-bottom:16px}
.brand h1{margin:0; font-size:19px; letter-spacing:-.02em}
.brand .sub{color:var(--fg-faint); font-size:12px; margin-top:4px; letter-spacing:.02em}
.navlist{list-style:none; margin:0; padding:0 12px}
.navlist a{
  display:block; padding:9px 12px; border-radius:6px; color:var(--fg-dim);
  font-size:14px; line-height:1.35;
}
.navlist a:hover{background:var(--bg); color:var(--fg); text-decoration:none}
.navlist a.active{background:var(--accent-dim); color:#fff}
.navlist a.active .nd{color:rgba(255,255,255,.75)}
.navlist .nt{font-weight:600; display:block}
.navlist .nd{color:var(--fg-faint); font-size:11.5px; display:block; margin-top:2px}

.main{flex:1; min-width:0; display:flex; justify-content:center; padding:0 32px}
.content{max-width:900px; width:100%; padding:40px 0 120px}

/* ---------- typography ---------- */
h1,h2,h3,h4{line-height:1.25; letter-spacing:-.015em; scroll-margin-top:24px}
h1{font-size:34px; margin:0 0 24px; padding-bottom:14px; border-bottom:1px solid var(--border)}
h2{font-size:24px; margin:44px 0 16px; padding-bottom:8px; border-bottom:1px solid var(--border)}
h3{font-size:19px; margin:32px 0 12px}
h4{font-size:16px; margin:24px 0 10px; color:var(--fg-dim)}
p{margin:0 0 16px}
ul,ol{margin:0 0 16px; padding-left:26px}
li{margin:5px 0}
hr{border:0; border-top:1px solid var(--border); margin:36px 0}
strong{font-weight:650}

blockquote{
  margin:20px 0; padding:12px 18px; border-left:3px solid var(--accent);
  background:var(--bg-alt); border-radius:0 6px 6px 0; color:var(--fg-dim);
}
blockquote p:last-child{margin-bottom:0}

code{
  background:var(--bg-code); padding:.15em .4em; border-radius:5px;
  font:.87em/1.5 ui-monospace,"Cascadia Code",Consolas,monospace;
  border:1px solid var(--border);
}
pre{
  background:var(--bg-code); border:1px solid var(--border); border-radius:8px;
  padding:16px; overflow-x:auto; margin:0 0 18px;
}
pre code{background:none; border:0; padding:0; font-size:13px; line-height:1.55}

/* ---------- tables ---------- */
.tablewrap{overflow-x:auto; margin:0 0 20px; border:1px solid var(--border); border-radius:8px}
table{border-collapse:collapse; width:100%; font-size:14.5px}
th,td{padding:9px 14px; text-align:left; border-bottom:1px solid var(--border);
      vertical-align:top}
th{background:var(--bg-alt); font-weight:650; white-space:nowrap}
tr:last-child td{border-bottom:0}
tbody tr:hover{background:var(--bg-alt)}
td code{white-space:nowrap}

/* ---------- math ---------- */
.math-block{margin:20px 0; overflow-x:auto; overflow-y:hidden; padding:4px 0}
.katex{font-size:1.04em}
.katex-display{margin:0 !important}

/* ---------- TOC ---------- */
.toc{
  background:var(--bg-alt); border:1px solid var(--border); border-radius:8px;
  padding:16px 20px; margin:0 0 32px;
}
.toc-title{font-size:12px; text-transform:uppercase; letter-spacing:.08em;
           color:var(--fg-faint); font-weight:700; margin-bottom:10px}
.toc ul{list-style:none; padding-left:0; margin:0}
.toc ul ul{padding-left:16px}
.toc li{margin:3px 0}
.toc a{color:var(--fg-dim); font-size:13.5px}
.toc a:hover{color:var(--accent)}

/* ---------- chrome ---------- */
.topbar{display:flex; justify-content:space-between; align-items:center;
        margin-bottom:28px; gap:16px; flex-wrap:wrap}
.crumb{color:var(--fg-faint); font-size:13px}
.themebtn{
  background:var(--bg-alt); color:var(--fg-dim); border:1px solid var(--border);
  border-radius:6px; padding:6px 12px; cursor:pointer; font-size:13px;
}
.themebtn:hover{color:var(--fg); border-color:var(--accent)}
.footer{margin-top:64px; padding-top:20px; border-top:1px solid var(--border);
        color:var(--fg-faint); font-size:13px}

/* ---------- index cards ---------- */
.cards{display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr));
       gap:16px; margin:24px 0}
.card{background:var(--bg-alt); border:1px solid var(--border); border-radius:10px;
      padding:18px 20px; transition:border-color .15s, transform .15s}
.card:hover{border-color:var(--accent); transform:translateY(-2px)}
.card a{font-size:16px; font-weight:650}
.card p{color:var(--fg-dim); font-size:13.5px; margin:6px 0 0}

@media (max-width:900px){
  .wrap{flex-direction:column}
  .sidebar{width:100%; flex:none; height:auto; position:static; border-right:0;
           border-bottom:1px solid var(--border)}
  .main{padding:0 18px}
}
@media print{
  .sidebar,.themebtn,.topbar{display:none}
  body{background:#fff; color:#000}
  .main{padding:0}
}
"""

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — LunarSerpent</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<style>{css}</style>
</head>
<body>
<div class="wrap">
  <nav class="sidebar">
    <div class="brand">
      <h1>LunarSerpent</h1>
      <div class="sub">Lunar Analysis &amp; Traverse Planning</div>
    </div>
    <ul class="navlist">{nav}</ul>
  </nav>
  <div class="main">
    <div class="content">
      <div class="topbar">
        <span class="crumb">docs / {stem}.md</span>
        <button class="themebtn" onclick="toggleTheme()">Toggle theme</button>
      </div>
      {toc}
      {body}
      <div class="footer">
        LunarSerpent documentation · generated from <code>docs/{stem}.md</code>
      </div>
    </div>
  </div>
</div>
<script>
function toggleTheme(){{
  var r=document.documentElement;
  var cur=r.getAttribute('data-theme');
  if(!cur){{cur=window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';}}
  var next=cur==='dark'?'light':'dark';
  r.setAttribute('data-theme',next);
  try{{localStorage.setItem('ls-theme',next);}}catch(e){{}}
}}
(function(){{
  try{{var s=localStorage.getItem('ls-theme');
      if(s)document.documentElement.setAttribute('data-theme',s);}}catch(e){{}}
}})();
</script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"
  onload="renderMathInElement(document.body,{{delimiters:[
    {{left:'\\\\[',right:'\\\\]',display:true}},
    {{left:'\\\\(',right:'\\\\)',display:false}}],throwOnError:false}});"></script>
</body>
</html>
"""


def build_nav(active: str) -> str:
    out = []
    for stem, title, desc in NAV:
        if not (DOCS / f"{stem}.md").exists() and stem != "README":
            continue
        cls = ' class="active"' if stem == active else ""
        out.append(
            f'<li><a href="{stem}.html"{cls}>'
            f'<span class="nt">{html.escape(title)}</span>'
            f'<span class="nd">{html.escape(desc)}</span></a></li>'
        )
    return "\n".join(out)


def convert(md_path: Path, stem: str) -> str:
    raw = md_path.read_text(encoding="utf-8")
    protected, store = protect_math(raw)

    md = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc", "attr_list", "sane_lists"],
        extension_configs={"toc": {"permalink": False, "toc_depth": "2-3"}},
    )
    body = md.convert(protected)
    body = restore_math(body, store)
    body = rewrite_links(body)
    body = body.replace("<table>", '<div class="tablewrap"><table>').replace(
        "</table>", "</table></div>"
    )

    toc_html = getattr(md, "toc", "") or ""
    toc = (
        f'<div class="toc"><div class="toc-title">Contents</div>{toc_html}</div>'
        if toc_html.count("<li>") > 2
        else ""
    )

    title = stem.replace("_", " ").title()
    m = re.search(r"^#\s+(.+)$", raw, re.M)
    if m:
        title = re.sub(r"—.*$", "", m.group(1)).strip() or title

    return PAGE.format(
        title=html.escape(title),
        css=CSS,
        nav=build_nav(stem),
        toc=toc,
        body=body,
        stem=stem,
    )


def _doc_exists(stem: str) -> bool:
    return (DOCS / f"{stem}.md").exists() or (ROOT / f"{stem}.md").exists()


def build_index() -> str:
    cards = []
    for stem, title, desc in NAV:
        if not _doc_exists(stem):
            continue
        cards.append(
            f'<div class="card"><a href="{stem}.html">{html.escape(title)}</a>'
            f"<p>{html.escape(desc)}</p></div>"
        )
    body = (
        "<h1>LunarSerpent Documentation</h1>"
        "<p>Scientific decision-support system for lunar surface analysis and "
        "rover traverse planning. Every displayed value traces to a documented "
        "formula with a peer-reviewed source.</p>"
        f'<div class="cards">{"".join(cards)}</div>'
    )
    return PAGE.format(
        title="Documentation",
        css=CSS,
        nav=build_nav(""),
        toc="",
        body=body,
        stem="index",
    )


ROOT_LANDING = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LunarSerpent</title>
<style>{css}
body{{display:block}}
.hero{{max-width:960px; margin:0 auto; padding:56px 28px 100px}}
.hero h1{{font-size:44px; border:0; margin:0 0 8px; padding:0}}
.tag{{color:var(--fg-dim); font-size:18px; margin:0 0 8px}}
.lede{{color:var(--fg-dim); font-size:15.5px; max-width:70ch; margin:20px 0 0}}
.badges{{display:flex; gap:8px; flex-wrap:wrap; margin:24px 0 0}}
.badge{{background:var(--bg-alt); border:1px solid var(--border); border-radius:20px;
       padding:5px 14px; font-size:12.5px; color:var(--fg-dim)}}
.badge.ok{{border-color:var(--ok); color:var(--ok)}}
.sec{{margin:52px 0 0}}
.sec h2{{font-size:15px; text-transform:uppercase; letter-spacing:.09em;
        color:var(--fg-faint); border:0; padding:0; margin:0 0 18px}}
.files{{display:grid; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); gap:14px}}
.f{{background:var(--bg-alt); border:1px solid var(--border); border-radius:10px;
   padding:18px 20px; transition:border-color .15s, transform .15s}}
.f:hover{{border-color:var(--accent); transform:translateY(-2px)}}
.f .t{{font-size:16px; font-weight:650}}
.f .d{{color:var(--fg-dim); font-size:13.5px; margin:6px 0 10px}}
.f .l{{display:flex; gap:14px; font-size:12.5px}}
.f .l a{{color:var(--fg-faint)}}
.f .l a:hover{{color:var(--accent)}}
.note{{background:var(--bg-alt); border-left:3px solid var(--accent);
      border-radius:0 8px 8px 0; padding:14px 18px; color:var(--fg-dim);
      font-size:14px; margin:20px 0 0}}
.tablewrap{{margin-top:8px}}
</style>
</head>
<body>
<div class="hero">
  <h1>LunarSerpent</h1>
  <p class="tag">Lunar surface analysis &amp; rover traverse planning</p>
  <div class="badges">
    <span class="badge ok">Phase&nbsp;0 · Documentation complete</span>
    <span class="badge">{ndocs} documents</span>
    <span class="badge">{nkb} KB</span>
    <span class="badge">Math typeset with KaTeX</span>
  </div>
  <p class="lede">A scientific decision-support system built on LOLA topography, the Robbins
  crater catalogue and Chandrayaan-2 imagery. Every displayed number traces to a documented
  formula with a peer-reviewed source; where a quantity cannot be determined with justified
  confidence, the system states its uncertainty rather than producing a plausible-looking
  value.</p>

  <div class="sec">
    <h2>Documentation</h2>
    <div class="files">{cards}</div>
  </div>

  <div class="sec">
    <h2>Reading these files</h2>
    <p class="note"><strong>Rendered</strong> opens the styled HTML with typeset mathematics —
    this is the readable version. <strong>Source</strong> opens the raw Markdown.
    Regenerate everything at any time with <code>python scripts/build_docs.py</code>.</p>
  </div>
</div>
<script>
(function(){{
  try{{var s=localStorage.getItem('ls-theme');
      if(s)document.documentElement.setAttribute('data-theme',s);}}catch(e){{}}
}})();
</script>
</body>
</html>
"""


def build_root_landing() -> str:
    """A one-click entry point at the project root."""
    cards, ndocs, nbytes = [], 0, 0
    for stem, title, desc in NAV:
        src = DOCS / f"{stem}.md"
        rel_md = f"docs/{stem}.md"
        if not src.exists():
            src = ROOT / f"{stem}.md"
            rel_md = f"{stem}.md"
        if not src.exists():
            continue
        ndocs += 1
        nbytes += src.stat().st_size
        cards.append(
            f'<div class="f"><div class="t">{html.escape(title)}</div>'
            f'<div class="d">{html.escape(desc)}</div>'
            f'<div class="l"><a href="docs/html/{stem}.html">Rendered &rarr;</a>'
            f'<a href="{rel_md}">Source</a></div></div>'
        )
    return ROOT_LANDING.format(
        css=CSS,
        cards="".join(cards),
        ndocs=ndocs,
        nkb=f"{nbytes/1024:.0f}",
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    built = 0

    for stem, _, _ in NAV:
        src = DOCS / f"{stem}.md"
        if not src.exists():
            src = ROOT / f"{stem}.md"  # README lives at the project root
        if not src.exists():
            print(f"  skip   {stem}.md (not found)")
            continue
        (OUT / f"{stem}.html").write_text(convert(src, stem), encoding="utf-8")
        size = (OUT / f"{stem}.html").stat().st_size
        print(f"  built  {stem}.html  ({size/1024:.0f} KB)")
        built += 1

    (OUT / "index.html").write_text(build_index(), encoding="utf-8")
    print("  built  index.html")

    (ROOT / "index.html").write_text(build_root_landing(), encoding="utf-8")
    print("  built  ../index.html   <- project-root entry point")

    print(f"\n{built + 2} pages generated")
    print(f"\n  START HERE:  {ROOT / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
