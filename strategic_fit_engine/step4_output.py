"""
Step 4 — GP Bullhound Report Dashboard

Professional report in GP Bullhound house style:
- Inline bull logo SVG
- Condensed sections (no workflow/impact bloat)
- SVG charts: company ranking, DCF annual FCF, EV bridge
- Interactive table, modals, DCF calculator with CSV export

Outputs: output/report.html
"""
from __future__ import annotations

import json, math, os, re, time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

DATA_DIR   = Path(__file__).parent / "data"
OUTPUT_DIR = Path(__file__).parent / "output"
MODEL      = "claude-sonnet-4-6"


# ──────────────────────────────────────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────────────────────────────────────

def _h(v) -> str:
    return (str(v).replace("&","&amp;").replace("<","&lt;")
            .replace(">","&gt;").replace('"',"&quot;"))

def _fmt_m(v) -> str:
    if v in (None,"Not publicly available","N/A"): return "N/A"
    try: return f"€{float(v):.0f}M"
    except: return str(v)

def _fmt_emp(v) -> str:
    if v in (None,"Not publicly available"): return "N/A"
    try: return f"{int(v):,}"
    except: return str(v)

def _list_str(v) -> str:
    if isinstance(v, list):
        parts = [x for x in v if x != "Not publicly available"]
        return ", ".join(parts) if parts else "N/A"
    return "N/A" if not v or v == "Not publicly available" else str(v)

def _call_claude(client, prompt: str, max_tokens: int = 600) -> str:
    r = client.messages.create(model=MODEL, max_tokens=max_tokens,
        messages=[{"role":"user","content":prompt}])
    return "\n".join(b.text for b in r.content if hasattr(b,"text"))

def _with_retry(fn, retries=3):
    for attempt in range(retries):
        try: return fn()
        except anthropic.RateLimitError:
            time.sleep(5*(2**attempt))
        except anthropic.APIStatusError as e:
            if attempt==retries-1: raise
            time.sleep(2**attempt)
    raise RuntimeError("Max retries exceeded")


# ──────────────────────────────────────────────────────────────────────────────
# GP Bullhound Bull Logo (inline SVG)
# ──────────────────────────────────────────────────────────────────────────────

BULL_LOGO = """<svg xmlns="http://www.w3.org/2000/svg" width="83.729" height="65.861" viewBox="0 0 83.729 65.861" style="height:44px;width:auto">
  <path d="M145.038,197c.1.1.2.207.306.309a.355.355,0,0,0,.5.094c.078-.034.158-.064.231-.094a.7.7,0,0,1,.3.449,1.8,1.8,0,0,0,.137.358c.113.232.245.455.35.689a.8.8,0,0,0,.523.459c.426.134.848.283,1.273.422a4.67,4.67,0,0,1,1.585.844c.574.481,1.142.968,1.713,1.452.3.251.593.5.886.752a1.421,1.421,0,0,1,.54.855c.028.186.012.378.022.566.013.274.016.55.051.822a.971.971,0,0,0,.575.775,2.5,2.5,0,0,0,.28.132,17.342,17.342,0,0,0,2.68.835,3.631,3.631,0,0,1,.695.192,1.027,1.027,0,0,1,.67,1.3c-.038.15-.094.295-.139.443a3.085,3.085,0,0,0-.09,1.253c.026.222.067.442.108.662a1.654,1.654,0,0,1-.025.716,5.265,5.265,0,0,1-.812,1.91,3.657,3.657,0,0,1-1.262,1.123,13.617,13.617,0,0,1-1.348.581,3.1,3.1,0,0,1-.658.123.8.8,0,0,0-.548.306,1.792,1.792,0,0,1-1.5.677,4.88,4.88,0,0,1-2.954-.92,1.292,1.292,0,0,0-.953-.235,3.979,3.979,0,0,0-.851.2,7.019,7.019,0,0,0-3.112,2.349,3.159,3.159,0,0,0-.673,1.944c-.006.774.044,1.549.075,2.322a13.282,13.282,0,0,1-.078,2.5,5.247,5.247,0,0,1-.188.8,19.087,19.087,0,0,1-4.387,7.4c-.554.589-1.135,1.154-1.7,1.729-.164.165-.33.328-.494.492a6.688,6.688,0,0,0-1.014,1.3c-1.725,2.869-3.468,5.728-5.2,8.6a42.319,42.319,0,0,0-2.144,4.148c-.435.944-.844,1.9-1.21,2.876a7.841,7.841,0,0,0-.512,3.01c.017.568-.012,1.137.01,1.7a7.676,7.676,0,0,0,.132,1.308,2.628,2.628,0,0,0,1.277,1.71c.278.171.567.327.837.511a1.388,1.388,0,0,1,.62,1.028,1.674,1.674,0,0,1-1.025,1.71,2.842,2.842,0,0,1-.879.18c-.947.018-1.894.005-2.841-.009a1.229,1.229,0,0,1-.823-.386,2.3,2.3,0,0,1-.556-.89,6.318,6.318,0,0,1-.35-2.1c-.011-.525.022-1.051-.005-1.575-.069-1.307-.157-2.612-.245-3.918-.047-.7-.106-1.39-.171-2.084a2.1,2.1,0,0,0-.126-.6,1.781,1.781,0,0,1,.241-1.78,9.679,9.679,0,0,0,1.594-3.688,8.327,8.327,0,0,0,.025-2.644c-.095-.673-.206-1.345-.263-2.021a10.35,10.35,0,0,1,0-1.471c.04-.678.117-1.355.176-2.032.007-.076,0-.152,0-.247-.162-.019-.322-.043-.482-.056a28.429,28.429,0,0,1-4.219-.712,57.123,57.123,0,0,1-5.665-1.75,21.981,21.981,0,0,0-2.692-.7,25.049,25.049,0,0,0-3.4-.47c-.9-.066-1.8-.133-2.706-.156a15.573,15.573,0,0,0-3.086.216,3.48,3.48,0,0,0-1.049.346,1.673,1.673,0,0,0-.831,1c-.315.964-.613,1.937-.987,2.878a13.815,13.815,0,0,1-3.263,4.908,31.925,31.925,0,0,1-6.736,5.008,10.825,10.825,0,0,1-1.026.484q-1.3.547-2.6,1.072a2.921,2.921,0,0,0-1.085.726,9.845,9.845,0,0,0-.826.991c-.5.718-.994,1.447-1.463,2.189-.45.713-.889,1.435-1.291,2.176-.422.778-.8,1.582-1.188,2.376a2.879,2.879,0,0,0-.149.412,1.709,1.709,0,0,0,.283,1.611c.206.276.435.534.643.809a1.5,1.5,0,0,1,.151,1.518.6.6,0,0,1-.374.372,3.43,3.43,0,0,1-.769.2c-1.081.081-2.165.138-3.248.2a2.546,2.546,0,0,1-.54-.038,1.046,1.046,0,0,1-.827-.628,1.965,1.965,0,0,1-.114-1.553q.158-.423.342-.835c.458-1.029.934-2.051,1.38-3.086q.878-2.041,1.918-4a13.764,13.764,0,0,0,1.27-3.451c.106-.469.265-.925.395-1.389a1.863,1.863,0,0,1,.8-1.041,8.944,8.944,0,0,0,.935-.728,4.048,4.048,0,0,0,1.194-1.895c.8-2.74,1.75-5.434,2.665-8.139.4-1.188.718-2.406,1.072-3.61a.235.235,0,0,0,0-.073c-.26.176-.508.362-.772.521a9.348,9.348,0,0,1-2.234.926,13.335,13.335,0,0,1-4.288.511,8.826,8.826,0,0,1-3.243-.777,3.714,3.714,0,0,1-.976-.623,2.49,2.49,0,0,1-.562-.708,1.759,1.759,0,0,1,.2-.054,7.485,7.485,0,0,1,1.8.029,15.821,15.821,0,0,0,2.239.134,8.979,8.979,0,0,0,7.616-4.409c.495-.8.938-1.625,1.39-2.446a15.758,15.758,0,0,1,3.708-4.5,5.175,5.175,0,0,1,.729-.531,19.466,19.466,0,0,1,5.258-2.153,17.969,17.969,0,0,1,2.6-.394c1.151-.1,2.3-.09,3.458-.086.843,0,1.686-.047,2.529-.094.592-.033,1.184-.09,1.774-.151a17.729,17.729,0,0,0,2.725-.566c1.6-.426,3.2-.875,4.81-1.282,1.475-.373,2.962-.7,4.442-1.054a43.05,43.05,0,0,0,7.265-2.4c.747-.326,1.527-.578,2.293-.863l.629-.231a6.817,6.817,0,0,0,3.239-2.423c.845-1.155,1.756-2.255,2.705-3.324a24.031,24.031,0,0,1,3.589-3.41l.416-.307a1.655,1.655,0,0,0,.6-.822,5.144,5.144,0,0,1,.555-1.19,4.973,4.973,0,0,1,1.624-1.525q.9-.549,1.809-1.1a.813.813,0,0,0,.11-.1Z" transform="translate(-74.671 -197)" fill="#fff"/>
</svg>"""

PROJECT_NAMES = ["Eagle", "Falcon", "Summit", "Atlas", "Apex", "Meridian", "Phoenix", "Titan"]


# ──────────────────────────────────────────────────────────────────────────────
# DCF Calculation
# ──────────────────────────────────────────────────────────────────────────────

def calculate_dcf(top: Dict) -> Dict:
    base_rev   = 700.0
    ebitda_m   = 0.15
    fcf_conv   = 0.55
    growths    = [0.10, 0.09, 0.08, 0.07, 0.06]
    wacc       = 0.105
    tgr        = 0.030
    syn_pct    = 0.20

    years, prev, sum_pv = [], base_rev, 0.0
    for i, g in enumerate(growths, 1):
        rev    = prev * (1+g)
        ebitda = rev * ebitda_m
        fcf    = ebitda * fcf_conv
        df     = (1+wacc)**i
        pv     = fcf/df
        sum_pv += pv
        years.append({"year":f"FY{2024+i}","growth_pct":round(g*100,1),
                      "revenue":round(rev,1),"ebitda":round(ebitda,1),
                      "fcf":round(fcf,1),"discount_factor":round(df,4),
                      "pv_fcf":round(pv,1)})
        prev = rev
    tv   = years[-1]["fcf"]*(1+tgr)/(wacc-tgr)
    pvtv = tv/(1+wacc)**5
    ev   = sum_pv+pvtv
    syn  = ev*syn_pct
    acq  = ev+syn
    return {
        "target_name": top.get("name","Target"),
        "assumptions": {"base_revenue_eur_m":base_rev,"ebitda_margin_pct":round(ebitda_m*100,1),
                        "fcf_pct_ebitda":round(fcf_conv*100,1),"wacc_pct":round(wacc*100,1),
                        "terminal_growth_pct":round(tgr*100,1),"synergy_premium_pct":round(syn_pct*100,1)},
        "years":years, "sum_pv_fcf":round(sum_pv,1), "terminal_value":round(tv,1),
        "pv_terminal_value":round(pvtv,1), "enterprise_value":round(ev,1),
        "synergy_value":round(syn,1), "acquisition_price":round(acq,1),
        "ev_revenue_multiple":round(ev/base_rev,2),
    }


# ──────────────────────────────────────────────────────────────────────────────
# SVG Charts
# ──────────────────────────────────────────────────────────────────────────────

def _svg_dcf_bars(dcf: Dict) -> str:
    """Vertical bar chart — annual PV of FCF."""
    years  = dcf["years"]
    values = [y["pv_fcf"] for y in years]
    W, H   = 420, 200
    pl,pr,pt,pb = 52, 16, 28, 38
    cw  = W-pl-pr
    ch  = H-pt-pb
    mv  = max(values)*1.25
    bw  = cw/len(values)*0.55
    gap = cw/len(values)

    grid = "".join(
        f'<line x1="{pl}" y1="{pt+ch*(1-lv/mv):.1f}" x2="{W-pr}" y2="{pt+ch*(1-lv/mv):.1f}" '
        f'stroke="#edf2f7" stroke-width="1"/>'
        f'<text x="{pl-5}" y="{pt+ch*(1-lv/mv)+4:.1f}" text-anchor="end" '
        f'font-size="8" fill="#9e9e9e">€{lv:.0f}M</text>'
        for lv in [mv*0.25, mv*0.5, mv*0.75, mv]
    )
    bars = ""
    for i,(yr,val) in enumerate(zip(years,values)):
        x    = pl + i*gap + gap*0.225
        bh   = ch*val/mv
        y    = pt+ch-bh
        fade = 0.95 - i*0.14
        bars += (f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
                 f'fill="#252850" opacity="{fade:.2f}"/>'
                 f'<text x="{x+bw/2:.1f}" y="{y-5:.1f}" text-anchor="middle" '
                 f'font-size="9" fill="#252850" font-weight="700">€{val:.0f}M</text>'
                 f'<text x="{x+bw/2:.1f}" y="{pt+ch+14:.1f}" text-anchor="middle" '
                 f'font-size="9" fill="#718096">{yr["year"]}</text>')

    axes = (f'<line x1="{pl}" y1="{pt}" x2="{pl}" y2="{pt+ch}" stroke="#cbd5e0" stroke-width="1"/>'
            f'<line x1="{pl}" y1="{pt+ch}" x2="{W-pr}" y2="{pt+ch}" stroke="#cbd5e0" stroke-width="1"/>')
    title = f'<text x="{W/2:.0f}" y="16" text-anchor="middle" font-size="11" font-weight="700" fill="#0B1C3D">Annual PV of Free Cash Flow (€M)</text>'
    return f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg">{title}{grid}{axes}{bars}</svg>'


def _svg_ev_bridge(dcf: Dict) -> str:
    """Horizontal bar bridge: components → enterprise value → acquisition price."""
    W, H = 420, 180
    pl,pr,pt,pb = 110, 60, 20, 10
    cw = W-pl-pr

    items = [
        ("PV of FCFs",         dcf["sum_pv_fcf"],      "#252850", 0.9),
        ("PV Terminal Value",  dcf["pv_terminal_value"],"#120A8F", 0.85),
        ("Synergy Premium",    dcf["synergy_value"],    "#CC0605", 1.0),
        ("Acquisition Price",  dcf["acquisition_price"],"#015D52", 1.0),
    ]
    max_val = max(v for _,v,_,_ in items) * 1.1
    row_h   = (H-pt-pb) / len(items)
    bh      = row_h * 0.52

    bars = ""
    for i, (label, val, color, opacity) in enumerate(items):
        y  = pt + i*row_h + (row_h-bh)/2
        bw = cw * val / max_val
        bars += (f'<rect x="{pl}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
                 f'fill="{color}" opacity="{opacity}" rx="3"/>'
                 f'<text x="{pl-6}" y="{y+bh/2+3.5:.1f}" text-anchor="end" '
                 f'font-size="10" fill="#2d3748" font-weight="600">{_h(label)}</text>'
                 f'<text x="{pl+bw+6:.1f}" y="{y+bh/2+3.5:.1f}" '
                 f'font-size="10" fill="{color}" font-weight="700">€{val:,.0f}M</text>')

    title = f'<text x="{W/2:.0f}" y="14" text-anchor="middle" font-size="11" font-weight="700" fill="#0B1C3D">Enterprise Value Bridge (€M)</text>'
    return f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg">{title}{bars}</svg>'


def _svg_scores_chart(targets: List[Dict]) -> str:
    """Horizontal bar chart of all company total scores."""
    W, H  = 540, max(220, len(targets)*28+50)
    pl,pr,pt,pb = 170, 70, 30, 20
    cw   = W-pl-pr
    maxs = targets[0].get("max_score", 35) if targets else 35
    rh   = (H-pt-pb)/len(targets)
    bh   = rh * 0.55

    grid = "".join(
        f'<line x1="{pl+cw*v/maxs:.1f}" y1="{pt}" x2="{pl+cw*v/maxs:.1f}" y2="{H-pb}" '
        f'stroke="#edf2f7" stroke-width="1"/>'
        f'<text x="{pl+cw*v/maxs:.1f}" y="{H-pb+12}" text-anchor="middle" font-size="9" fill="#9e9e9e">{v}</text>'
        for v in range(0, maxs+1, 5)
    )
    bars = ""
    for i, t in enumerate(targets):
        y     = pt + i*rh + (rh-bh)/2
        score = t.get("total_score", 0)
        bw    = cw*score/maxs
        rank  = t.get("rank", i+1)
        color = "#015D52" if rank<=3 else ("#CC0605" if rank<=6 else "#9ca3af")
        name  = t.get("name","")
        if len(name)>22: name=name[:20]+"…"
        bars += (f'<rect x="{pl}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
                 f'fill="{color}" opacity="0.85" rx="2"/>'
                 f'<text x="{pl-6}" y="{y+bh/2+3.5:.1f}" text-anchor="end" '
                 f'font-size="10" fill="#2d3748" font-weight="600">#{rank} {_h(name)}</text>'
                 f'<text x="{pl+bw+5:.1f}" y="{y+bh/2+3.5:.1f}" '
                 f'font-size="10" fill="{color}" font-weight="700">{score}/{maxs}</text>')

    title = f'<text x="{W/2:.0f}" y="18" text-anchor="middle" font-size="11" font-weight="700" fill="#0B1C3D">Strategic Fit Scores — All Targets (out of {maxs})</text>'
    return f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg">{title}{grid}{bars}</svg>'


def _radar_svg(targets: List[Dict], criteria: List[Dict], names: List[str]) -> str:
    n = len(criteria)
    if n < 3: return ""
    size, cx, cy, maxr = 280, 140, 140, 100
    angles = [math.pi/2 + 2*math.pi*i/n for i in range(n)]

    grid = "".join(
        f'<polygon points="{" ".join(f"{cx+maxr*lv/5*math.cos(a):.1f},{cy-maxr*lv/5*math.sin(a):.1f}" for a in angles)}" '
        f'fill="none" stroke="#e2e8f0" stroke-width="0.8"/>'
        for lv in range(1,6)
    )
    axes = "".join(
        f'<line x1="{cx}" y1="{cy}" x2="{cx+maxr*math.cos(a):.1f}" y2="{cy-maxr*math.sin(a):.1f}" stroke="#cbd5e0" stroke-width="0.8"/>'
        f'<text x="{cx+(maxr+20)*math.cos(a):.1f}" y="{cy-(maxr+20)*math.sin(a):.1f}" '
        f'text-anchor="middle" dominant-baseline="middle" font-size="8" fill="#4a5568" font-weight="600">'
        f'{_h(" ".join(c.get("name","").split()[:2]))}</text>'
        for a,c in zip(angles,criteria)
    )
    COLORS = [("rgba(37,40,80,0.6)","#252850"),("rgba(204,6,5,0.55)","#CC0605"),("rgba(1,93,82,0.55)","#015D52")]
    tmap   = {t["name"].lower():t for t in targets}
    polys  = ""
    for idx,name in enumerate(names[:3]):
        t = tmap.get(name.lower())
        if not t: continue
        sc    = t.get("scores",{})
        pts   = " ".join(
            f"{cx+maxr*sc.get(c['id'],{}).get('score',1)/5*math.cos(a):.1f},{cy-maxr*sc.get(c['id'],{}).get('score',1)/5*math.sin(a):.1f}"
            for a,c in zip(angles,criteria)
        )
        fill,stroke = COLORS[idx]
        polys += f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="2" opacity="0.9"/>'

    return (f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg">'
            f'{grid}{axes}{polys}</svg>')


# ──────────────────────────────────────────────────────────────────────────────
# CSS
# ──────────────────────────────────────────────────────────────────────────────

CSS = """
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;600;700&family=IBM+Plex+Mono:wght@400;600&display=swap');

*{box-sizing:border-box;margin:0;padding:0}
:root{
  --red:#CC0605;
  --navy:#252850;
  --ultra:#120A8F;
  --opal:#015D52;
  --pastel:#5D9B9B;
  --yellow:#FAD201;
  --bg:#F4F4F4;
  --white:#ffffff;
  --text:#2C2C2C;
  --muted:#6b7280;
  --border:#e5e7eb;
  --green:#015D52;
  --amber:#F9A825;
  --grey:#9ca3af;
  --r:0px;
  --sh:0 1px 3px rgba(0,0,0,.08),0 1px 2px rgba(0,0,0,.06)
}
html{scroll-behavior:smooth}
body{font-family:'IBM Plex Sans',Helvetica,Arial,sans-serif;font-size:13.5px;
  line-height:1.6;color:var(--text);background:var(--bg)}

/* ── Cover bar ── */
.cover-bar{background:var(--red);height:6px;width:100%}

/* ── Header ── */
header{background:var(--navy);padding:24px 56px;
  display:flex;justify-content:space-between;align-items:center}
.logo-wrap{display:flex;align-items:center;gap:18px}
.logo-wordmark{font-size:18px;font-weight:700;color:#fff;letter-spacing:-.2px;
  font-family:'IBM Plex Sans',sans-serif}
.logo-wordmark span{color:var(--red)}
.header-right{text-align:right}
.doc-title{font-size:15px;font-weight:600;color:#fff;letter-spacing:-.1px}
.doc-meta{font-size:11px;color:rgba(255,255,255,.5);margin-top:3px}
.confidential{display:inline-block;margin-top:6px;font-size:9px;font-weight:600;
  letter-spacing:1.5px;text-transform:uppercase;color:var(--red);
  border:1px solid rgba(204,6,5,.4);padding:2px 9px}

/* ── Nav ── */
nav{background:var(--navy);border-top:1px solid rgba(255,255,255,.08);
  padding:0 56px;display:flex;position:sticky;top:0;z-index:100;
  border-bottom:1px solid rgba(255,255,255,.05)}
nav a{color:rgba(255,255,255,.45);text-decoration:none;padding:12px 16px;
  font-size:11px;font-weight:600;letter-spacing:.6px;text-transform:uppercase;
  border-bottom:2px solid transparent;margin-bottom:-1px;transition:all .18s}
nav a:hover,nav a.active{color:#fff;border-bottom-color:var(--red)}

/* ── Page ── */
.page{max-width:1080px;margin:0 auto;padding:44px 40px}
section{margin-bottom:56px}

/* ── Section header ── */
.sh{display:flex;align-items:center;gap:0;margin-bottom:24px}
.sh-num{background:var(--red);color:#fff;font-size:9px;font-weight:700;
  padding:4px 10px;letter-spacing:1.5px;text-transform:uppercase;
  font-family:'IBM Plex Mono',monospace;margin-right:14px}
.sh-title{font-size:18px;font-weight:600;color:var(--navy);letter-spacing:-.2px}
.sh-rule{flex:1;height:1px;background:var(--border);margin-left:16px}

/* ── KPI row ── */
.kpi-row{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;
  margin-bottom:32px;background:var(--border);border:1px solid var(--border)}
@media(max-width:700px){.kpi-row{grid-template-columns:repeat(2,1fr)}}
.kpi{background:var(--white);padding:20px 22px}
.kpi.red{border-top:3px solid var(--red)}
.kpi.navy{border-top:3px solid var(--navy)}
.kpi-val{font-size:28px;font-weight:700;color:var(--navy);line-height:1;
  font-family:'IBM Plex Sans',sans-serif;letter-spacing:-.5px}
.kpi.red .kpi-val{color:var(--red)}
.kpi-label{font-size:10px;color:var(--muted);margin-top:5px;font-weight:600;
  text-transform:uppercase;letter-spacing:.8px}

/* ── Tables ── */
.tbl-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;background:var(--white);
  border:1px solid var(--border);margin-bottom:16px}
th{background:var(--navy);color:#fff;padding:10px 14px;text-align:left;
  font-size:10px;font-weight:600;letter-spacing:.8px;text-transform:uppercase;
  cursor:pointer;user-select:none;white-space:nowrap;
  font-family:'IBM Plex Mono',monospace}
th:hover{background:#1e2244}
th .si{margin-left:4px;opacity:.4;font-size:9px}
th.sorted .si{opacity:1;color:var(--red)}
td{padding:10px 14px;border-bottom:1px solid var(--border);vertical-align:top;font-size:13px}
tr:last-child td{border-bottom:none}
tr.cr{cursor:pointer}
tr.cr:hover td{background:#f9fafb!important}

/* ── Tier colours ── */
.t-top td{background:#f0fdf4!important;border-left:3px solid var(--green)}
.t-mid td{background:#fffbeb!important;border-left:3px solid var(--amber)}
.t-low td{background:#fafafa!important;border-left:3px solid var(--grey)}

/* ── Score chip ── */
.sc{display:inline-block;padding:2px 8px;
  font-size:10px;font-weight:700;color:#fff;min-width:24px;text-align:center;
  font-family:'IBM Plex Mono',monospace}
.sc5{background:var(--opal)}.sc4{background:#2d8653}
.sc3{background:var(--amber);color:#1a1a1a}.sc2{background:#e07b39}.sc1{background:var(--red)}

/* ── Risk badge ── */
.risk{display:inline-block;background:#fff0f0;color:var(--red);
  font-size:10px;font-weight:600;padding:2px 7px;
  margin:2px 2px 2px 0;border:1px solid rgba(204,6,5,.2)}

/* ── Criteria badge ── */
.cb{display:inline-block;padding:3px 9px;
  font-size:11px;font-weight:600;margin:3px 3px 3px 0}
.cb-met{background:#e6f9f4;color:#015D52;border:1px solid #9de2d0}
.cb-par{background:#fffbeb;color:#92400e;border:1px solid #fde68a}
.cb-no{background:#f9fafb;color:#6b7280;border:1px solid var(--border)}

/* ── Priorities ── */
.prio{list-style:none}
.prio li{padding:8px 12px 8px 24px;position:relative;
  border-left:3px solid var(--red);margin-bottom:4px;
  background:var(--white);font-size:13px}
.prio li::before{content:"—";position:absolute;left:8px;color:var(--red);font-size:10px;top:10px}

/* ── Callout ── */
.callout{background:#f8f9ff;border-left:4px solid var(--navy);
  padding:14px 18px;margin-bottom:18px;font-size:13px}

/* ── Filters ── */
.fbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:14px}
.fbar select,.fbar input{border:1px solid var(--border);
  padding:7px 11px;font-size:12.5px;background:#fff;outline:none;color:var(--text);
  font-family:'IBM Plex Sans',sans-serif}
.fbar select:focus,.fbar input:focus{border-color:var(--navy)}
.fbar label{font-size:10px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.8px}

/* ── Legend ── */
.legend{display:flex;gap:18px;flex-wrap:wrap;margin-bottom:12px}
.li{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted)}
.ld{width:10px;height:10px}

/* ── Radar ── */
.radar-wrap{display:flex;gap:32px;align-items:flex-start;flex-wrap:wrap;margin-bottom:32px}
.radar-leg{display:flex;flex-direction:column;gap:10px;padding-top:12px}
.rl{display:flex;align-items:center;gap:8px;font-size:12px}
.rd{width:10px;height:10px;border-radius:50%}

/* ── Charts ── */
.chart-pair{display:grid;grid-template-columns:1fr 1fr;gap:1px;
  margin-bottom:24px;background:var(--border);border:1px solid var(--border)}
@media(max-width:780px){.chart-pair{grid-template-columns:1fr}}
.chart-box{background:var(--white);padding:24px;text-align:center}

/* ── DCF ── */
.dcf-layout{display:grid;grid-template-columns:280px 1fr;gap:1px;
  margin-bottom:20px;background:var(--border);border:1px solid var(--border)}
@media(max-width:780px){.dcf-layout{grid-template-columns:1fr}}
.asm-panel{background:var(--white);padding:22px}
.asm-panel h4{font-size:10px;font-weight:700;color:var(--navy);
  margin-bottom:16px;text-transform:uppercase;letter-spacing:.8px;
  font-family:'IBM Plex Mono',monospace}
.asm-r{display:flex;justify-content:space-between;align-items:center;
  margin-bottom:10px;gap:6px}
.asm-l{font-size:12px;color:var(--muted);flex:1}
.asm-i{width:82px;border:1px solid var(--border);
  padding:5px 8px;font-size:12px;text-align:right;font-weight:600;color:var(--navy);
  font-family:'IBM Plex Mono',monospace}
.asm-i:focus{outline:none;border-color:var(--navy)}
.dcf-kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;
  margin-top:16px;background:var(--border);border:1px solid var(--border)}
@media(max-width:700px){.dcf-kpis{grid-template-columns:repeat(2,1fr)}}
.dk{background:var(--white);padding:16px 18px;text-align:center}
.dk.hl{border-top:3px solid var(--red)}
.dk-val{font-size:22px;font-weight:700;color:var(--navy);line-height:1;
  font-family:'IBM Plex Sans',sans-serif;letter-spacing:-.3px}
.dk.hl .dk-val{color:var(--red)}
.dk-lbl{font-size:10px;color:var(--muted);margin-top:5px;font-weight:600;letter-spacing:.3px}
.dcf-note{font-size:11px;color:var(--muted);margin-top:10px;font-style:italic}
.btn{display:inline-block;padding:9px 18px;font-size:11px;
  font-weight:700;cursor:pointer;border:none;transition:all .15s;
  letter-spacing:.5px;text-transform:uppercase;font-family:'IBM Plex Sans',sans-serif}
.btn-nv{background:var(--navy);color:#fff}
.btn-nv:hover{background:#1e2244}
.btn-rd{background:var(--red);color:#fff}
.btn-rd:hover{background:#a80504}

/* ── Client summary ── */
.cs-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:1px;
  background:var(--border);border:1px solid var(--border)}
.csc{background:var(--white);transition:transform .15s,box-shadow .15s}
.csc:hover{transform:translateY(-2px);box-shadow:0 6px 20px rgba(0,0,0,.1)}
.csc-top{background:var(--navy);padding:14px 16px;color:#fff;
  border-left:4px solid var(--red)}
.csc-rank{font-size:9px;color:rgba(255,255,255,.5);font-weight:700;
  text-transform:uppercase;letter-spacing:1px;margin-bottom:3px;
  font-family:'IBM Plex Mono',monospace}
.csc-name{font-size:14px;font-weight:600}
.csc-sub{font-size:11px;color:rgba(255,255,255,.45);margin-top:2px}
.csc-score{font-size:17px;font-weight:700;color:var(--red)}
.csc-row{display:flex;justify-content:space-between;align-items:flex-start}
.csc-body{padding:14px 16px}
.csc-desc{font-size:12px;color:#4b5563;margin-bottom:10px;line-height:1.55}
.csc-badges{display:flex;flex-wrap:wrap;gap:4px}

/* ── Modal ── */
#mo{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);
  z-index:1000;align-items:center;justify-content:center}
#mo.open{display:flex}
.modal{background:var(--white);max-width:720px;
  width:94%;max-height:88vh;overflow-y:auto;
  box-shadow:0 20px 60px rgba(0,0,0,.3)}
.mh{background:var(--navy);padding:20px 24px;color:#fff;
  display:flex;justify-content:space-between;align-items:flex-start;
  position:sticky;top:0;z-index:1;border-left:5px solid var(--red)}
.mx{background:none;border:none;color:#fff;font-size:22px;cursor:pointer;opacity:.6}
.mx:hover{opacity:1}
.mb{padding:24px}
.ms{margin-bottom:16px}
.ms h4{font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;
  color:var(--muted);margin-bottom:8px;font-family:'IBM Plex Mono',monospace}
.ms p{font-size:13px;color:var(--text);line-height:1.6}

/* ── Rubric ── */
.rj{font-size:11px;color:var(--muted);font-style:italic}

/* ── Footer ── */
footer{background:var(--navy);color:rgba(255,255,255,.35);text-align:center;
  padding:20px 56px;font-size:11px;margin-top:48px;
  border-top:3px solid var(--red)}
footer strong{color:#fff}

/* ── Company Report ── */
.company-report{background:var(--white);
  border:1px solid var(--border);margin-bottom:40px;
  border-top:4px solid var(--red)}
.cr-header{background:var(--navy);padding:26px 32px;color:#fff;
  border-left:6px solid var(--red)}
.cr-rank{font-size:9px;color:rgba(255,255,255,.5);font-weight:700;
  text-transform:uppercase;letter-spacing:1.5px;margin-bottom:6px;
  font-family:'IBM Plex Mono',monospace}
.cr-title{font-size:22px;font-weight:600;margin-bottom:10px;letter-spacing:-.2px}
.cr-meta{font-size:11px;color:rgba(255,255,255,.5)}
.cr-section{padding:26px 32px;border-bottom:1px solid var(--border)}
.cr-section:last-child{border-bottom:none}
.cr-sh{font-size:13px;font-weight:700;color:var(--navy);margin-bottom:16px;
  padding-bottom:8px;border-bottom:2px solid var(--red);
  text-transform:uppercase;letter-spacing:.5px;
  font-family:'IBM Plex Mono',monospace}
.callout-imp{background:#fff5f5;border-left:4px solid var(--red);
  padding:14px 18px;margin-bottom:16px}
.callout-note2{background:#f0f4ff;border-left:4px solid var(--ultra);
  padding:14px 18px;margin-top:14px;font-size:12.5px}
.roadmap-list{padding-left:0;list-style:none}
.roadmap-list li{padding:10px 14px 10px 52px;position:relative;
  margin-bottom:6px;background:#f9fafb;border-left:2px solid var(--border);font-size:13px}
.roadmap-list li .ph-num{position:absolute;left:14px;top:50%;transform:translateY(-50%);
  width:22px;height:22px;background:var(--navy);color:#fff;
  font-weight:700;font-size:11px;
  display:flex;align-items:center;justify-content:center;
  font-family:'IBM Plex Mono',monospace}
.rec-badge{display:inline-block;padding:5px 16px;
  color:#fff;font-weight:700;font-size:12px;letter-spacing:1px;
  text-transform:uppercase;margin-bottom:10px;
  font-family:'IBM Plex Mono',monospace}

/* ── Snapshot side-by-side table ── */
.snapshot-tbl{width:100%;border-collapse:collapse;background:var(--white);
  border:1px solid var(--border);margin-bottom:0}
.snapshot-tbl thead th{background:var(--navy);color:#fff;padding:10px 14px;
  font-size:10px;font-weight:600;letter-spacing:.8px;text-transform:uppercase;
  font-family:'IBM Plex Mono',monospace}
.snapshot-tbl tbody td{padding:11px 14px;border-bottom:1px solid var(--border);
  font-size:13px;vertical-align:top;width:50%}
.snapshot-tbl tbody tr:last-child td{border-bottom:none}
.snapshot-tbl tbody tr:nth-child(even) td{background:#f9fafb}

/* ── Deal footer strip ── */
.cr-deal-footer{display:grid;grid-template-columns:repeat(4,1fr);gap:0;
  background:var(--navy);border-top:3px solid var(--red)}
@media(max-width:700px){.cr-deal-footer{grid-template-columns:repeat(2,1fr)}}
.cr-df-item{padding:14px 18px;border-right:1px solid rgba(255,255,255,.07)}
.cr-df-item:last-child{border-right:none}
.cr-df-label{display:block;font-size:9px;font-weight:700;text-transform:uppercase;
  letter-spacing:1px;color:rgba(255,255,255,.4);margin-bottom:5px;
  font-family:'IBM Plex Mono',monospace}
.cr-df-val{display:block;font-size:13px;font-weight:600;color:#fff}

/* ── SVG chart overrides ── */
.chart-box svg text{font-family:'IBM Plex Sans',sans-serif}
"""

# ──────────────────────────────────────────────────────────────────────────────
# JavaScript
# ──────────────────────────────────────────────────────────────────────────────

JS = """
// Nav active on scroll
const _secs = document.querySelectorAll('section[id]');
const _nav  = document.querySelectorAll('nav a[href^="#"]');
const _obs  = new IntersectionObserver(entries=>{
  entries.forEach(e=>{if(e.isIntersecting){
    _nav.forEach(l=>l.classList.remove('active'));
    const a=document.querySelector(`nav a[href="#${e.target.id}"]`);
    if(a)a.classList.add('active');
  }});
},{threshold:0.3});
_secs.forEach(s=>_obs.observe(s));

// Table sort & filter
function initTable(tid,sid,cid,stid){
  const tbl=document.getElementById(tid);if(!tbl)return;
  const tb=tbl.querySelector('tbody');
  let rows=Array.from(tb.querySelectorAll('tr'));
  let sc=-1,sa=true;
  tbl.querySelectorAll('th[data-col]').forEach(th=>{
    th.addEventListener('click',()=>{
      const c=parseInt(th.dataset.col);
      sa=sc===c?!sa:true;sc=c;
      tbl.querySelectorAll('th').forEach(h=>h.classList.remove('sorted'));
      th.classList.add('sorted');
      th.querySelector('.si').textContent=sa?'▲':'▼';
      rows.sort((a,b)=>{
        const av=a.querySelectorAll('td')[c]?.dataset.val||a.querySelectorAll('td')[c]?.textContent||'';
        const bv=b.querySelectorAll('td')[c]?.dataset.val||b.querySelectorAll('td')[c]?.textContent||'';
        const an=parseFloat(av),bn=parseFloat(bv);
        if(!isNaN(an)&&!isNaN(bn))return sa?an-bn:bn-an;
        return sa?av.localeCompare(bv):bv.localeCompare(av);
      });
      rows.forEach(r=>tb.appendChild(r));
      applyF();
    });
  });
  function applyF(){
    const t=document.getElementById(sid)?.value.toLowerCase()||'';
    const c=document.getElementById(cid)?.value||'';
    const s=document.getElementById(stid)?.value||'';
    rows.forEach(r=>{
      const show=(!t||r.textContent.toLowerCase().includes(t))
        &&(!c||r.dataset.country===c)&&(!s||r.dataset.stage===s);
      r.style.display=show?'':'none';
    });
  }
  [sid,cid,stid].forEach(id=>{
    const el=document.getElementById(id);
    if(el){el.addEventListener('input',applyF);el.addEventListener('change',applyF);}
  });
}

// Modal
function openModal(d){
  document.getElementById('mc').innerHTML=d;
  document.getElementById('mo').classList.add('open');
  document.body.style.overflow='hidden';
}
function closeModal(){
  document.getElementById('mo').classList.remove('open');
  document.body.style.overflow='';
}
document.getElementById('mo').addEventListener('click',e=>{
  if(e.target===document.getElementById('mo'))closeModal();
});
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal();});

// DCF recalc
function recalcDCF(){
  const br=parseFloat(document.getElementById('dcf-br').value)||700;
  const em=parseFloat(document.getElementById('dcf-em').value)||15;
  const fc=parseFloat(document.getElementById('dcf-fc').value)||55;
  const wc=parseFloat(document.getElementById('dcf-wc').value)/100||.105;
  const tg=parseFloat(document.getElementById('dcf-tg').value)/100||.03;
  const sp=parseFloat(document.getElementById('dcf-sp').value)/100||.20;
  const gs=[.10,.09,.08,.07,.06];
  let pr=br,spv=0;
  document.querySelectorAll('.dcf-yr').forEach((r,i)=>{
    const rev=pr*(1+gs[i]),eb=rev*em/100,fc2=eb*fc/100,df=Math.pow(1+wc,i+1),pv=fc2/df;
    spv+=pv;pr=rev;
    const cs=r.querySelectorAll('td');
    if(cs[1])cs[1].textContent='€'+rev.toFixed(0)+'M';
    if(cs[2])cs[2].textContent='€'+eb.toFixed(0)+'M';
    if(cs[3])cs[3].textContent='€'+fc2.toFixed(0)+'M';
    if(cs[4])cs[4].textContent=df.toFixed(3);
    if(cs[5])cs[5].textContent='€'+pv.toFixed(0)+'M';
  });
  const tv=pr*(1+gs[4])*em/100*fc/100*(1+tg)/(wc-tg);
  const ptv=tv/Math.pow(1+wc,5);
  const ev=spv+ptv,syn=ev*sp,acq=ev+syn;
  const s=(id,v)=>{const el=document.getElementById(id);if(el)el.textContent=v;};
  s('d-spv','€'+spv.toFixed(0)+'M');s('d-tv','€'+tv.toFixed(0)+'M');
  s('d-ptv','€'+ptv.toFixed(0)+'M');s('d-ev','€'+ev.toFixed(0)+'M');
  s('d-syn','€'+syn.toFixed(0)+'M');s('d-acq','€'+acq.toFixed(0)+'M');
  s('d-mult',(ev/br).toFixed(1)+'x');
}

function dlCSV(){
  const rows=[['Year','Revenue (€M)','EBITDA (€M)','FCF (€M)','Discount Factor','PV FCF (€M)']];
  document.querySelectorAll('.dcf-yr').forEach(r=>
    rows.push(Array.from(r.querySelectorAll('td')).map(td=>td.textContent)));
  rows.push([]);
  [['Sum PV FCFs','d-spv'],['Terminal Value','d-tv'],['PV Terminal Value','d-ptv'],
   ['Enterprise Value','d-ev'],['Synergy Value','d-syn'],['Acquisition Price','d-acq'],
   ['EV/Revenue','d-mult']].forEach(([l,id])=>rows.push([l,document.getElementById(id)?.textContent||'']));
  const b=new Blob([rows.map(r=>r.join(',')).join('\\n')],{type:'text/csv'});
  const a=document.createElement('a');a.href=URL.createObjectURL(b);
  a.download='DCF_Valuation.csv';a.click();
}

initTable('tgtbl','ts','tc','tst');
"""


# ──────────────────────────────────────────────────────────────────────────────
# Company detail generation (Claude call per top-3 target)
# ──────────────────────────────────────────────────────────────────────────────

def _extract_json_local(raw: str) -> Any:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        try: return json.loads(fence.group(1).strip())
        except json.JSONDecodeError: pass
    try: return json.loads(text)
    except json.JSONDecodeError: pass
    s = text.find("{"); e = text.rfind("}")
    if s != -1 and e != -1 and e > s:
        try: return json.loads(text[s:e+1])
        except json.JSONDecodeError: pass
    raise ValueError("JSON parse failed")


def generate_company_detail(client, buyer: str, company: Dict, criteria: List[Dict]) -> Dict:
    name      = company.get("name", "")
    country   = company.get("country", "")
    stage     = company.get("funding_stage", "")
    raised    = company.get("total_raised_usd_m", "N/A")
    arr       = company.get("arr_usd_m", "N/A")
    employees = company.get("employees", "N/A")
    product   = company.get("product_description", "")
    customers = company.get("key_customers", [])
    investors = company.get("key_investors", [])
    news      = company.get("recent_news", "")
    total     = company.get("total_score", 0)
    max_s     = company.get("max_score", 35)
    fit_sum   = company.get("strategic_fit_summary", "")
    sf_rel    = company.get("salesforce_relevance", company.get("buyer_relevance", ""))
    risks_raw = company.get("deal_breaker_risks", [])
    scores_d  = company.get("scores", {})

    crit_lines = "\n".join(
        f"- {c['id']} ({c['name']}): {scores_d.get(c['id'],{}).get('score',0)}/5 — {scores_d.get(c['id'],{}).get('rationale','')}"
        for c in criteria
    )
    custs_str  = ", ".join(customers) if isinstance(customers, list) else str(customers)
    invest_str = ", ".join(investors) if isinstance(investors, list) else str(investors)

    prompt = f"""You are a Managing Director at GP Bullhound preparing a Transaction Snapshot brief.

Target: {name} ({country}) | Acquiror: {buyer}
Stage: {stage} | Total Raised: ${raised}M | ARR: ~${arr}M | Employees: ~{employees}
Product: {product}
Key Customers: {custs_str}
Key Investors: {invest_str}
Recent News: {news}
Strategic Fit Score: {total}/{max_s}
Strategic Fit Summary: {fit_sum}
Buyer Relevance: {sf_rel}
Identified Risks: {', '.join(risks_raw) if risks_raw else 'None'}

Criterion Scores:
{crit_lines}

Return ONLY raw JSON (no markdown, no preamble):
{{
  "priority": "High",
  "sector_label": "e.g. B2B SaaS / Healthcare IT",
  "mission": "1-sentence company mission",
  "scale": "summary e.g. ~€45M ARR · 280 employees · 120 enterprise clients",
  "synergy": "core strategic reason {buyer} should acquire this company",
  "moat": "proprietary data / tech / network effect advantage",
  "company_profile": "3-4 sentence professional summary of product and market position",
  "acquiror_mission": "1-sentence description of {buyer}'s relevant strategy or product line",
  "acquiror_scale": "summary of {buyer}'s relevant scale in this sector",
  "kpis": [
    {{"kpi": "ARR / Revenue", "value": "~€XM", "status": "🟢 Premium", "trend": "▲ X% YoY"}},
    {{"kpi": "Revenue Multiple", "value": "X.Xx ARR", "status": "🟡 Market Rate", "trend": "▲ X%"}},
    {{"kpi": "Headcount Growth", "value": "~X employees", "status": "🟢 Scaling", "trend": "▲ X% YoY"}},
    {{"kpi": "Customer Retention", "value": "~X%", "status": "🟢 Best-in-Class", "trend": "✅ Stable"}},
    {{"kpi": "Burn Rate", "value": "~€XM/mo", "status": "🟡 Moderate", "trend": "▼ Improving"}}
  ],
  "exec_summary": "2-sentence high-level strategic why for a Managing Director audience",
  "rationale": "2-3 sentences expanding on transaction rationale — white space, moats, and specific synergies with {buyer}",
  "advisory_view": "2 sentences: why this company is a Category Killer or irreplaceable strategic asset for {buyer}",
  "recommendation": "PROCEED",
  "next_steps": "2 sentences on immediate next steps",
  "deal_type": "Buy-side",
  "estimated_valuation": "€X–YM",
  "lead_dealmaker": "Managing Director, Technology M&A",
  "strategic_value_score": 8.2
}}
Rules:
- recommendation = exactly one of: PROCEED / MONITOR / DISCARD
- priority = exactly one of: High / Medium / Low
- strategic_value_score = float 1.0-10.0 calibrated to the {total}/{max_s} fit score
- All figures use ~ prefix for estimates. Use €M denomination.
- Every field must be specific to {name} and {buyer} — zero generic filler text."""

    raw = _with_retry(lambda: _call_claude(client, prompt, max_tokens=1600))
    try:
        return _extract_json_local(raw)
    except Exception:
        pct = total / max_s if max_s else 0.5
        rec = "PROCEED" if pct >= 0.7 else ("MONITOR" if pct >= 0.5 else "DISCARD")
        return {
            "priority": "High" if pct >= 0.7 else "Medium",
            "sector_label": "Technology / SaaS",
            "mission": product[:100] if product else f"{name} delivers specialised software solutions.",
            "scale": f"~€{arr}M ARR · ~{employees} employees",
            "synergy": sf_rel or fit_sum,
            "moat": "Proprietary data network and sector-specific workflow integrations",
            "company_profile": fit_sum or f"{name} is a {stage} company based in {country}.",
            "acquiror_mission": f"{buyer} is expanding its presence in this sector.",
            "acquiror_scale": f"{buyer} operates at global scale with a broad enterprise customer base.",
            "kpis": [
                {"kpi": "ARR / Revenue", "value": f"~€{arr}M", "status": "🟡 Estimated", "trend": "▲ Growing"},
                {"kpi": "Headcount", "value": f"~{employees}", "status": "🟢 Scaling", "trend": "▲ YoY"},
                {"kpi": "Total Raised", "value": f"~€{raised}M", "status": "🟢 Well-funded", "trend": "▲ Series progression"},
            ],
            "exec_summary": fit_sum or f"Acquisition of {name} offers {buyer} a direct entry into an underserved market segment.",
            "rationale": sf_rel or f"{name} fills a material product gap for {buyer} in {country}.",
            "advisory_view": f"{name} represents a rare, defensible asset in a consolidating market.",
            "recommendation": rec,
            "next_steps": "Initiate NDA and management presentation. Target LOI within 60 days.",
            "deal_type": "Buy-side",
            "estimated_valuation": "Subject to data room",
            "lead_dealmaker": "Managing Director, Technology M&A",
            "strategic_value_score": round(pct * 10, 1),
        }


def _rec_badge(rec: str) -> str:
    cfg = {
        "PROCEED":  ("#2E7D32", "✅ PROCEED — Advance to LOI Stage"),
        "MONITOR":  ("#F57F17", "👁 MONITOR — Track and Reassess in 90 Days"),
        "DISCARD":  ("#C62828", "🚫 DISCARD — Below Acquisition Threshold"),
    }
    color, label = cfg.get(rec, ("#9E9E9E", rec))
    return f'<span class="rec-badge" style="background:{color}">{_h(label)}</span>'


def _priority_badge(priority: str) -> str:
    cfg = {"High": "#C62828", "Medium": "#F57F17", "Low": "#2E7D32"}
    color = cfg.get(priority, "#9E9E9E")
    return (f'<span style="display:inline-block;background:{color};color:#fff;'
            f'font-size:10px;font-weight:800;padding:2px 9px;border-radius:3px;'
            f'letter-spacing:.8px;text-transform:uppercase">{_h(priority)} PRIORITY</span>')


def _sec_company_report(t: Dict, detail: Dict, rank: int, criteria: List[Dict],
                        date_str: str, project_code: str) -> str:
    name      = t.get("name", "")
    country   = t.get("country", "")
    stage     = t.get("funding_stage", "")
    raised    = _fmt_m(t.get("total_raised_usd_m"))
    employees = _fmt_emp(t.get("employees"))
    total     = t.get("total_score", 0)
    max_s     = t.get("max_score", 35)
    scores    = t.get("scores", {})

    priority      = detail.get("priority", "High")
    sector_label  = detail.get("sector_label", "Technology / SaaS")
    mission       = detail.get("mission", "")
    scale         = detail.get("scale", f"~{raised} raised · {employees} employees")
    synergy       = detail.get("synergy", "")
    moat          = detail.get("moat", "")
    company_prof  = detail.get("company_profile", t.get("product_profile", t.get("product_description", "")))
    acq_mission   = detail.get("acquiror_mission", "")
    acq_scale     = detail.get("acquiror_scale", "")
    kpis          = detail.get("kpis", [])
    exec_sum      = detail.get("exec_summary", t.get("strategic_fit_summary", ""))
    rationale     = detail.get("rationale", "")
    advisory_view = detail.get("advisory_view", "")
    rec           = detail.get("recommendation", "PROCEED")
    next_steps    = detail.get("next_steps", "")
    deal_type     = detail.get("deal_type", "Buy-side")
    est_val       = detail.get("estimated_valuation", "Subject to data room")
    lead_dm       = detail.get("lead_dealmaker", "Managing Director, Technology M&A")
    svs           = detail.get("strategic_value_score", round(total / max_s * 10, 1) if max_s else 0)

    # ── Company Snapshot table ───────────────────────────────────────────────
    snapshot_html = f"""
<table class="snapshot-tbl">
  <thead><tr>
    <th style="width:50%">🏢 TARGET PROFILE</th>
    <th style="width:50%">🎯 STRATEGIC RATIONALE</th>
  </tr></thead>
  <tbody>
    <tr>
      <td><strong>Mission:</strong> {_h(mission)}</td>
      <td><strong>Synergy:</strong> {_h(synergy)}</td>
    </tr>
    <tr>
      <td><strong>Scale:</strong> {_h(scale)}</td>
      <td><strong>Moat:</strong> {_h(moat)}</td>
    </tr>
    <tr>
      <td><strong>Stage:</strong> {_h(stage)} · {raised} raised</td>
      <td><strong>Strategic Fit Score:</strong>
        <strong style="color:var(--navy);font-size:15px">{total}</strong>
        <span style="color:var(--muted)">/{max_s}</span> &nbsp;·&nbsp;
        {_rec_badge(rec)}</td>
    </tr>
  </tbody>
</table>"""

    # ── Acquiror profile comparison ──────────────────────────────────────────
    acq_html = f"""
<table class="snapshot-tbl" style="margin-top:10px">
  <thead><tr>
    <th style="width:50%">🏢 TARGET: {_h(name)}</th>
    <th style="width:50%">🤝 ACQUIROR PROFILE</th>
  </tr></thead>
  <tbody>
    <tr>
      <td style="font-size:12.5px;color:#2d3748;line-height:1.6">{_h(company_prof)}</td>
      <td>
        <p style="font-size:12.5px;color:#2d3748;margin-bottom:8px">{_h(acq_mission)}</p>
        <p style="font-size:12.5px;color:#2d3748">{_h(acq_scale)}</p>
      </td>
    </tr>
  </tbody>
</table>"""

    # ── KPI table ────────────────────────────────────────────────────────────
    if kpis:
        kpi_rows = "".join(
            f"<tr><td><strong>{_h(k.get('kpi',''))}</strong></td>"
            f"<td style='font-weight:700'>{_h(k.get('value',''))}</td>"
            f"<td>{_h(k.get('status',''))}</td>"
            f"<td style='color:{'#2E7D32' if '▲' in k.get('trend','') or '✅' in k.get('trend','') else ('#C62828' if '▼' in k.get('trend','') else '#718096')};font-weight:700'>"
            f"{_h(k.get('trend',''))}</td></tr>"
            for k in kpis
        )
        kpi_html = (
            f"<table><thead><tr><th>KPI</th><th>Value</th>"
            f"<th>Status</th><th>Trend</th></tr></thead><tbody>{kpi_rows}</tbody></table>"
        )
    else:
        kpi_html = (
            f"<table><thead><tr><th>KPI</th><th>Value</th></tr></thead><tbody>"
            f"<tr><td><strong>ARR / Revenue</strong></td><td>{_h(str(t.get('arr_usd_m','N/A')))}</td></tr>"
            f"<tr><td><strong>Total Raised</strong></td><td>{raised}</td></tr>"
            f"<tr><td><strong>Headcount</strong></td><td>{employees}</td></tr>"
            f"<tr><td><strong>Funding Stage</strong></td><td>{_h(stage)}</td></tr>"
            f"</tbody></table>"
        )

    # ── Criterion scores ─────────────────────────────────────────────────────
    crit_rows = "".join(
        f"<tr><td><strong>{_h(c['id'])}</strong></td><td>{_h(c['name'])}</td>"
        f"<td style='text-align:center'>{_sc(scores.get(c['id'],{}).get('score',0))}</td>"
        f"<td style='font-size:11px;color:var(--muted)'>{_h(scores.get(c['id'],{}).get('rationale',''))}</td></tr>"
        for c in criteria
    )

    return f"""
<div class="company-report">

  <!-- ── HEADER ── -->
  <div class="cr-header">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:10px">
      <div>
        <div class="cr-rank">#{rank} · Project {_h(project_code)} &nbsp;|&nbsp; Current Status: Final Review &nbsp;|&nbsp; {_h(date_str)}</div>
        <div class="cr-title">🤝 TARGET ANALYSIS: {_h(name)}</div>
      </div>
      <div style="text-align:right">
        {_priority_badge(priority)}
        <div style="font-size:20px;font-weight:800;color:var(--gold);margin-top:6px">{svs}<span style="font-size:13px;color:#8a9ab8">/10</span></div>
        <div style="font-size:10px;color:#8a9ab8;letter-spacing:.5px">STRATEGIC VALUE SCORE</div>
      </div>
    </div>
    <div class="cr-meta" style="margin-top:10px">
      <strong>HQ:</strong> {_h(country)} &nbsp;|&nbsp;
      <strong>Sector:</strong> {_h(sector_label)} &nbsp;|&nbsp;
      <strong>Stage:</strong> {_h(stage)} &nbsp;|&nbsp;
      <strong>Raised:</strong> {raised}
    </div>
  </div>

  <!-- ── 1. COMPANY SNAPSHOT ── -->
  <div class="cr-section">
    <div class="cr-sh">🏗 Company Snapshot</div>
    {snapshot_html}
    {acq_html}
  </div>

  <!-- ── 2. PERFORMANCE METRICS ── -->
  <div class="cr-section">
    <div class="cr-sh">📊 Performance Metrics</div>
    {kpi_html}
    <p style="font-size:11px;color:var(--muted);margin-top:8px;font-style:italic">
      Estimates based on publicly available benchmarks and funding stage comparables. Subject to data room verification.
    </p>
  </div>

  <!-- ── 3. TRANSACTION RATIONALE ── -->
  <div class="cr-section">
    <div class="cr-sh">💡 Transaction Rationale</div>
    <div class="callout-imp">
      <div style="font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.8px;
        color:#F57F17;margin-bottom:6px">⚑ EXECUTIVE SUMMARY</div>
      <p style="font-size:13.5px;font-weight:600;color:#2d3748;line-height:1.6">{_h(exec_sum)}</p>
    </div>
    <p style="font-size:13.5px;color:#2d3748;line-height:1.75;margin-bottom:18px">{_h(rationale)}</p>
    <div class="callout-note2">
      <div style="font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.8px;
        color:var(--navy);margin-bottom:6px">📌 THE ADVISORY VIEW</div>
      <p style="font-size:13px;color:#2d3748;line-height:1.65;font-style:italic">{_h(advisory_view)}</p>
    </div>
    <p style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;
      color:var(--muted);margin:16px 0 8px">Criterion Breakdown — {total}/{max_s} points</p>
    <table style="font-size:12px">
      <thead><tr><th>ID</th><th>Criterion</th><th>Score</th><th>Rationale</th></tr></thead>
      <tbody>{crit_rows}</tbody>
    </table>
  </div>

  <!-- ── 4. CONCLUSION ── -->
  <div class="cr-section">
    <div class="cr-sh">🏁 Conclusion &amp; Next Steps</div>
    <div style="margin-bottom:16px">{_rec_badge(rec)}</div>
    <p style="font-size:13.5px;color:#2d3748;line-height:1.75;margin-bottom:20px">{_h(next_steps)}</p>
    <div class="cr-deal-footer">
      <div class="cr-df-item"><span class="cr-df-label">Type</span><span class="cr-df-val">{_h(deal_type)}</span></div>
      <div class="cr-df-item"><span class="cr-df-label">Lead Dealmaker</span><span class="cr-df-val">{_h(lead_dm)}</span></div>
      <div class="cr-df-item"><span class="cr-df-label">Estimated Valuation</span><span class="cr-df-val">{_h(est_val)}</span></div>
      <div class="cr-df-item"><span class="cr-df-label">Strategic Value Score</span>
        <span class="cr-df-val" style="color:var(--gold);font-size:17px">{svs}/10</span></div>
    </div>
    <p style="font-size:11px;color:var(--muted);margin-top:12px;font-style:italic;text-align:right">
      Confidential | GP Bullhound M&amp;A Advisory — Not for Distribution
    </p>
  </div>

</div>"""


# ──────────────────────────────────────────────────────────────────────────────
# Section builders
# ──────────────────────────────────────────────────────────────────────────────

def _sc(s) -> str:
    v=max(1,min(5,int(s) if str(s).isdigit() else 1))
    return f'<span class="sc sc{v}">{v}</span>'

def _tier(rank,n) -> str:
    if rank<=3: return "t-top"
    if rank<=max(6,n//2): return "t-mid"
    return "t-low"

def _cb(score,name) -> str:
    if score>=4: return f'<span class="cb cb-met">✓ {_h(name)}</span>'
    if score==3: return f'<span class="cb cb-par">~ {_h(name)}</span>'
    return f'<span class="cb cb-no">✗ {_h(name)}</span>'

def _sh(num: str, title: str) -> str:
    return (f'<div class="sh"><span class="sh-num">{_h(num)}</span>'
            f'<span class="sh-title">{_h(title)}</span>'
            f'<span class="sh-rule"></span></div>')


def _modal_html(t: Dict, criteria: List[Dict]) -> str:
    scores = t.get("scores",{})
    rows = "".join(
        f"<tr><td><strong>{_h(c['id'])}</strong></td>"
        f"<td>{_h(c['name'])}</td>"
        f"<td style='text-align:center'>{_sc(scores.get(c['id'],{}).get('score',0))}</td>"
        f"<td style='font-size:12px;color:#4a5568'>{_h(scores.get(c['id'],{}).get('rationale',''))}</td></tr>"
        for c in criteria
    )
    risks = t.get("deal_breaker_risks",[])
    risk_html = " ".join(f'<span class="risk">⚠ {_h(r)}</span>' for r in risks) if risks else '<span style="color:var(--green);font-size:12px">None identified</span>'

    return f"""
<div class="mh">
  <div>
    <div style="font-size:10px;color:var(--gold);font-weight:800;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">
      #{t.get('rank','–')} Ranked · {t.get('total_score',0)}/{t.get('max_score',35)} points
    </div>
    <div style="font-size:19px;font-weight:700">{_h(t.get('name',''))}</div>
    <div style="font-size:11px;color:#aab3c7;margin-top:3px">
      {_h(t.get('country',''))} · {_h(t.get('funding_stage',''))} · Raised: {_fmt_m(t.get('total_raised_usd_m'))} · ~{_fmt_emp(t.get('employees'))} employees
    </div>
  </div>
  <button class="mx" onclick="closeModal()">✕</button>
</div>
<div class="mb">
  <div class="ms"><h4>Product &amp; Market Profile</h4>
    <p>{_h(t.get('product_profile', t.get('product_description','N/A')))}</p></div>
  <div class="ms"><h4>Salesforce Relevance</h4>
    <p>{_h(t.get('salesforce_relevance','N/A'))}</p></div>
  <div class="ms"><h4>Strategic Fit Summary</h4>
    <p>{_h(t.get('strategic_fit_summary',''))}</p></div>
  <div class="ms"><h4>Criterion Scores</h4>
    <table><thead><tr><th>ID</th><th>Criterion</th><th>Score</th><th>Rationale</th></tr></thead>
    <tbody>{rows}</tbody></table></div>
  <div class="ms"><h4>Key Investors &amp; Customers</h4>
    <p><strong>Investors:</strong> {_h(_list_str(t.get('key_investors',[])))}<br>
    <strong>Customers:</strong> {_h(_list_str(t.get('key_customers',[])))}</p></div>
  <div class="ms"><h4>Deal Risks</h4><p>{risk_html}</p></div>
</div>"""


# ── Section 1: Executive Summary ─────────────────────────────────────────────

def sec_exec(bp: Dict, ts: Dict, dcf: Dict) -> str:
    targets = ts.get("targets",[])
    top3    = [t for t in targets if t.get("rank",99)<=3]
    buyer   = _h(bp.get("buyer",""))
    sector  = _h(ts.get("sector",""))
    geo     = _h(ts.get("geography",""))
    n       = len(targets)
    maxs    = targets[0].get("max_score",35) if targets else 35

    top3_names = " &nbsp;·&nbsp; ".join(
        f'<strong style="color:var(--green)">#{t["rank"]} {_h(t["name"])}</strong> ({t["total_score"]}/{maxs})'
        for t in top3
    )

    acq = dcf.get("acquisition_price",0)
    ev  = dcf.get("enterprise_value",0)

    return f"""
<section id="s1">
  {_sh("EXEC SUMMARY", f"Strategic Screening: {buyer} × {sector}")}

  <div class="kpi-row">
    <div class="kpi navy"><div class="kpi-val">{n}</div>
      <div class="kpi-label">Targets Screened</div></div>
    <div class="kpi red"><div class="kpi-val">3</div>
      <div class="kpi-label">Primary Recommendations</div></div>
    <div class="kpi navy"><div class="kpi-val">7</div>
      <div class="kpi-label">Scoring Criteria</div></div>
    <div class="kpi red"><div class="kpi-val">€{acq:,.0f}M</div>
      <div class="kpi-label">Indicative Acq. Price (#1)</div></div>
  </div>

  <div class="callout">
    <strong>Primary Recommendations ({geo}):</strong>&nbsp; {top3_names}
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--border);
    border:1px solid var(--border);margin-top:20px">
    <div style="background:var(--white);padding:20px 22px">
      <p style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
        color:var(--muted);margin-bottom:10px;font-family:'IBM Plex Mono',monospace">Buyer Acquisition Pattern</p>
      <p style="font-size:13px;color:var(--text);line-height:1.65">{_h(bp.get('acquisition_pattern_summary',''))}</p>
    </div>
    <div style="background:var(--white);padding:20px 22px">
      <p style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
        color:var(--muted);margin-bottom:10px;font-family:'IBM Plex Mono',monospace">Product Gaps in Sector</p>
      <ul style="padding-left:16px">
        {"".join(f'<li style="font-size:13px;margin-bottom:5px;color:var(--text)">{_h(g)}</li>' for g in bp.get('current_product_gaps',[])[:3])}
      </ul>
    </div>
  </div>
</section>"""


# ── Section 2: Buyer Profile + Rubric ────────────────────────────────────────

def sec_buyer(bp: Dict) -> str:
    acqs     = bp.get("acquisitions",[])
    prios    = bp.get("strategic_priorities",[])
    criteria = bp.get("scoring_criteria",[])
    buyer    = _h(bp.get("buyer",""))

    acq_rows = "".join(
        f"<tr><td><strong>{_h(a.get('name',''))}</strong></td>"
        f"<td>{_h(str(a.get('year','')))}</td>"
        f"<td>{'€'+str(a.get('deal_size_usd_bn',''))+'B' if a.get('deal_size_usd_bn') else 'Undisclosed'}</td>"
        f"<td style='font-size:12px'>{_h(a.get('capability_gap_filled',''))}</td></tr>"
        for a in acqs
    )
    rub_rows = "".join(
        f"<tr><td><strong>{_h(c.get('id',''))}</strong></td>"
        f"<td><strong>{_h(c.get('name',''))}</strong><br>"
        f"<span class='rj'>{_h(c.get('justification',''))}</span></td>"
        f"<td style='font-size:12px'>{_h(c.get('description',''))}</td></tr>"
        for c in criteria
    )
    prio_items = "".join(f"<li>{_h(p)}</li>" for p in prios[:6])

    return f"""
<section id="s2">
  {_sh("02", f"Buyer Profile &amp; Scoring Rubric — {buyer}")}

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--border);
    border:1px solid var(--border);margin-bottom:24px">
    <div style="background:var(--white);padding:20px 22px">
      <p style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
        color:var(--muted);margin-bottom:12px;font-family:'IBM Plex Mono',monospace">Recent Acquisitions</p>
      <table><thead><tr><th>Company</th><th>Year</th><th>Size</th><th>Capability Acquired</th></tr></thead>
      <tbody>{acq_rows}</tbody></table>
    </div>
    <div style="background:var(--white);padding:20px 22px">
      <p style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
        color:var(--muted);margin-bottom:12px;font-family:'IBM Plex Mono',monospace">Strategic Priorities 2024–2026</p>
      <ul class="prio">{prio_items}</ul>
    </div>
  </div>

  <p style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
    color:var(--muted);margin-bottom:12px;font-family:'IBM Plex Mono',monospace">
    Scoring Rubric — 7 Criteria (C1–C4 buyer-specific · C5–C7 universal M&amp;A)</p>
  <table><thead><tr><th width="40">ID</th><th>Criterion</th><th>What It Measures (1–5)</th></tr></thead>
  <tbody>{rub_rows}</tbody></table>
</section>"""


# ── Section 3: Target Table + Score Chart ─────────────────────────────────────

def sec_targets(ts: Dict, bp: Dict) -> str:
    targets  = ts.get("targets",[])
    criteria = bp.get("scoring_criteria",[])
    cids     = [c["id"] for c in criteria]
    n        = len(targets)

    countries = sorted({t.get("country","") for t in targets if t.get("country")})
    stages    = sorted({t.get("funding_stage","") for t in targets if t.get("funding_stage")})
    co_opts   = "".join(f'<option value="{_h(c)}">{_h(c)}</option>' for c in countries)
    st_opts   = "".join(f'<option value="{_h(s)}">{_h(s)}</option>' for s in stages)

    crit_hd = "".join(
        f'<th data-col="{i+4}" title="{_h(c["name"])}">{_h(c["id"])}<span class="si">⇅</span></th>'
        for i,c in enumerate(criteria)
    )

    rows = ""
    for t in targets:
        rank   = t.get("rank",0)
        tier   = _tier(rank,n)
        scores = t.get("scores",{})
        sc     = "".join(
            f'<td style="text-align:center" data-val="{scores.get(cid,{}).get("score",0)}">'
            f'{_sc(scores.get(cid,{}).get("score",0))}</td>'
            for cid in cids
        )
        total = t.get("total_score",0)
        maxs  = t.get("max_score",35)
        risks = t.get("deal_breaker_risks",[])
        rhtml = " ".join(f'<span class="risk">⚠ {_h(r)}</span>' for r in risks[:2]) if risks else "—"
        md    = _modal_html(t, criteria)
        me    = md.replace("\\","\\\\").replace("`","\\`").replace("${","\\${")
        rows += f"""
        <tr class="{tier} cr" data-country="{_h(t.get('country',''))}"
            data-stage="{_h(t.get('funding_stage',''))}"
            onclick="openModal(`{me}`)">
          <td><strong>#{rank}</strong></td>
          <td><strong>{_h(t.get('name',''))}</strong><br>
              <span style="font-size:11px;color:var(--muted)">{_h(t.get('country',''))}</span></td>
          <td style="font-size:12px">{_h(t.get('funding_stage',''))}<br>
              <span style="color:var(--muted)">{_fmt_m(t.get('total_raised_usd_m'))}</span></td>
          {sc}
          <td style="text-align:center" data-val="{total}">
            <strong style="font-size:14px">{total}</strong>
            <span style="color:var(--muted);font-size:11px">/{maxs}</span>
          </td>
          <td style="font-size:11px">{rhtml}</td>
        </tr>"""

    chart = _svg_scores_chart(targets)
    crit_note = " · ".join(f"{c['id']}: {c['name']}" for c in criteria)

    return f"""
<section id="s3">
  {_sh("03", f"Target Screening — {n} Companies")}

  <div style="background:var(--white);border:1px solid var(--border);
    padding:20px 24px;margin-bottom:24px;text-align:center;overflow-x:auto">
    {chart}
  </div>

  <div class="legend">
    <div class="li"><div class="ld" style="background:var(--green)"></div> Top 3 — Primary</div>
    <div class="li"><div class="ld" style="background:var(--amber)"></div> Mid Tier — Monitor</div>
    <div class="li"><div class="ld" style="background:var(--grey)"></div> Lower Tier</div>
    <span style="font-size:11px;color:var(--muted);font-style:italic">Click any row for full profile →</span>
  </div>
  <div class="fbar">
    <label>Search:</label>
    <input type="text" id="ts" placeholder="Company name..." style="width:170px">
    <label>Country:</label>
    <select id="tc"><option value="">All</option>{co_opts}</select>
    <label>Stage:</label>
    <select id="tst"><option value="">All</option>{st_opts}</select>
  </div>
  <p style="font-size:11px;color:var(--muted);margin-bottom:10px">{_h(crit_note)}</p>
  <div class="tbl-wrap">
  <table id="tgtbl">
    <thead><tr>
      <th data-col="0">Rank<span class="si">⇅</span></th>
      <th data-col="1">Company</th>
      <th data-col="2">Stage</th>
      {crit_hd}
      <th data-col="{len(cids)+3}" style="background:#1a3060">Score<span class="si">⇅</span></th>
      <th>Risks</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
  </div>
</section>"""


# ── Section 4: Top 3 Acquisition Reports ──────────────────────────────────────

def sec_top3(ts: Dict, bp: Dict, company_details: Optional[Dict] = None,
             date_str: str = "") -> str:
    targets  = ts.get("targets",[])
    criteria = ts.get("criteria_detail", bp.get("scoring_criteria",[]))
    top3     = sorted([t for t in targets if t.get("rank",99)<=3], key=lambda x: x.get("rank",99))
    t3names  = [t["name"] for t in top3]
    radar    = _radar_svg(targets, criteria, t3names)

    rl = "".join(
        f'<div class="rl"><div class="rd" style="background:{c}"></div>'
        f'<span><strong>#{t.get("rank")}</strong> {_h(t.get("name",""))}</span></div>'
        for t,c in zip(top3,["#0B1C3D","#C9A84C","#2E7D32"])
    )

    reports = ""
    if company_details is None:
        company_details = {}
    for i, t in enumerate(top3):
        detail = company_details.get(t["name"], {})
        code   = PROJECT_NAMES[i] if i < len(PROJECT_NAMES) else f"Project {i+1}"
        reports += _sec_company_report(t, detail, t.get("rank",i+1), criteria, date_str, code)

    return f"""
<section id="s4">
  {_sh("04", "Top 3 Acquisition Reports")}

  <div class="radar-wrap" style="margin-bottom:36px">
    <div style="background:var(--white);border:1px solid var(--border);padding:18px">{radar}</div>
    <div>
      <p style="font-size:12px;font-weight:700;color:var(--navy);margin-bottom:10px;
        text-transform:uppercase;letter-spacing:.5px">Comparative Radar — 7 Criteria</p>
      <div class="radar-leg">{rl}</div>
      <p style="font-size:11px;color:var(--muted);margin-top:12px">Outer edge = score of 5/5</p>
    </div>
  </div>
  {reports}
</section>"""


# ── Section 5: DCF Valuation ─────────────────────────────────────────────────

def sec_dcf(dcf: Dict, commentary: str) -> str:
    a     = dcf["assumptions"]
    tname = _h(dcf["target_name"])
    yrws  = "".join(
        f"<tr class='dcf-yr'>"
        f"<td><strong>{_h(y['year'])}</strong></td>"
        f"<td>€{y['revenue']:.0f}M</td><td>€{y['ebitda']:.0f}M</td>"
        f"<td>€{y['fcf']:.0f}M</td><td>{y['discount_factor']:.3f}</td>"
        f"<td><strong>€{y['pv_fcf']:.0f}M</strong></td></tr>"
        for y in dcf["years"]
    )
    bars_svg   = _svg_dcf_bars(dcf)
    bridge_svg = _svg_ev_bridge(dcf)

    return f"""
<section id="s5">
  {_sh("05", f"DCF Valuation — {tname} (#1 Target)")}

  <div class="callout" style="margin-bottom:16px">
    <strong>Illustrative analysis</strong> based on publicly available benchmarks.
    All figures in EUR millions. Adjust assumptions below and export to CSV.
  </div>
  {commentary}

  <div class="chart-pair" style="margin-bottom:22px">
    <div class="chart-box">{bars_svg}</div>
    <div class="chart-box">{bridge_svg}</div>
  </div>

  <div class="dcf-layout">
    <div class="asm-panel">
      <h4>⚙ Assumptions</h4>
      <div class="asm-r"><span class="asm-l">Base Revenue (€M)</span>
        <input class="asm-i" id="dcf-br" type="number" value="{a['base_revenue_eur_m']}" onchange="recalcDCF()"></div>
      <div class="asm-r"><span class="asm-l">EBITDA Margin (%)</span>
        <input class="asm-i" id="dcf-em" type="number" value="{a['ebitda_margin_pct']}" onchange="recalcDCF()"></div>
      <div class="asm-r"><span class="asm-l">FCF / EBITDA (%)</span>
        <input class="asm-i" id="dcf-fc" type="number" value="{a['fcf_pct_ebitda']}" onchange="recalcDCF()"></div>
      <div class="asm-r"><span class="asm-l">WACC (%)</span>
        <input class="asm-i" id="dcf-wc" type="number" step="0.1" value="{a['wacc_pct']}" onchange="recalcDCF()"></div>
      <div class="asm-r"><span class="asm-l">Terminal Growth (%)</span>
        <input class="asm-i" id="dcf-tg" type="number" step="0.1" value="{a['terminal_growth_pct']}" onchange="recalcDCF()"></div>
      <div class="asm-r"><span class="asm-l">Synergy Premium (%)</span>
        <input class="asm-i" id="dcf-sp" type="number" value="{a['synergy_premium_pct']}" onchange="recalcDCF()"></div>
      <div style="margin-top:14px;display:flex;gap:8px">
        <button class="btn btn-nv" onclick="recalcDCF()">Recalculate</button>
        <button class="btn btn-rd" onclick="dlCSV()">↓ Export CSV</button>
      </div>
    </div>
    <div class="tbl-wrap">
      <table>
        <thead><tr><th>Year</th><th>Revenue</th><th>EBITDA</th><th>FCF</th><th>Disc. Factor</th><th>PV of FCF</th></tr></thead>
        <tbody>
          {yrws}
          <tr style="background:#f8fafc"><td colspan="5" style="text-align:right;font-weight:700;color:var(--navy)">Sum of PV (FCFs)</td>
            <td><strong id="d-spv">€{dcf['sum_pv_fcf']:.0f}M</strong></td></tr>
          <tr style="background:#f8fafc"><td colspan="5" style="text-align:right;font-weight:700;color:var(--navy)">Terminal Value</td>
            <td><strong id="d-tv">€{dcf['terminal_value']:.0f}M</strong></td></tr>
          <tr style="background:#f8fafc"><td colspan="5" style="text-align:right;font-weight:700;color:var(--navy)">PV of Terminal Value</td>
            <td><strong id="d-ptv">€{dcf['pv_terminal_value']:.0f}M</strong></td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <div class="dcf-kpis">
    <div class="dk"><div class="dk-val">€<span id="d-ev">{dcf['enterprise_value']:.0f}</span>M</div>
      <div class="dk-lbl">Enterprise Value (DCF)</div></div>
    <div class="dk"><div class="dk-val">€<span id="d-syn">{dcf['synergy_value']:.0f}</span>M</div>
      <div class="dk-lbl">Synergy Value ({a['synergy_premium_pct']:.0f}% premium)</div></div>
    <div class="dk hl"><div class="dk-val">€<span id="d-acq">{dcf['acquisition_price']:.0f}</span>M</div>
      <div class="dk-lbl">Indicative Acquisition Price</div></div>
    <div class="dk"><div class="dk-val"><span id="d-mult">{dcf['ev_revenue_multiple']:.1f}</span>x</div>
      <div class="dk-lbl">EV / Base Revenue</div></div>
  </div>
  <p class="dcf-note">Growth assumptions: {', '.join(str(int(y['growth_pct']))+'%' for y in dcf['years'])}.
    WACC reflects blended cost of capital for comparable sector assets.
    Synergy premium reflects value of acquirer's distribution network.</p>
</section>"""


# ── Section 6: Client Summary ─────────────────────────────────────────────────

def sec_client(ts: Dict, bp: Dict) -> str:
    targets  = ts.get("targets",[])
    criteria = bp.get("scoring_criteria",[])

    cards = ""
    for t in targets:
        rank   = t.get("rank",0)
        scores = t.get("scores",{})
        badges = "".join(_cb(scores.get(c["id"],{}).get("score",0), c["name"]) for c in criteria)
        desc   = t.get("product_profile", t.get("product_description","")) or ""
        if len(desc)>150: desc = desc[:148]+"…"
        total  = t.get("total_score",0)
        maxs   = t.get("max_score",35)
        bc     = "#015D52" if rank<=3 else ("#CC0605" if rank<=6 else "#9ca3af")
        cards += f"""
    <div class="csc">
      <div class="csc-top" style="border-left:4px solid {bc}">
        <div class="csc-rank">#{rank}</div>
        <div class="csc-row">
          <div><div class="csc-name">{_h(t.get('name',''))}</div>
            <div class="csc-sub">{_h(t.get('country',''))} · {_h(t.get('funding_stage',''))}</div></div>
          <div class="csc-score">{total}/{maxs}</div>
        </div>
      </div>
      <div class="csc-body">
        <p class="csc-desc">{_h(desc)}</p>
        <div class="csc-badges">{badges}</div>
      </div>
    </div>"""

    return f"""
<section id="s6">
  {_sh("06", "Target Summary — At a Glance")}
  <p style="font-size:11px;color:var(--muted);margin-bottom:20px;letter-spacing:.3px">
    ✓ Strong fit (4–5) &nbsp;·&nbsp; ~ Partial fit (3) &nbsp;·&nbsp; ✗ Weak fit (1–2)
  </p>
  <div class="cs-grid">{cards}</div>
</section>"""


# ──────────────────────────────────────────────────────────────────────────────
# Full HTML
# ──────────────────────────────────────────────────────────────────────────────

def build_html(bp: Dict, ts: Dict, dcf: Dict, dcf_commentary: str,
               company_details: Optional[Dict] = None) -> str:
    buyer  = _h(bp.get("buyer",""))
    sector = _h(ts.get("sector",""))
    geo    = _h(ts.get("geography",""))
    now    = datetime.now().strftime("%d %B %Y")

    s1 = sec_exec(bp, ts, dcf)
    s2 = sec_buyer(bp)
    s3 = sec_targets(ts, bp)
    s4 = sec_top3(ts, bp, company_details=company_details, date_str=now)
    s5 = sec_dcf(dcf, dcf_commentary)
    s6 = sec_client(ts, bp)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>M&A Target Screening — {buyer} | GP Bullhound</title>
  <style>{CSS}</style>
</head>
<body>

<div class="cover-bar"></div>

<header>
  <div class="logo-wrap">
    {BULL_LOGO}
    <div class="logo-wordmark">GP Bull<span>hound</span></div>
  </div>
  <div class="header-right">
    <div class="doc-title">M&amp;A Target Screening — {buyer}</div>
    <div class="doc-meta">{sector} &nbsp;·&nbsp; {geo}</div>
    <div class="doc-meta">{now}</div>
    <div><span class="confidential">Confidential &mdash; Not for Distribution</span></div>
  </div>
</header>

<nav>
  <a href="#s1">Executive Summary</a>
  <a href="#s2">Buyer Profile</a>
  <a href="#s3">Target Screening</a>
  <a href="#s4">Acquisition Reports</a>
  <a href="#s5">DCF Valuation</a>
  <a href="#s6">Summary</a>
</nav>

<div id="mo"><div class="modal"><div id="mc"></div></div></div>

<div class="page">
  {s1}{s2}{s3}{s4}{s5}{s6}
</div>

<footer>
  <strong>GP Bullhound</strong> &nbsp;&mdash;&nbsp; Technology Investment Banking &nbsp;&mdash;&nbsp;
  {now} &nbsp;&mdash;&nbsp; Strictly Confidential &nbsp;&mdash;&nbsp; Not for Distribution
</footer>

<script>{JS}</script>
</body>
</html>"""


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

def generate_dcf_commentary(client, dcf: Dict) -> str:
    name = dcf["target_name"]
    ev   = dcf["enterprise_value"]
    acq  = dcf["acquisition_price"]
    raw  = _with_retry(lambda: _call_claude(client,
        f"In 2 sentences, explain why a ~€{ev:.0f}M enterprise value and ~€{acq:.0f}M acquisition price "
        f"(including 20% synergy premium) is reasonable for {name}, a leading European healthcare IT company, "
        f"from Salesforce's perspective. Cite specific value drivers. Output plain HTML using only <p> tags.",
        max_tokens=200))
    return re.sub(r"```(?:html)?\s*","",raw).replace("```","").strip()


def save(html: str, path: Optional[Path] = None) -> str:
    if path is None: path = OUTPUT_DIR / "report.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path,"w",encoding="utf-8") as f: f.write(html)
    print(f"  [Saved] {path}")
    return str(path)


def run(bp: Optional[Dict]=None, ts: Optional[Dict]=None) -> str:
    if bp is None:
        with open(DATA_DIR/"buyer_profile.json",encoding="utf-8") as f: bp=json.load(f)
    if ts is None:
        with open(DATA_DIR/"targets_scored.json",encoding="utf-8") as f: ts=json.load(f)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key: raise RuntimeError("ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=api_key)

    print("  Calculating DCF...")
    dcf = calculate_dcf(ts["targets"][0] if ts.get("targets") else {})

    print("  Generating DCF commentary...")
    commentary = _with_retry(lambda: generate_dcf_commentary(client, dcf))

    targets  = ts.get("targets", [])
    criteria = ts.get("criteria_detail", bp.get("scoring_criteria", []))
    buyer_n  = bp.get("buyer", "Strategic Buyer")
    top3     = sorted([t for t in targets if t.get("rank", 99) <= 3], key=lambda x: x.get("rank", 99))

    company_details: Dict = {}
    for i, t in enumerate(top3, 1):
        print(f"  Generating acquisition brief {i}/3 — {t.get('name','?')}...")
        company_details[t["name"]] = _with_retry(
            lambda tgt=t: generate_company_detail(client, buyer_n, tgt, criteria)
        )

    print("  Building report...")
    html = build_html(bp, ts, dcf, commentary, company_details=company_details)
    return save(html)


if __name__ == "__main__":
    print("\n[Step 4] GP Bullhound Report Generation")
    print(run())
