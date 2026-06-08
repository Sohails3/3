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
try:
    from . import companies_house as ch_api  # package import (via app.py)
except ImportError:
    import companies_house as ch_api          # standalone run

load_dotenv(Path(__file__).parent.parent / ".env")

DATA_DIR   = Path(__file__).parent / "data"
OUTPUT_DIR = Path(__file__).parent / "output"
MODEL      = "claude-sonnet-4-6"


# ──────────────────────────────────────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────────────────────────────────────

def _h(v) -> str:
    return (str(v).replace("&","&amp;").replace("<","&lt;")
            .replace(">","&gt;").replace('"',"&quot;"))


def _src_note(sources: List[str], live: bool = False) -> str:
    """Render a compact source footnote row at the bottom of a section."""
    pills = ""
    for s in sources:
        if s.startswith("~"):
            # Live/verified source — green pill
            label = s[1:]
            pills += (
                f'<span style="display:inline-block;background:#e6f4ea;border:1px solid #a8d5b5;'
                f'color:#1b5e20;font-size:10px;font-weight:600;padding:2px 9px;border-radius:3px;'
                f'margin-right:5px;white-space:nowrap">✓ {label}</span>'
            )
        else:
            pills += (
                f'<span style="display:inline-block;background:#f1f3f8;border:1px solid #d0d5e8;'
                f'color:#4a5568;font-size:10px;font-weight:500;padding:2px 9px;border-radius:3px;'
                f'margin-right:5px;white-space:nowrap">{s}</span>'
            )
    caveat = ""
    if live:
        caveat = ('<span style="color:#1b5e20;font-size:10px;font-style:italic;margin-left:6px">'
                  '✓ includes live API data</span>')
    ai_note = ('<span style="color:#9ca3af;font-size:10px;font-style:italic;margin-left:6px">'
               'AI-synthesised from Claude training data (cutoff early 2025) unless marked ✓'
               '</span>') if not live else ""
    return (
        f'<div style="margin-top:18px;padding:10px 14px;background:#f8fafc;'
        f'border:1px solid #e2e8f0;border-radius:4px;display:flex;align-items:center;'
        f'flex-wrap:wrap;gap:4px">'
        f'<span style="font-size:10px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:.6px;color:#718096;margin-right:8px;white-space:nowrap">Sources</span>'
        f'{pills}{caveat}{ai_note}</div>'
    )

def _fmt_m(v, estimated: bool = False) -> str:
    if v in (None,"Not publicly available","N/A"): return "N/A"
    try:
        label = f"€{float(v):.0f}M"
        if estimated:
            label += " <span style='font-size:10px;color:#9ca3af;font-weight:400'>(est.)</span>"
        return label
    except: return str(v)

def _fmt_emp(v) -> str:
    if v in (None,"Not publicly available"): return "N/A"
    try: return f"{int(v):,}"
    except: return str(v)

# Verification badge — reflects the Bigdata.com cross-check from Step 2.5.
_VERIF_STYLE = {
    "verified":   ("#0f7b3f", "✓ Verified"),
    "partial":    ("#9a7b00", "◑ Partial"),
    "unverified": ("#9a3b00", "⚠ Unverified"),
    "not_found":  ("#9a0000", "✕ Not found"),
}
def _verif_badge(t) -> str:
    v = t.get("verification") or {}
    flag = v.get("flag")
    if not flag or flag == "skipped":
        return ""  # verification not run — render nothing
    color, label = _VERIF_STYLE.get(flag, ("#555", flag))
    src = v.get("source")
    if src and flag in ("verified", "partial"):
        label = f"{label} · {_h(src)}"  # e.g. "✓ Verified · Exa"
    notes = _h(v.get("notes", "")) if v.get("notes") else ""
    title = f' title="{notes}"' if notes else ""
    return (f'<span{title} style="display:inline-block;margin-top:6px;font-size:10px;'
            f'font-weight:700;letter-spacing:.04em;padding:3px 9px;border-radius:3px;'
            f'color:#fff;background:{color}">{label}</span>')

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

BULL_LOGO = ""

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

/* ── Floating action buttons ── */
.fab-group{position:fixed;bottom:28px;right:28px;z-index:9999;
  display:flex;flex-direction:column;gap:10px;align-items:flex-end}
.pdf-btn,.pptx-btn{border:none;border-radius:6px;
  padding:12px 20px;font-size:13px;font-weight:700;letter-spacing:.3px;
  cursor:pointer;box-shadow:0 4px 16px rgba(0,0,0,.35);
  display:flex;align-items:center;gap:8px;transition:background .2s,transform .2s;
  text-decoration:none}
.pdf-btn{background:var(--red);color:#fff}
.pdf-btn:hover{background:#a80504;transform:translateY(-2px)}
.pptx-btn{background:var(--navy);color:#fff}
.pptx-btn:hover{background:#1a1f42;transform:translateY(-2px)}
.pdf-btn svg,.pptx-btn svg{width:16px;height:16px;fill:#fff}

/* ── Print styles ── */
@media print{
  .fab-group,.cover-bar,nav,#mo{display:none!important}
  header{padding:16px 32px}
  .page{padding:0 32px}
  section{page-break-inside:avoid}
  .fbar,.modal{display:none!important}
  body{background:#fff!important;color:#000!important}
  footer{color:#666!important}
}
"""

# ──────────────────────────────────────────────────────────────────────────────
# JavaScript
# ──────────────────────────────────────────────────────────────────────────────

JS = """
// PDF download
function downloadPDF(){
  const btn=document.querySelector('.pdf-btn');
  if(btn)btn.style.display='none';
  window.print();
  setTimeout(()=>{if(btn)btn.style.display='flex';},500);
}

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
    def _crit_rationale(raw: str) -> str:
        """Strip the 'Score (X/5) — Reason: ' prefix if the model included it, returning just the reason."""
        import re as _re
        cleaned = _re.sub(r'^Score\s*\(\d/5\)\s*[-—]+\s*Reason:\s*', '', raw, flags=_re.IGNORECASE).strip()
        return cleaned or raw

    crit_rows = "".join(
        "<tr>"
        f"<td style='white-space:nowrap'><strong>{_h(c['id'])}</strong></td>"
        f"<td style='white-space:nowrap'>{_h(c['name'])}</td>"
        f"<td style='text-align:center;white-space:nowrap'>{_sc(scores.get(c['id'],{}).get('score',0))}</td>"
        f"<td style='font-size:11px;color:var(--text)'>"
        f"<span style='font-weight:600;color:var(--navy)'>Score ({scores.get(c['id'],{}).get('score','?')}/5)</span>"
        f" &mdash; <span style='color:var(--muted)'>Reason:</span> "
        f"{_h(_crit_rationale(scores.get(c['id'],{}).get('rationale','')))}"
        f"</td></tr>"
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
      <strong>Raised:</strong> {raised} &nbsp;|&nbsp;
      <strong>Employees:</strong> {employees}
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
      Confidential — Not for Distribution
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


def _strip_score_prefix(raw: str) -> str:
    import re as _re
    # Handle: "Score (4/5) — Reason: text", "Score (4/5) - Reason: text",
    # and post-ascii-clean "Score (4/5) Reason: text" (dash stripped by _ascii_clean)
    cleaned = _re.sub(r'^Score\s*\(\d/5\)\s*[-\u2014]*\s*Reason:\s*', '', raw, flags=_re.IGNORECASE).strip()
    return cleaned if cleaned != raw else raw


def _modal_html(t: Dict, criteria: List[Dict]) -> str:
    scores = t.get("scores",{})
    rows = "".join(
        "<tr>"
        f"<td style='white-space:nowrap'><strong>{_h(c['id'])}</strong></td>"
        f"<td style='white-space:nowrap'>{_h(c['name'])}</td>"
        f"<td style='text-align:center;white-space:nowrap'>{_sc(scores.get(c['id'],{}).get('score',0))}</td>"
        f"<td style='font-size:11px;color:var(--text)'>"
        f"<span style='font-weight:600;color:var(--navy)'>Score ({scores.get(c['id'],{}).get('score','?')}/5)</span>"
        f" &mdash; <span style='color:var(--muted)'>Reason:</span> "
        f"{_h(_strip_score_prefix(scores.get(c['id'],{}).get('rationale','')))}"
        f"</td></tr>"
        for c in criteria
    )
    risks = t.get("deal_breaker_risks",[])
    risk_html = " ".join(f'<span class="risk">⚠ {_h(r)}</span>' for r in risks) if risks else '<span style="color:var(--green);font-size:12px">None identified</span>'

    # Banker cheat-sheet extras (sell-side fields; render only when present)
    _own = t.get("ownership", "")
    meta_extra = ""
    if _own and str(_own).lower() not in ("not publicly available", "n/a", "none", ""):
        meta_extra += f" &middot; Owner: {_h(_own)}"
    _mc, _cash = t.get("market_cap_usd_m"), t.get("cash_usd_m")
    if isinstance(_mc, (int, float)) and not isinstance(_mc, bool):
        meta_extra += f" &middot; Mkt cap: {_fmt_m(_mc)}"
    if isinstance(_cash, (int, float)) and not isinstance(_cash, bool):
        meta_extra += f" &middot; Cash: {_fmt_m(_cash)}"
    _rma = [x for x in (t.get("relevant_ma") or [])
            if x and str(x).strip().lower() not in ("not publicly available", "n/a", "none", "")]
    relevant_ma_html = ""
    if _rma:
        _items = "".join(f"<li>{_h(x)}</li>" for x in _rma)
        relevant_ma_html = ('<div class="ms"><h4>Recent M&amp;A</h4>'
                            '<ul style="margin:0;padding-left:18px;font-size:12px;color:#4a5568;line-height:1.6">'
                            f'{_items}</ul></div>')

    return f"""
<div class="mh">
  <div>
    <div style="font-size:10px;color:var(--gold);font-weight:800;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">
      #{t.get('rank','–')} Ranked · {t.get('total_score',0)}/{t.get('max_score',35)} points
    </div>
    <div style="font-size:19px;font-weight:700">{_h(t.get('name',''))}</div>
    <div style="font-size:11px;color:#aab3c7;margin-top:3px">
      {_h(t.get('country',''))} · {_h(t.get('funding_stage',''))} · Raised: {_fmt_m(t.get('total_raised_usd_m'))} · ~{_fmt_emp(t.get('employees'))} employees{meta_extra}
    </div>
    {_verif_badge(t)}
  </div>
  <button class="mx" onclick="closeModal()">✕</button>
</div>
<div class="mb">
  <div class="ms"><h4>Product &amp; Market Profile</h4>
    <p>{_h(t.get('product_profile', t.get('product_description','N/A')))}</p></div>
  <div class="ms"><h4>Strategic Relevance</h4>
    <p>{_h(t.get('buyer_relevance', t.get('salesforce_relevance','N/A')))}</p></div>
  <div class="ms"><h4>Strategic Fit Summary</h4>
    <p>{_h(t.get('strategic_fit_summary',''))}</p></div>
  <div class="ms"><h4>Criterion Scores</h4>
    <table><thead><tr><th>ID</th><th>Criterion</th><th>Score</th><th>Rationale</th></tr></thead>
    <tbody>{rows}</tbody></table></div>
  <div class="ms"><h4>Key Investors &amp; Customers</h4>
    <p><strong>Investors:</strong> {_h(_list_str(t.get('key_investors',[])))}<br>
    <strong>Customers:</strong> {_h(_list_str(t.get('key_customers',[])))}</p></div>
  {relevant_ma_html}
  <div class="ms"><h4>Deal Risks</h4><p>{risk_html}</p></div>
</div>"""


# ── Section 1: Executive Summary ─────────────────────────────────────────────

def sec_exec(bp: Dict, ts: Dict, dcf: Optional[Dict] = None) -> str:
    targets   = ts.get("targets",[])
    top3      = sorted([t for t in targets if t.get("rank",99)<=3], key=lambda x: x.get("rank",99))
    buyer     = _h(bp.get("buyer",""))
    sector    = _h(ts.get("sector",""))
    geo       = _h(ts.get("geography",""))
    n         = len(targets)
    maxs      = targets[0].get("max_score",35) if targets else 35
    is_sell   = (ts.get("mode") == "sell")
    top3_lbl  = "Top 3 Recommended Acquirers" if is_sell else "Top 3 Recommended Targets"
    sh_title  = f"Exit Strategy: {buyer} · {sector}"  if is_sell else f"Strategic Screening: {buyer} \xd7 {sector}"
    kpi1_lbl  = "Acquirers Screened"  if is_sell else "Targets Screened"
    kpi2_lbl  = "Primary Acquirers"   if is_sell else "Primary Recommendations"
    kpi4_lbl  = "Acquirer Geography"  if is_sell else "Target Geography"

    # Build inline top 3 cards
    top3_cards_html = ""
    for t in top3:
        t_name   = _h(t.get("name", ""))
        t_country= _h(t.get("country", ""))
        t_stage  = _h(t.get("funding_stage", ""))
        t_total  = t.get("total_score", 0)
        t_maxs   = t.get("max_score", maxs)
        t_fit    = _h(t.get("strategic_fit_summary", t.get("product_profile", "")))
        t_arr    = _fmt_m(t.get("arr_usd_m"), t.get("arr_estimated", False))
        t_raised = _fmt_m(t.get("total_raised_usd_m"))
        t_emp    = _fmt_emp(t.get("employees"))
        t_rank   = t.get("rank", "")
        top3_cards_html += f"""
      <div style="flex:1;background:#fff;border:1.5px solid #2E7D32;border-radius:6px;
        padding:16px 18px;border-top:4px solid #2E7D32;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
          <div>
            <span style="font-size:9px;font-weight:700;color:#2E7D32;text-transform:uppercase;
              letter-spacing:.5px">#{t_rank} Recommendation</span>
            <div style="font-size:15px;font-weight:700;color:var(--navy);margin-top:2px">{t_name}</div>
            <div style="font-size:11px;color:var(--muted)">{t_country} · {t_stage}</div>
          </div>
          <div style="text-align:right">
            <div style="font-size:22px;font-weight:700;color:#2E7D32">{t_total}</div>
            <div style="font-size:9px;color:var(--muted)">out of {t_maxs}</div>
          </div>
        </div>
        <p style="font-size:11.5px;color:#374151;line-height:1.6;margin-bottom:10px">{t_fit}</p>
        <div style="display:flex;gap:16px;font-size:10.5px;color:var(--muted);
          padding-top:8px;border-top:1px solid var(--border)">
          <span>ARR: <strong style="color:var(--navy)">{t_arr}</strong></span>
          <span>Raised: <strong style="color:var(--navy)">{t_raised}</strong></span>
          <span>Employees: <strong style="color:var(--navy)">{t_emp}</strong></span>
        </div>
      </div>"""

    top3_inline = f"""
  <div style="margin-top:20px;margin-bottom:20px">
    <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
      color:var(--muted);margin-bottom:12px;font-family:'IBM Plex Mono',monospace">{top3_lbl}</div>
    <div style="display:flex;gap:16px">{top3_cards_html}</div>
  </div>""" if top3_cards_html else ""

    return f"""
<section id="s1">
  {_sh("EXEC SUMMARY", sh_title)}

  <div class="kpi-row">
    <div class="kpi navy"><div class="kpi-val">{n}</div>
      <div class="kpi-label">{kpi1_lbl}</div></div>
    <div class="kpi red"><div class="kpi-val">3</div>
      <div class="kpi-label">{kpi2_lbl}</div></div>
    <div class="kpi navy"><div class="kpi-val">8</div>
      <div class="kpi-label">Scoring Criteria</div></div>
    <div class="kpi red"><div class="kpi-val">{geo}</div>
      <div class="kpi-label">{kpi4_lbl}</div></div>
  </div>

  {top3_inline}

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--border);
    border:1px solid var(--border);margin-top:20px">
    <div style="background:var(--white);padding:20px 22px">
      <p style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
        color:var(--muted);margin-bottom:10px;font-family:'IBM Plex Mono',monospace">Competitive Urgency</p>
      <p style="font-size:13px;color:var(--text);line-height:1.65">{_h(bp.get('competitive_urgency_summary', bp.get('acquisition_pattern_summary','')))}</p>
    </div>
    <div style="background:var(--white);padding:20px 22px">
      <p style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
        color:var(--muted);margin-bottom:10px;font-family:'IBM Plex Mono',monospace">Strategic Gaps Exposed</p>
      <ul style="padding-left:16px">
        {"".join(f'<li style="font-size:13px;margin-bottom:5px;color:var(--text)">{_h(g)}</li>' for g in bp.get('strategic_gaps', bp.get('current_product_gaps',[]))[:4])}
      </ul>
    </div>
  </div>
  {_src_note(["Earnings calls & investor days", "SEC / regulatory filings", "Press releases & analyst reports"])}
</section>"""


# ── Sell-side valuation blocks (injected into sec_buyer for sell mode) ────────

def _sell_side_valuation_blocks(bp: Dict) -> str:
    """Render comp table, valuation bridge, revenue quality and seller story cards."""

    # ── 1. Comparable transactions ───────────────────────────────────────────
    comps = bp.get("valuation_comps", [])
    if comps:
        comp_rows = "".join(
            f"<tr>"
            f"<td><strong>{_h(c.get('target',''))}</strong></td>"
            f"<td>{_h(c.get('acquirer',''))}</td>"
            f"<td>{_h(str(c.get('year','')))}</td>"
            f"<td style='text-align:right'>{'${:,.0f}M'.format(float(c['ev_usd_m'])) if c.get('ev_usd_m') else 'N/A'}</td>"
            f"<td style='text-align:right;font-weight:700;color:var(--navy)'>{'{}x'.format(c['arr_multiple']) if c.get('arr_multiple') else 'N/A'}</td>"
            f"<td style='font-size:11px;color:var(--muted)'>{_h(c.get('rationale',''))}</td>"
            f"</tr>"
            for c in comps
        )
    else:
        comp_rows = "<tr><td colspan='6' style='color:var(--muted)'>No comparable transactions available</td></tr>"

    comp_table = f"""
<div style="margin-top:24px;margin-bottom:2px">
  <div class="tbl-wrap" style="border:1px solid var(--border);border-top:3px solid var(--navy)">
  <table style="margin-bottom:0">
    <thead><tr>
      <th colspan="6" style="text-align:left;background:var(--white);color:var(--navy);
        font-size:10px;letter-spacing:.8px;text-transform:uppercase;padding:12px 14px;
        font-family:'IBM Plex Mono',monospace;font-weight:700">
        Comparable Transaction Analysis — Precedent Exits in Sector</th>
    </tr>
    <tr>
      <th>Target</th><th>Acquirer</th><th>Year</th>
      <th style="text-align:right">EV (USD)</th>
      <th style="text-align:right">ARR Multiple</th>
      <th>Relevance</th>
    </tr></thead>
    <tbody>{comp_rows}</tbody>
  </table>
  </div>
</div>"""

    # ── 2. Valuation bridge ──────────────────────────────────────────────────
    vr   = bp.get("valuation_range", {})
    floor_m = vr.get("floor_arr_multiple", 5)
    ceil_m  = vr.get("ceiling_arr_multiple", 10)
    prem    = vr.get("strategic_premium_pct", 25)
    vr_rat  = _h(vr.get("rationale", ""))

    # Try to extract ARR from dry_powder string for a rough EV estimate
    arr_hint = bp.get("dry_powder", "")

    bridge_html = f"""
<div style="margin-top:2px;margin-bottom:2px">
  <div style="border:1px solid var(--border);border-top:3px solid var(--opal)">
    <div style="padding:12px 14px;background:var(--white);border-bottom:1px solid var(--border)">
      <p style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
        color:var(--opal);font-family:'IBM Plex Mono',monospace;margin:0">
        Valuation Bridge — ARR Floor to Strategic Premium</p>
    </div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:0;background:var(--border)">
      <div style="background:var(--white);padding:18px 20px;border-right:1px solid var(--border)">
        <div style="font-size:10px;font-weight:700;color:var(--muted);text-transform:uppercase;
          letter-spacing:.6px;margin-bottom:6px">Floor Multiple</div>
        <div style="font-size:26px;font-weight:800;color:var(--navy);line-height:1">{floor_m}x ARR</div>
        <div style="font-size:11px;color:var(--muted);margin-top:4px">Financial sponsor floor</div>
      </div>
      <div style="background:var(--white);padding:18px 20px;border-right:1px solid var(--border)">
        <div style="font-size:10px;font-weight:700;color:var(--muted);text-transform:uppercase;
          letter-spacing:.6px;margin-bottom:6px">Ceiling Multiple</div>
        <div style="font-size:26px;font-weight:800;color:var(--navy);line-height:1">{ceil_m}x ARR</div>
        <div style="font-size:11px;color:var(--muted);margin-top:4px">Competitive auction ceiling</div>
      </div>
      <div style="background:#f0fdf4;padding:18px 20px">
        <div style="font-size:10px;font-weight:700;color:var(--green);text-transform:uppercase;
          letter-spacing:.6px;margin-bottom:6px">Strategic Premium</div>
        <div style="font-size:26px;font-weight:800;color:var(--green);line-height:1">+{prem}%</div>
        <div style="font-size:11px;color:var(--muted);margin-top:4px">Above fair value for Tier 1</div>
      </div>
    </div>
    {f'<div style="padding:12px 16px;background:var(--white);border-top:1px solid var(--border);font-size:12px;color:var(--text)">{vr_rat}</div>' if vr_rat else ""}
  </div>
</div>"""

    # ── 3. Revenue quality scorecard ─────────────────────────────────────────
    rq = bp.get("revenue_quality", {})
    def _rq_signal(label: str, value: str, good_value: Optional[str] = None) -> str:
        val_h = _h(value)
        if value in ("Not Available", "Not available", ""):
            color = "#9ca3af"
            icon  = "—"
        elif good_value and value.lower() in good_value.lower():
            color = "#2E7D32"
            icon  = "✓"
        else:
            color = "#2d3748"
            icon  = "·"
        return (
            f'<div style="display:flex;justify-content:space-between;align-items:center;'
            f'padding:10px 14px;border-bottom:1px solid var(--border)">'
            f'<span style="font-size:12px;font-weight:600;color:var(--navy)">{_h(label)}</span>'
            f'<span style="font-size:12px;color:{color};font-weight:600">'
            f'<span style="margin-right:5px">{icon}</span>{val_h}</span>'
            f'</div>'
        )

    rq_html = f"""
<div style="margin-top:2px;margin-bottom:24px">
  <div style="border:1px solid var(--border);border-top:3px solid var(--amber)">
    <div style="padding:12px 14px;background:var(--white);border-bottom:1px solid var(--border)">
      <p style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
        color:#92400e;font-family:'IBM Plex Mono',monospace;margin:0">
        Revenue Quality Scorecard — Buyers Pay Premiums for High NRR</p>
    </div>
    <div style="background:var(--white)">
      {_rq_signal("Net Revenue Retention (NRR)", rq.get("nrr_pct","Not Available"), ">110")}
      {_rq_signal("ARR vs Services Mix", rq.get("arr_services_mix","Not Available"))}
      {_rq_signal("Customer Concentration", rq.get("customer_concentration","Not Available"), "<10%")}
      {_rq_signal("Churn Signal", rq.get("churn_signal","Not Available"), "Low")}
    </div>
    <div style="padding:10px 14px;background:#fffbeb;font-size:11px;color:#92400e;font-style:italic">
      Buyers pay 20-40% premiums for ARR with NRR &gt;120% and Low churn. Verify these figures in the data room.
    </div>
  </div>
</div>"""

    # ── 4. Seller story cards ────────────────────────────────────────────────
    story_strat = _h(bp.get("seller_story_strategic", ""))
    story_pe    = _h(bp.get("seller_story_pe", ""))
    process_rec = _h(bp.get("process_recommendation", ""))

    story_html = ""
    if story_strat or story_pe:
        story_html = f"""
<div style="display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--border);
  border:1px solid var(--border);border-top:3px solid var(--red);margin-bottom:2px">
  <div style="background:var(--white);padding:18px 20px">
    <p style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
      color:var(--red);font-family:'IBM Plex Mono',monospace;margin-bottom:8px">
      Seller Positioning — Strategic Acquirers</p>
    <p style="font-size:13px;color:var(--text);line-height:1.65">{story_strat or "Not available"}</p>
  </div>
  <div style="background:var(--white);padding:18px 20px">
    <p style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
      color:var(--ultra);font-family:'IBM Plex Mono',monospace;margin-bottom:8px">
      Seller Positioning — PE / Growth Equity</p>
    <p style="font-size:13px;color:var(--text);line-height:1.65">{story_pe or "Not available"}</p>
  </div>
</div>"""

    process_html = ""
    if process_rec:
        process_html = f"""
<div style="background:#f8f9ff;border-left:4px solid var(--navy);padding:14px 18px;
  margin-top:2px;margin-bottom:2px">
  <p style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
    color:var(--navy);font-family:'IBM Plex Mono',monospace;margin-bottom:6px">
    Process Recommendation</p>
  <p style="font-size:13px;color:var(--text);line-height:1.65">{process_rec}</p>
</div>"""

    return comp_table + bridge_html + rq_html + story_html + process_html


# ── Section 2: Buyer Profile + Rubric ────────────────────────────────────────

def sec_buyer(bp: Dict, ts: Optional[Dict] = None) -> str:
    prios    = bp.get("strategic_priorities",[])
    # Pull all 8 criteria — ts has the full list (buyer-specific + universal)
    criteria = (ts or {}).get("criteria_detail", bp.get("scoring_criteria",[]))
    buyer    = _h(bp.get("buyer",""))
    is_sell  = ((ts or {}).get("mode") == "sell")

    competitors    = bp.get("competitors_mapped", [])
    strategic_gaps = bp.get("strategic_gaps", bp.get("current_product_gaps", []))

    # Buy-side: buyer's own acquisition history
    buyer_acqs = bp.get("buyer_acquisitions", [])
    acq_pattern = _h(bp.get("acquisition_pattern_summary", ""))
    acqui_hire  = _h(bp.get("acqui_hire_posture", "Not available"))
    dry_powder  = _h(bp.get("dry_powder", "Not available"))

    buyer_acq_rows = "".join(
        "<tr>"
        f"<td><strong>{_h(a.get('name',''))}</strong></td>"
        f"<td>{_h(str(a.get('year','')))}</td>"
        f"<td>{'€' + str(a.get('deal_size_usd_bn','')) + 'B' if a.get('deal_size_usd_bn') else 'Undisclosed'}</td>"
        f"<td style='font-size:12px'>{_h(a.get('rationale',''))}</td>"
        "</tr>"
        for a in buyer_acqs
    ) or "<tr><td colspan='4' style='color:var(--muted)'>No acquisition history available</td></tr>"

    # Competitor acquisitions
    competitors = bp.get("competitors_mapped", [])
    comp_acq_rows_parts = []
    for comp in competitors:
        comp_name = comp.get("competitor", "")
        for acq in comp.get("acquisitions", []):
            size = acq.get("deal_size_usd_bn")
            size_str = f"${size}B" if size else "Undisclosed"
            comp_acq_rows_parts.append(
                "<tr>"
                f"<td style='font-size:11px;color:var(--muted);white-space:nowrap'>{_h(comp_name)}</td>"
                f"<td><strong>{_h(acq.get('name',''))}</strong></td>"
                f"<td>{_h(str(acq.get('year','')))}</td>"
                f"<td>{size_str}</td>"
                f"<td style='font-size:12px'>{_h(acq.get('capability_gained',''))}</td>"
                f"<td style='font-size:12px;color:#C62828'>{_h(acq.get('threat_to_buyer',''))}</td>"
                "</tr>"
            )
    comp_acq_rows = "".join(comp_acq_rows_parts) or (
        "<tr><td colspan='6' style='color:var(--muted)'>No competitor acquisition data available</td></tr>"
    )

    # Market signals
    market_signals = bp.get("market_signals", [])
    timing_colors = {"Peaking Now": "#C62828", "Near-term": "#B45309", "Emerging": "#1565C0"}
    signal_cards_parts = []
    for sig in market_signals[:5]:
        timing = sig.get("timing", "")
        tc = timing_colors.get(timing, "#555")
        signal_cards_parts.append(
            f"<div style='background:#fff;border:1px solid var(--border);border-top:3px solid {tc};"
            f"padding:14px 16px;flex:1;min-width:180px'>"
            f"<div style='font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;"
            f"color:{tc};margin-bottom:4px'>{_h(timing)}</div>"
            f"<div style='font-size:12px;font-weight:700;color:var(--navy);margin-bottom:6px'>{_h(sig.get('trend',''))}</div>"
            f"<div style='font-size:11px;color:var(--muted);line-height:1.5'>{_h(sig.get('capability_made_urgent',''))}</div>"
            f"</div>"
        )
    signal_cards = "".join(signal_cards_parts)

    rub_rows_parts = []
    for c in criteria:
        is_comp = c.get("source") == "competitive_threat"
        src_bg    = "#fff0f0" if is_comp else "#f0f4ff"
        src_color = "#C62828" if is_comp else "#3730a3"
        src_label = "⚔ Competitive" if is_comp else "📡 Market Signal"
        rub_rows_parts.append(
            f"<tr>"
            f"<td><strong>{_h(c.get('id',''))}</strong></td>"
            f"<td><strong>{_h(c.get('name',''))}</strong><br>"
            f"<span class='rj'>{_h(c.get('justification',''))}</span></td>"
            f"<td style='font-size:12px'>{_h(c.get('description',''))}</td>"
            f"<td style='text-align:center'><span style='font-size:10px;font-weight:700;"
            f"padding:2px 7px;border-radius:3px;background:{src_bg};color:{src_color}'>"
            f"{src_label}</span></td>"
            f"</tr>"
        )
    rub_rows = "".join(rub_rows_parts)

    gap_items = "".join(
        f"<li style='margin-bottom:6px;font-size:12px;color:var(--text)'>"
        f"<span style='color:var(--red);font-weight:700'>→</span> {_h(g)}</li>"
        for g in strategic_gaps[:6]
    )

    strategic_summary = _h(bp.get("strategic_summary", ""))
    target_brief_text = _h(bp.get("target_brief", ""))

    s2_title     = f"Seller Intelligence — {buyer}"  if is_sell else f"Intelligence Brief — {buyer}"
    s2_side_lbl  = "Sell-Side Profile"               if is_sell else "Buy Side Analysis"
    s2_tb_lbl    = "Ideal Acquirer Profile"           if is_sell else "Target Brief"
    s2_dp_lbl    = "Seller Financials &amp; Valuation" if is_sell else "Dry Powder &amp; Buying Capacity"
    s2_acq_lbl   = "Key Milestones &amp; Partnerships" if is_sell else f"Acquisition History \u2014 {buyer}"
    s2_comp_lbl  = ("Who is Acquiring Similar Companies"
                    if is_sell else "Competitor Acquisitions \u2014 What the Market is Buying")
    s2_rubric_lbl = ("Acquirer Scoring Rubric \u2014 8 Criteria (C1\u2013C2 acquirer capability \xb7 C3\u2013C4 market urgency \xb7 C5\u2013C8 universal)"
                     if is_sell else
                     "Sell Side Due Diligence \u2014 8 Criteria (C1\u2013C2 competitive \xb7 C3\u2013C4 market signal \xb7 C5\u2013C8 universal)")

    return f"""
<section id="s2">
  {_sh("02", s2_title)}

  <!-- ── BUY SIDE: Strategy / Dry Powder / Acquisition History ── -->
  <p style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
    color:var(--navy);margin-bottom:14px;font-family:'IBM Plex Mono',monospace;
    border-left:3px solid var(--red);padding-left:10px">{s2_side_lbl}</p>

  <!-- Strategy row -->
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--border);
    border:1px solid var(--border);border-top:3px solid var(--red);margin-bottom:2px">
    <div style="background:var(--white);padding:20px 24px">
      <p style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
        color:var(--red);margin-bottom:8px;font-family:'IBM Plex Mono',monospace">Strategy</p>
      <p style="font-size:13px;color:var(--navy);line-height:1.65;font-weight:500">{strategic_summary}</p>
    </div>
    <div style="background:var(--white);padding:20px 24px">
      <p style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
        color:var(--red);margin-bottom:8px;font-family:'IBM Plex Mono',monospace">
        {s2_tb_lbl}</p>
      <p style="font-size:13px;color:var(--text);line-height:1.65">{target_brief_text}</p>
    </div>
  </div>

  <!-- Dry Powder row -->
  <div style="background:var(--white);border:1px solid var(--border);border-top:none;
    padding:18px 24px;margin-bottom:2px">
    <p style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
      color:var(--muted);margin-bottom:8px;font-family:'IBM Plex Mono',monospace">
      {s2_dp_lbl}</p>
    <p style="font-size:13px;color:var(--text);line-height:1.65">{dry_powder}</p>
  </div>

  <!-- Acquisition History -->
  <div style="margin-bottom:2px;margin-top:2px">
    <div class="tbl-wrap" style="border:1px solid var(--border);border-top:none">
    <table style="margin-bottom:0">
      <thead><tr>
        <th colspan="4" style="text-align:left;background:var(--white);color:var(--muted);
          font-size:10px;letter-spacing:.8px;text-transform:uppercase;padding:12px 14px;
          font-family:'IBM Plex Mono',monospace;font-weight:700">
          {s2_acq_lbl}</th>
      </tr>
      <tr>
        <th>Company Acquired</th><th>Year</th><th>Size</th><th>Strategic Rationale</th>
      </tr></thead>
      <tbody>{buyer_acq_rows}</tbody>
    </table>
    </div>
    {f'<p style="font-size:12px;color:var(--muted);margin-top:8px;font-style:italic;padding:0 2px">{acq_pattern}</p>' if acq_pattern else ""}
  </div>

  <!-- Competitor Acquisitions -->
  <div style="margin-bottom:2px;margin-top:2px">
    <div class="tbl-wrap" style="border:1px solid var(--border);border-top:3px solid #C62828">
    <table style="margin-bottom:0">
      <thead><tr>
        <th colspan="6" style="text-align:left;background:var(--white);color:var(--muted);
          font-size:10px;letter-spacing:.8px;text-transform:uppercase;padding:12px 14px;
          font-family:'IBM Plex Mono',monospace;font-weight:700">
          {s2_comp_lbl}</th>
      </tr>
      <tr>
        <th>Competitor</th><th>Company Acquired</th><th>Year</th><th>Size</th>
        <th>Capability Gained</th><th style="color:#C62828">Threat to {buyer}</th>
      </tr></thead>
      <tbody>{comp_acq_rows}</tbody>
    </table>
    </div>
  </div>

  <!-- Market Signals -->
  <div style="margin-bottom:28px;margin-top:2px">
    <div style="padding:12px 14px;background:var(--white);border:1px solid var(--border);
      border-top:3px solid #1565C0;border-bottom:none">
      <p style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
        color:var(--muted);font-family:'IBM Plex Mono',monospace">
        Market Signals — Sector Trends Driving Urgency</p>
    </div>
    <div style="display:flex;gap:1px;background:var(--border);border:1px solid var(--border);
      border-top:none;flex-wrap:wrap">
      {signal_cards if signal_cards else
       '<div style="padding:14px;color:var(--muted);font-size:12px">No market signals available</div>'}
    </div>
  </div>

  <!-- ── Sell Side Due Diligence ── -->
  <p style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
    color:var(--muted);margin-bottom:12px;font-family:'IBM Plex Mono',monospace">
    {s2_rubric_lbl}</p>
  <table><thead><tr><th width="40">ID</th><th>Criterion</th><th>What It Measures (1–5)</th><th>Source</th></tr></thead>
  <tbody>{rub_rows}</tbody></table>
  {_sell_side_valuation_blocks(bp) if is_sell else ""}
  {_src_note(["Earnings calls & investor days", "SEC / regulatory filings", "PitchBook (training data)", "FT / Bloomberg (training data)", "Crunchbase (training data)"])}
</section>"""


# ── Section 3: Target Table + Score Chart ─────────────────────────────────────

_SELL_SIGNAL_LABELS = {
    "recent_funding":       "Dry Powder / Recent Raise",
    "leadership_change":    "Stated M&A Intent",
    "product_pivot":        "Competitor Acquisition",
    "market_expansion":     "Strategic Gap",
    "strategic_partnership":"Existing Partnership",
}

def sec_targets(ts: Dict, bp: Dict) -> str:
    targets  = ts.get("targets",[])
    criteria = bp.get("scoring_criteria",[])
    n        = len(targets)
    chart    = _svg_scores_chart(targets)
    is_sell  = (ts.get("mode") == "sell")
    s3_hdr   = f"Acquirer Screening \u2014 {n} Potential Acquirers" if is_sell else f"Target Screening \u2014 {n} Companies"
    arr_lbl     = "Revenue"        if is_sell else "ARR"
    raised_lbl  = "Fund Size/Cap"  if is_sell else "Raised"
    rs_lbl      = "Appetite Score" if is_sell else "Readiness Score"
    leg1_lbl    = "Top 3 — Best Acquirers" if is_sell else "Top 3 — Primary"

    cards = ""
    for t in targets:
        rank   = t.get("rank",0)
        total  = t.get("total_score",0)
        maxs   = t.get("max_score",35)
        pct    = total/maxs if maxs else 0
        scores = t.get("scores",{})
        risks  = t.get("deal_breaker_risks",[])
        fit    = t.get("strategic_fit_summary","")

        if rank <= 3:
            border = "var(--green)"; badge_bg = "#E8F5E9"; badge_c = "var(--green)"
        elif pct >= 0.5:
            border = "var(--amber)"; badge_bg = "#FFF8E1"; badge_c = "#B45309"
        else:
            border = "#bbb"; badge_bg = "#F5F5F5"; badge_c = "#555"

        score_dots = "".join(
            f'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:2px;'
            f'background:{border};opacity:{max(0.2, scores.get(c["id"], {}).get("score",0)/5):.2f}"></span>'
            for c in criteria
        )

        risk_line = f'<p style="font-size:11px;color:#B45309;margin-top:4px">⚠ {_h(risks[0])}</p>' if risks else ""

        # Readiness / appetite signals
        readiness   = t.get("readiness_score", 0)
        rs_summary  = t.get("readiness_summary", "")
        signals     = t.get("readiness_signals", {})
        rs_color    = "#2E7D32" if readiness >= 7 else ("#F57F17" if readiness >= 4 else "#9E9E9E")
        signal_pills = "".join(
            f'<span style="display:inline-block;background:#f0f4ff;border:1px solid #c7d2fe;'
            f'color:#3730a3;font-size:10px;padding:1px 7px;border-radius:3px;margin-right:4px;margin-top:3px">'
            f'&#10003; {_h(_SELL_SIGNAL_LABELS.get(k, k.replace("_"," ").title()) if is_sell else k.replace("_"," ").title())}</span>'
            for k, v in signals.items()
            if v and v.lower() not in ("not detected", "not publicly available", "n/a", "none")
        )

        # Sell-side: tier badge + approach sequence badge + vertical/ownership
        tier_badge = ""
        seq_badge  = ""
        vert_badge = ""
        owner_txt  = ""
        if is_sell:
            acq_tier = t.get("acquirer_tier", 0)
            acq_seq  = t.get("approach_sequence", 0)
            tier_cfg = {
                1: ("#015D52", "#e6f9f4", "Tier 1 — Strategic Natural"),
                2: ("#B45309", "#FFF8E1", "Tier 2 — Strategic Stretch"),
                3: ("#3730a3", "#f0f4ff", "Tier 3 — Financial Sponsor"),
            }
            if acq_tier in tier_cfg:
                tc, tbg, tlbl = tier_cfg[acq_tier]
                tier_badge = (
                    f'<span style="background:{tbg};color:{tc};font-size:10px;font-weight:700;'
                    f'padding:2px 9px;border-radius:3px;letter-spacing:.4px;border:1px solid {tc}33">'
                    f'{tlbl}</span>'
                )
            if acq_seq:
                seq_badge = (
                    f'<span style="background:#f1f3f8;color:#4a5568;font-size:10px;font-weight:600;'
                    f'padding:2px 8px;border-radius:3px;white-space:nowrap">'
                    f'Approach #{acq_seq}</span>'
                )
            # premium rationale pill
            prem_rat = t.get("premium_rationale", "")
            if prem_rat:
                signal_pills += (
                    f'<span style="display:inline-block;background:#fff5f5;border:1px solid #fca5a5;'
                    f'color:#991b1b;font-size:10px;padding:1px 7px;border-radius:3px;'
                    f'margin-right:4px;margin-top:3px">&#9650; {_h(prem_rat)}</span>'
                )
            # vertical badge + ownership inline (banker cheat-sheet fields)
            vert = t.get("vertical", "")
            if vert and str(vert).lower() not in ("not publicly available", "n/a", "none", ""):
                vert_badge = (
                    f'<span style="background:#eef2f7;color:#334155;font-size:10px;font-weight:700;'
                    f'padding:2px 9px;border-radius:3px;letter-spacing:.3px;border:1px solid #cbd5e1">'
                    f'{_h(vert)}</span>'
                )
            own = t.get("ownership", "")
            if own and str(own).lower() not in ("not publicly available", "n/a", "none", ""):
                owner_txt = f" &middot; Owner: {_h(own)}"

        # Right-column financials (sell-side adds market cap + cash when known)
        fin_lines = (f"{arr_lbl}: {_fmt_m(t.get('arr_usd_m'), t.get('arr_estimated', False))}"
                     f"<br>{raised_lbl}: {_fmt_m(t.get('total_raised_usd_m'))}")
        if is_sell:
            mc, cash = t.get("market_cap_usd_m"), t.get("cash_usd_m")
            if isinstance(mc, (int, float)) and not isinstance(mc, bool):
                fin_lines += f"<br>Mkt cap: {_fmt_m(mc)}"
            if isinstance(cash, (int, float)) and not isinstance(cash, bool):
                fin_lines += f"<br>Cash: {_fmt_m(cash)}"
        fin_lines += f"<br>Emp: {_fmt_emp(t.get('employees'))}"

        cards += f"""
<div style="border:1px solid {border};border-left:4px solid {border};border-radius:4px;
  padding:14px 16px;background:#fff;display:flex;gap:16px;align-items:flex-start">
  <div style="min-width:36px;text-align:center">
    <div style="font-size:20px;font-weight:800;color:{border}">{rank}</div>
    <div style="font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px">Rank</div>
  </div>
  <div style="flex:1;min-width:0">
    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:4px">
      <strong style="font-size:14px;color:var(--navy)">{_h(t.get('name',''))}</strong>
      <span style="font-size:11px;color:var(--muted)">{_h(t.get('country',''))} · {_h(t.get('funding_stage',''))}{owner_txt}</span>
      <span style="background:{badge_bg};color:{badge_c};font-size:10px;font-weight:700;
        padding:2px 8px;border-radius:3px;letter-spacing:.5px">{total}/{maxs}</span>
      {tier_badge}
      {seq_badge}
      {vert_badge}
    </div>
    <p style="font-size:12px;color:#4a5568;line-height:1.55;margin-bottom:4px">{_h(fit)}</p>
    <div style="margin-top:4px">{signal_pills}</div>
    {risk_line}
  </div>
  <div style="min-width:90px;text-align:right;font-size:11px;color:var(--muted);white-space:nowrap">
    {fin_lines}
  </div>
</div>"""

    # Sell-side: process recommendation callout + approach sequence legend
    process_callout = ""
    if is_sell:
        proc_rec = bp.get("process_recommendation", "")
        process_callout = f"""
  <div style="background:#f8f9ff;border-left:4px solid var(--navy);padding:14px 18px;
    margin-bottom:20px;margin-top:4px">
    <p style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
      color:var(--navy);font-family:'IBM Plex Mono',monospace;margin-bottom:6px">
      Process Recommendation &amp; Approach Sequence</p>
    <p style="font-size:13px;color:var(--text);line-height:1.65;margin-bottom:10px">
      {_h(proc_rec) if proc_rec else "Approach Tier 3 sponsors first to set the price floor, then Tier 2 to build competitive tension, and Tier 1 naturals last to extract maximum valuation premium."}
    </p>
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <span style="background:#f0f4ff;color:#3730a3;font-size:11px;font-weight:700;padding:3px 10px;border-radius:3px;border:1px solid #c7d2fe">Step 1: Tier 3 Financial Sponsors</span>
      <span style="font-size:14px;color:#9ca3af;align-self:center">&#8594;</span>
      <span style="background:#FFF8E1;color:#B45309;font-size:11px;font-weight:700;padding:3px 10px;border-radius:3px;border:1px solid #fde68a">Step 2: Tier 2 Strategic Stretch</span>
      <span style="font-size:14px;color:#9ca3af;align-self:center">&#8594;</span>
      <span style="background:#e6f9f4;color:#015D52;font-size:11px;font-weight:700;padding:3px 10px;border-radius:3px;border:1px solid #9de2d0">Step 3: Tier 1 Strategic Naturals</span>
    </div>
  </div>"""

    return f"""
<section id="s3">
  {_sh("03", s3_hdr)}

  <div style="background:var(--white);border:1px solid var(--border);
    padding:20px 24px;margin-bottom:24px;text-align:center;overflow-x:auto">
    {chart}
  </div>

  {process_callout}

  <div class="legend" style="margin-bottom:20px">
    <div class="li"><div class="ld" style="background:var(--green)"></div> {leg1_lbl}</div>
    <div class="li"><div class="ld" style="background:var(--amber)"></div> Mid Tier — Monitor</div>
    <div class="li"><div class="ld" style="background:#bbb"></div> Lower Tier</div>
    {"<div class='li'><div class='ld' style='background:#015D52'></div> Tier 1 Natural</div><div class='li'><div class='ld' style='background:#B45309'></div> Tier 2 Stretch</div><div class='li'><div class='ld' style='background:#3730a3'></div> Tier 3 Sponsor</div>" if is_sell else ""}
  </div>

  <div style="display:flex;flex-direction:column;gap:10px">
    {cards}
  </div>
  {_src_note(["Crunchbase (training data)", "PitchBook (training data)", "Company websites", "LinkedIn (training data)", "Press releases"])}
</section>"""


# ── Section 4: Top 3 Acquisition Reports ──────────────────────────────────────

def sec_top3(ts: Dict, bp: Dict, company_details: Optional[Dict] = None,
             date_str: str = "") -> str:
    targets  = ts.get("targets",[])
    criteria = ts.get("criteria_detail", bp.get("scoring_criteria",[]))
    top3     = sorted([t for t in targets if t.get("rank",99)<=3], key=lambda x: x.get("rank",99))
    t3names  = [t["name"] for t in top3]
    radar    = _radar_svg(targets, criteria, t3names)
    is_sell  = (ts.get("mode") == "sell")
    s4_title      = "Top 3 — Primary Acquirers"      if is_sell else "Top 3 — Primary Recommendations"
    arr_lbl4      = "Revenue"                         if is_sell else "ARR"
    raised_lbl4   = "Fund Size / Mkt Cap"             if is_sell else "Raised"
    inv_lbl4      = "Portfolio / LPs"                 if is_sell else "Investors"
    rec_lbl4      = "Acquisition Appetite Signals"    if is_sell else "Acquisition Readiness Signals"
    meta_lbl4     = "Revenue"                         if is_sell else "Raised"
    score_lbl4    = "Acquirer Fit Score"              if is_sell else "Strategic Fit Score"

    rl = "".join(
        f'<div class="rl"><div class="rd" style="background:{c}"></div>'
        f'<span><strong>#{t.get("rank")}</strong> {_h(t.get("name",""))}</span></div>'
        for t,c in zip(top3,["#0B1C3D","#C9A84C","#2E7D32"])
    )

    CARD_COLORS = ["#252850", "#C9A84C", "#2E7D32"]

    cards = ""
    for i, t in enumerate(top3):
        accent  = CARD_COLORS[i]
        rank    = t.get("rank", i+1)
        total   = t.get("total_score", 0)
        maxs    = t.get("max_score", 35)
        scores  = t.get("scores", {})
        risks   = t.get("deal_breaker_risks", [])
        fit     = t.get("strategic_fit_summary", "")
        rec     = t.get("recommendation", "MONITOR")
        rec_color = {"PROCEED": "#2E7D32", "MONITOR": "#F57F17", "DISCARD": "#C62828"}.get(rec, "#9E9E9E")

        score_rows = "".join(
            "<tr>"
            f'<td style="font-size:11px;color:#4a5568;padding:5px 0;white-space:nowrap;padding-right:10px">{_h(c.get("name",""))}</td>'
            f'<td style="text-align:center;padding:5px 6px;white-space:nowrap">{_sc(scores.get(c["id"], {}).get("score",0))}</td>'
            f'<td style="font-size:10px;color:#6b7280;padding:5px 0">'
            f'<span style="font-weight:600;color:#252850">Score ({scores.get(c["id"],{}).get("score","?"  )}/5)</span>'
            f' &mdash; <span style="color:#9ca3af">Reason:</span> '
            f'{_h(_strip_score_prefix(scores.get(c["id"],{}).get("rationale","")))}'
            f'</td>'
            "</tr>"
            for c in criteria
        )
        risk_items = "".join(f'<li style="font-size:11px;color:#B45309">⚠ {_h(r)}</li>' for r in risks[:3])

        # Banker fields for Top-3 detail (sell-side): cash/mkt-cap line + recent M&A block
        cash_mc_line4 = ""
        if is_sell:
            _mc4, _cash4 = t.get("market_cap_usd_m"), t.get("cash_usd_m")
            if isinstance(_mc4, (int, float)) and not isinstance(_mc4, bool):
                cash_mc_line4 += f' &nbsp;·&nbsp; Mkt cap: <strong style="color:var(--navy)">{_fmt_m(_mc4)}</strong>'
            if isinstance(_cash4, (int, float)) and not isinstance(_cash4, bool):
                cash_mc_line4 += f' &nbsp;·&nbsp; Cash: <strong style="color:var(--navy)">{_fmt_m(_cash4)}</strong>'
        _rma4 = [x for x in (t.get("relevant_ma") or [])
                 if x and str(x).strip().lower() not in ("not publicly available", "n/a", "none", "")]
        relevant_ma_block4 = ""
        if _rma4:
            _items4 = "".join(f'<li style="font-size:11px;color:#4a5568;margin-bottom:2px">{_h(x)}</li>' for x in _rma4)
            relevant_ma_block4 = (
                '<div style="margin-top:10px;padding-top:10px;border-top:1px solid var(--border)">'
                '<p style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;'
                'color:var(--muted);margin-bottom:6px">Recent M&amp;A</p>'
                f'<ul style="list-style:none;padding:0;margin:0">{_items4}</ul></div>'
            )

        # Build readiness HTML outside the f-string to avoid {{}} issues
        t_signals = t.get("readiness_signals") or {}
        active_signals = {k: v for k, v in t_signals.items()
                         if v and v.lower() not in ("not detected", "not publicly available", "n/a", "none")}
        if active_signals:
            readiness_html = "".join(
                f'<div style="font-size:11px;margin-bottom:3px;color:#2d3748">'
                f'<span style="color:#2E7D32;font-weight:700">&#10003;</span> '
                f'<strong>{_SELL_SIGNAL_LABELS.get(k, k.replace("_"," ").title()) if is_sell else k.replace("_"," ").title()}:</strong> {_h(v)}</div>'
                for k, v in active_signals.items()
            )
        else:
            no_sig_txt = "No strong acquisition appetite signals detected" if is_sell else "No strong readiness signals detected"
            readiness_html = f"<span style='font-size:11px;color:var(--muted)'>{no_sig_txt}</span>"
        readiness_summary_html = _h(t.get("readiness_summary", ""))

        # Tier badge for sell-side cards
        tier_hdr_badge = ""
        prem_rat_html  = ""
        if is_sell:
            acq_tier4 = t.get("acquirer_tier", 0)
            acq_seq4  = t.get("approach_sequence", 0)
            tier4_cfg = {
                1: ("Tier 1 — Strategic Natural", "rgba(255,255,255,.2)", "#fff"),
                2: ("Tier 2 — Strategic Stretch", "rgba(255,255,255,.15)", "rgba(255,255,255,.9)"),
                3: ("Tier 3 — Financial Sponsor", "rgba(255,255,255,.15)", "rgba(255,255,255,.9)"),
            }
            if acq_tier4 in tier4_cfg:
                tlbl4, tbg4, tc4 = tier4_cfg[acq_tier4]
                tier_hdr_badge = (
                    f'<span style="display:inline-block;background:{tbg4};color:{tc4};'
                    f'font-size:10px;font-weight:700;padding:2px 10px;border-radius:3px;'
                    f'letter-spacing:.5px;margin-left:6px">{tlbl4}</span>'
                )
            prem_rat = t.get("premium_rationale", "")
            if prem_rat:
                seq_txt = f"Approach #{acq_seq4} in process" if acq_seq4 else ""
                prem_rat_html = (
                    f'<div style="margin-top:8px;padding:8px 12px;background:rgba(255,255,255,.12);'
                    f'border-radius:3px">'
                    f'<span style="font-size:10px;font-weight:700;color:rgba(255,255,255,.65);'
                    f'text-transform:uppercase;letter-spacing:.6px">Premium Rationale</span>'
                    f'<p style="font-size:12px;color:#fff;margin-top:3px;line-height:1.5">'
                    f'&#9650; {_h(prem_rat)}'
                    f'{(" &nbsp;·&nbsp; " + seq_txt) if seq_txt else ""}</p>'
                    f'</div>'
                )

        cards += f"""
<div style="border:1px solid {accent};border-top:4px solid {accent};border-radius:4px;
  background:#fff;overflow:hidden;margin-bottom:16px">
  <div style="background:{accent};padding:14px 20px;display:flex;align-items:center;
    justify-content:space-between;flex-wrap:wrap;gap:10px">
    <div>
      <div style="font-size:10px;color:rgba(255,255,255,.65);text-transform:uppercase;
        letter-spacing:.8px;margin-bottom:2px">#{rank} Primary Recommendation{tier_hdr_badge}</div>
      <div style="font-size:19px;font-weight:700;color:#fff">{_h(t.get('name',''))}</div>
      <div style="font-size:12px;color:rgba(255,255,255,.7);margin-top:2px">
        {_h(t.get('country',''))} · {_h(t.get('funding_stage',''))} · {meta_lbl4} {_fmt_m(t.get('total_raised_usd_m'))} · {_fmt_emp(t.get('employees'))} employees
      </div>
      {prem_rat_html}
    </div>
    <div style="text-align:right">
      <div style="font-size:28px;font-weight:800;color:#fff;line-height:1">{total}/{maxs}</div>
      <div style="font-size:10px;color:rgba(255,255,255,.65)">{score_lbl4}</div>
      <div style="display:inline-block;background:{rec_color};color:#fff;font-size:10px;font-weight:700;
        padding:2px 10px;border-radius:3px;margin-top:6px;letter-spacing:.5px">{_h(rec)}</div>
    </div>
  </div>
  <div style="padding:16px 20px;display:grid;grid-template-columns:1fr 1fr;gap:20px">
    <div>
      <p style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;
        color:var(--muted);margin-bottom:8px">Strategic Fit</p>
      <p style="font-size:12px;color:#2d3748;line-height:1.6">{_h(fit)}</p>
      <div style="margin-top:10px">
        <p style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;
          color:var(--muted);margin-bottom:6px">Key Risks</p>
        <ul style="list-style:none;padding:0">{risk_items if risk_items else '<li style="font-size:11px;color:var(--green)">No major risks identified</li>'}</ul>
      </div>
    </div>
    <div>
      <p style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;
        color:var(--muted);margin-bottom:8px">Criterion Scores</p>
      <table style="width:100%;border-collapse:collapse">{score_rows}</table>
      <div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--border);
        font-size:11px;color:var(--muted)">
        {arr_lbl4}: <strong style="color:var(--navy)">{_fmt_m(t.get('arr_usd_m'))}</strong> &nbsp;·&nbsp;
        Employees: <strong style="color:var(--navy)">{_fmt_emp(t.get('employees'))}</strong> &nbsp;·&nbsp;
        {inv_lbl4}: <strong style="color:var(--navy)">{_h(_list_str(t.get('key_investors',[])))[:60]}</strong>{cash_mc_line4}
      </div>
      <div style="margin-top:10px;padding-top:10px;border-top:1px solid var(--border)">
        <p style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;
          color:var(--muted);margin-bottom:6px">{rec_lbl4}</p>
        {readiness_html}
        <p style="font-size:11px;color:#4a5568;margin-top:6px;font-style:italic">{readiness_summary_html}</p>
      </div>
      {relevant_ma_block4}
    </div>
  </div>
</div>"""

    return f"""
<section id="s4">
  {_sh("04", s4_title)}

  <div class="radar-wrap" style="margin-bottom:28px">
    <div style="background:var(--white);border:1px solid var(--border);padding:18px">{radar}</div>
    <div>
      <p style="font-size:12px;font-weight:700;color:var(--navy);margin-bottom:10px;
        text-transform:uppercase;letter-spacing:.5px">Comparative Radar — 7 Criteria</p>
      <div class="radar-leg">{rl}</div>
      <p style="font-size:11px;color:var(--muted);margin-top:12px">Outer edge = score of 5/5</p>
    </div>
  </div>
  {cards}
  {_src_note(["Crunchbase (training data)", "PitchBook (training data)", "LinkedIn (training data)", "FT / TechCrunch (training data)", "Company websites"])}
</section>"""


# ── Section 5: DCF Valuation ─────────────────────────────────────────────────

def sec_strip_profile(ts: Dict) -> str:
    targets  = ts.get("targets", [])
    top3     = sorted([t for t in targets if t.get("rank", 99) <= 3], key=lambda x: x.get("rank", 99))
    is_sell  = (ts.get("mode") == "sell")
    s5_title = "Strip Profile \u2014 Top 3 Acquirers" if is_sell else "Strip Profile \u2014 Top 3 Targets"
    callout5 = ("Side-by-side comparison of the three primary acquisition candidates (from the acquirer's perspective)."
                if is_sell else
                "Side-by-side operational comparison of the three primary acquisition candidates.")

    def _safe_float(v):
        try: return float(v)
        except: return None

    def _ticket(raised):
        r = _safe_float(raised)
        if r: return f"€{r:.0f}M"
        return "N/A"

    def _fmt_gbp(v):
        """Format a GBP millions figure for display."""
        if v is None:
            return None
        return f"£{v:,.1f}M"

    # ── Companies House enrichment (UK companies only, requires API key) ──────
    ch_data: Dict[str, Optional[Dict]] = {}
    ch_available = bool(os.environ.get("COMPANIES_HOUSE_API_KEY", ""))
    if ch_available:
        for t in top3:
            name = t.get("name", "")
            country = str(t.get("country", "")).lower()
            is_uk = any(x in country for x in ("uk", "united kingdom", "england", "scotland", "wales"))
            if is_uk:
                print(f"  [CH] Looking up {name}...")
                ch_data[name] = ch_api.lookup(name)
            else:
                ch_data[name] = None
    else:
        for t in top3:
            ch_data[t.get("name", "")] = None

    def _ch(t: Dict, field: str):
        """Return a CH financial field or None."""
        d = ch_data.get(t.get("name", ""))
        return d.get(field) if d else None

    def _ch_cell(t: Dict, field: str, label_suffix: str = "") -> str:
        """Render a cell value: live CH data (green) if available, else 'N/A'."""
        val = _ch(t, field)
        if val is not None:
            display = _fmt_gbp(val) if isinstance(val, float) else _h(str(val))
            return (
                f'<span style="color:#1b5e20;font-weight:700">{display}</span>'
                f'<span style="font-size:10px;color:#388e3c;display:block;margin-top:1px">'
                f'✓ Companies House{label_suffix}</span>'
            )
        return '<span style="color:#9ca3af">N/A</span>'

    # Header row
    hdr = "".join(
        f'<th style="background:var(--navy);color:#fff;padding:10px 14px;text-align:left">'
        f'#{t.get("rank")} {_h(t.get("name",""))}</th>'
        for t in top3
    )

    # Build metrics list — CH financials appear when found
    def _metric_row(label: str, vals: List[str]) -> str:
        return (label, vals)

    raised_row_lbl = "Fund Size / Mkt Cap" if is_sell else "Ticket Size (Raised)"
    stage_row_lbl  = "Acquirer Type"       if is_sell else "Stage"
    emp_row_lbl    = "Headcount"           if is_sell else "Employees"

    metrics: List[Any] = [
        (emp_row_lbl,     [_fmt_emp(t.get("employees")) for t in top3]),
        (raised_row_lbl,  [_ticket(t.get("total_raised_usd_m")) for t in top3]),
        ("Country",       [_h(t.get("country","N/A")) for t in top3]),
        (stage_row_lbl,   [_h(t.get("funding_stage","N/A")) for t in top3]),
    ]
    if is_sell:
        metrics.insert(0, ("Annual Revenue", [_fmt_m(t.get("arr_usd_m")) for t in top3]))

    # CH financial rows — only emit if at least one company has live data
    ch_fields = [
        ("Revenue (£M)",          "revenue_gbp_m"),
        ("Gross Profit (£M)",     "gross_profit_gbp_m"),
        ("EBITDA / Op. Profit",   "ebitda_gbp_m"),
        ("Profit Before Tax (£M)","profit_before_tax_gbp_m"),
    ]
    for label, field in ch_fields:
        has_data = any(_ch(t, field) is not None for t in top3)
        if has_data:
            metrics.append((label, [_ch_cell(t, field) for t in top3], True))

    rows = ""
    for i, row in enumerate(metrics):
        label = row[0]
        vals  = row[1]
        raw_html = len(row) > 2 and row[2]  # flag: vals contain pre-built HTML
        bg = "#f8fafc" if i % 2 == 0 else "#fff"
        cells = "".join(
            f'<td style="padding:10px 14px;font-size:13px;color:var(--navy);font-weight:600">{v}</td>'
            for v in vals
        ) if not raw_html else "".join(
            f'<td style="padding:10px 14px;font-size:12px">{v}</td>'
            for v in vals
        )
        rows += (
            f'<tr style="background:{bg}">'
            f'<td style="padding:10px 14px;font-size:12px;font-weight:700;color:var(--muted);'
            f'text-transform:uppercase;letter-spacing:.4px;white-space:nowrap">{label}</td>'
            f'{cells}</tr>'
        )

    # Source note wording depends on whether CH data was fetched
    has_live_ch = any(v is not None for v in ch_data.values())
    if has_live_ch:
        src_sources = ["Crunchbase (training data)", "PitchBook (training data)",
                       "~Companies House API (live, UK only)"]
        src_live = True
        note_extra = '<p style="font-size:11px;color:#1b5e20;margin-top:8px">✓ Revenue, profit and EBITDA rows sourced live from Companies House annual accounts filings (iXBRL). All figures in GBP.</p>'
    else:
        src_sources = ["Crunchbase (training data)", "PitchBook (training data)"]
        src_live = False
        note_extra = ""
        if ch_available:
            note_extra = '<p style="font-size:11px;color:#9ca3af;margin-top:8px;font-style:italic">No UK-registered companies in top 3 — Companies House financials not applicable.</p>'
        else:
            note_extra = '<p style="font-size:11px;color:#9ca3af;margin-top:8px;font-style:italic">Add COMPANIES_HOUSE_API_KEY to .env to pull live revenue, profit &amp; EBITDA for UK companies.</p>'

    note = '<p style="font-size:11px;color:var(--muted);margin-top:12px;font-style:italic">* Ticket size reflects total disclosed funding raised. Financial figures sourced from public disclosures where available.</p>'

    return f"""
<section id="s5">
  {_sh("05", s5_title)}
  <div class="callout" style="margin-bottom:20px">
    {callout5}
  </div>
  <div class="tbl-wrap">
  <table style="width:100%">
    <thead><tr>
      <th style="background:var(--navy);color:#fff;padding:10px 14px;text-align:left;width:180px">Metric</th>
      {hdr}
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
  </div>
  {note}
  {note_extra}
  {_src_note(src_sources, live=src_live)}
</section>"""


# ── Section 6: Client Summary ─────────────────────────────────────────────────

def sec_client(ts: Dict, bp: Dict) -> str:
    targets  = ts.get("targets",[])
    criteria = bp.get("scoring_criteria",[])
    is_sell  = (ts.get("mode") == "sell")
    s6_title = "Acquirer Summary \u2014 At a Glance" if is_sell else "Target Summary \u2014 At a Glance"
    s6_src   = "Scoring: C1\u2013C8 as defined in Seller Profile" if is_sell else "Scoring: C1\u2013C8 as defined in Buyer Profile"

    cards = ""
    for t in targets:
        rank   = t.get("rank",0)
        scores = t.get("scores",{})
        badges = "".join(_cb(scores.get(c["id"],{}).get("score",0), c["name"]) for c in criteria)
        desc   = t.get("product_profile", t.get("product_description","")) or ""
        # No truncation — show full description
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
  {_sh("06", s6_title)}
  <p style="font-size:11px;color:var(--muted);margin-bottom:20px;letter-spacing:.3px">
    ✓ Strong fit (4–5) &nbsp;·&nbsp; ~ Partial fit (3) &nbsp;·&nbsp; ✗ Weak fit (1–2)
  </p>
  <div class="cs-grid">{cards}</div>
  {_src_note(["Derived from Sections 1–5 above", s6_src])}
</section>"""


# ──────────────────────────────────────────────────────────────────────────────
# Full HTML
# ──────────────────────────────────────────────────────────────────────────────

def _sec_workflow_engine() -> str:
    steps = [
        ("01", "User Input", "Buyer · Sector · Geography", "Flask web form", "#252850"),
        ("02", "Buyer Intelligence", "Strategy · Dry Powder · Acquisition History · Competitor Threats · Market Signals", "Claude API (claude-sonnet-4-6)\nTraining data: public filings, news, CrunchBase, PitchBook", "#CC0605"),
        ("03", "Target Longlist", "Batch A: 6 companies\nBatch B: 4 additional\nBuyer-brief filtered", "Claude API × 2 calls\nTraining data: CrunchBase, Companies House, LinkedIn, press releases", "#1565C0"),
        ("04", "Scoring & Ranking", "C1–C8 scored 1–5\nPython recalculates totals\nRanked descending", "Claude API × 2 batches\nPython arithmetic (no model totals trusted)", "#2E7D32"),
        ("05", "Report Generation", "HTML dashboard\nPPTX deck\nData sources disclaimer", "step4_output.py → report.html\nstep5_pptx.py → report.pptx\npython-pptx library", "#6A1B9A"),
    ]

    cards = ""
    for i, (num, title, content, tools, color) in enumerate(steps):
        arrow = f'<div style="font-size:22px;color:#ccc;padding:0 8px;align-self:center">→</div>' if i < len(steps)-1 else ""
        cards += f"""
<div style="display:flex;align-items:stretch;gap:0">
  <div style="background:#fff;border:1px solid #e0e4ef;border-top:3px solid {color};
    width:200px;min-width:200px;padding:14px 16px;position:relative">
    <div style="position:absolute;top:10px;right:12px;font-size:10px;font-weight:700;
      color:{color};letter-spacing:.08em">STEP {num}</div>
    <div style="font-size:13px;font-weight:700;color:#252850;margin-bottom:8px;
      padding-right:40px">{title}</div>
    <div style="font-size:11px;color:#555;line-height:1.55;margin-bottom:10px;
      white-space:pre-line">{content}</div>
    <div style="background:#f5f7ff;border-left:2px solid {color};padding:6px 8px;
      margin-top:auto">
      <div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;
        color:{color};margin-bottom:3px">Tools / Data</div>
      <div style="font-size:10px;color:#444;line-height:1.5;white-space:pre-line">{tools}</div>
    </div>
  </div>
  {arrow}
</div>"""

    data_sources = [
        ("#3730a3", "Crunchbase / PitchBook", "Funding, investors, ARR estimates"),
        ("#1565C0", "Companies House / Handelsregister", "Incorporation, directors, filings"),
        ("#0a66c2", "LinkedIn", "Headcount, leadership changes"),
        ("#CC0605", "FT / TechCrunch", "News, partnerships, market signals"),
        ("#2E7D32", "Claude Training Data", "Synthesised from above (pre-Apr 2025)"),
    ]
    src_pills = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:5px;background:#fff;'
        f'border:1px solid {c};border-radius:3px;padding:4px 10px;font-size:11px;'
        f'color:{c};font-weight:600;margin:3px">'
        f'<span style="width:8px;height:8px;border-radius:50%;background:{c};'
        f'display:inline-block"></span>{name}</span>'
        for c, name, _ in data_sources
    )

    return f"""
<section id="wf1" style="margin-top:48px">
  <div style="border:1px solid var(--border);border-top:3px solid var(--navy)">
    <div style="background:var(--navy);padding:14px 20px">
      <span style="font-size:10px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;
        color:rgba(255,255,255,.6)">Appendix A — Engine Architecture</span>
      <span style="font-size:12px;font-weight:600;color:#fff;margin-left:16px">
        How this report was generated</span>
    </div>
    <div style="padding:24px;background:#fafbff;overflow-x:auto">
      <div style="display:flex;align-items:flex-start;gap:8px;min-width:900px">
        {cards}
      </div>
    </div>
    <div style="padding:14px 20px;background:#fff;border-top:1px solid var(--border)">
      <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;
        color:var(--muted);margin-bottom:8px">Underlying Data Sources (all via Claude training data)</div>
      <div>{src_pills}</div>
      <p style="font-size:11px;color:#888;margin-top:10px;line-height:1.5">
        All data is AI-synthesised from public sources available before April 2025.
        No live API connections are made during report generation.
        Verify all figures independently before use in investment decisions.
      </p>
    </div>
  </div>
</section>"""


def _sec_workflow_ma() -> str:
    phases = [
        {
            "num": "1",
            "title": "Mandate Definition",
            "color": "#252850",
            "items": ["Buyer strategy researched from public sources", "Dry powder & deal size range established", "M&A thesis and target brief written", "4 buyer-specific scoring criteria derived (C1–C4)"],
            "output": "buyer_profile.json",
        },
        {
            "num": "2",
            "title": "Longlist Generation",
            "color": "#CC0605",
            "items": ["Buyer brief used as search filter", "Batch A: 6 candidates identified", "Batch B: 4 additional (non-duplicate)", "Acquisition readiness signals assessed per company"],
            "output": "targets_raw.json\n10 companies",
        },
        {
            "num": "3",
            "title": "Strategic Scoring",
            "color": "#1565C0",
            "items": ["C1–C4: Buyer-specific criteria", "C5: Technology & IP", "C6: Market Position", "C7: Team & Talent", "C8: Legal & Regulatory", "Each scored 1–5, totals recalculated in Python"],
            "output": "targets_scored.json\nRanked 1–N",
        },
        {
            "num": "4",
            "title": "Shortlist Output",
            "color": "#2E7D32",
            "items": ["Top 3 highlighted in green", "Ranked table of all candidates", "Strip profile for top 3", "Deal-breaker risks flagged"],
            "output": "report.html\nreport.pptx",
        },
    ]

    cols = ""
    for i, p in enumerate(phases):
        arrow = '<div style="font-size:24px;color:#ccc;padding-top:60px;flex-shrink:0">→</div>' if i < len(phases)-1 else ""
        items_html = "".join(
            f'<div style="display:flex;gap:6px;margin-bottom:5px">'
            f'<span style="color:{p["color"]};font-weight:700;flex-shrink:0">·</span>'
            f'<span style="font-size:11px;color:#444;line-height:1.4">{item}</span>'
            f'</div>'
            for item in p["items"]
        )
        cols += f"""
<div style="flex:1;min-width:180px">
  <div style="background:{p["color"]};color:#fff;padding:10px 14px;margin-bottom:0">
    <div style="font-size:9px;font-weight:700;letter-spacing:.1em;opacity:.7;margin-bottom:2px">
      PHASE {p["num"]}</div>
    <div style="font-size:14px;font-weight:700">{p["title"]}</div>
  </div>
  <div style="border:1px solid #e0e4ef;border-top:none;padding:14px;background:#fff;
    min-height:180px">
    {items_html}
  </div>
  <div style="background:#f5f7ff;border:1px solid #e0e4ef;border-top:none;
    padding:8px 14px">
    <div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;
      color:{p["color"]};margin-bottom:3px">Output</div>
    <div style="font-size:10px;color:#333;font-family:'IBM Plex Mono',monospace;
      white-space:pre-line">{p["output"]}</div>
  </div>
</div>
{"<div style='padding-top:30px;flex-shrink:0'>" + arrow + "</div>" if arrow else ""}"""

    bank_comparison = [
        ("Mandate definition", "2–4 weeks with Corp Dev & CFO", "~2 min (AI-synthesised from public data)"),
        ("Longlist generation", "30–80 companies via PitchBook + banker network", "10–12 companies (AI discovery, public footprint only)"),
        ("Financial screening", "Live PitchBook data, audited accounts", "AI-recalled figures — verify independently"),
        ("Shortlisting", "Senior banker judgment + relationship intel", "C1–C8 rubric scoring — systematic but not relationship-driven"),
        ("Off-market companies", "Major advantage via banker network", "Not covered — AI only knows public companies"),
        ("Sellability assessment", "Ownership map, fund lifecycle, prior interest", "Not currently assessed — recommend manual overlay"),
        ("Speed (phases 1–3)", "3–6 months", "~5–8 minutes"),
    ]

    rows = ""
    for i, (stage, bank, engine) in enumerate(bank_comparison):
        bg = "#fafbff" if i % 2 == 0 else "#fff"
        rows += (
            f'<tr style="background:{bg}">'
            f'<td style="padding:9px 12px;font-size:12px;font-weight:600;color:#252850;'
            f'border-bottom:1px solid #eee">{stage}</td>'
            f'<td style="padding:9px 12px;font-size:12px;color:#444;border-bottom:1px solid #eee">{bank}</td>'
            f'<td style="padding:9px 12px;font-size:12px;color:#444;border-bottom:1px solid #eee">{engine}</td>'
            f'</tr>'
        )

    return f"""
<section id="wf2" style="margin-top:24px">
  <div style="border:1px solid var(--border);border-top:3px solid var(--red)">
    <div style="background:var(--navy);padding:14px 20px">
      <span style="font-size:10px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;
        color:rgba(255,255,255,.6)">Appendix B — M&amp;A Target Identification Process</span>
      <span style="font-size:12px;font-weight:600;color:#fff;margin-left:16px">
        How the acquisition search works</span>
    </div>
    <div style="padding:24px;background:#fafbff;overflow-x:auto">
      <div style="display:flex;align-items:flex-start;gap:0;min-width:800px">
        {cols}
      </div>
    </div>
    <div style="padding:20px 24px;background:#fff;border-top:1px solid var(--border)">
      <p style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;
        color:var(--muted);margin-bottom:12px">Comparison vs. Investment Bank Process (Phases 1–3)</p>
      <table style="width:100%;border-collapse:collapse">
        <thead>
          <tr style="background:var(--navy)">
            <th style="padding:9px 12px;text-align:left;font-size:11px;color:#fff;font-weight:700">Stage</th>
            <th style="padding:9px 12px;text-align:left;font-size:11px;color:#fff;font-weight:700">Investment Bank</th>
            <th style="padding:9px 12px;text-align:left;font-size:11px;color:#fff;font-weight:700">Strategic Fit Engine</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  </div>
</section>"""


def _data_sources_box() -> str:
    sources = [
        ("Crunchbase / PitchBook",
         "Funding rounds, investor lists, ARR estimates, and company stage. "
         "Figures are based on last publicly disclosed rounds; actual current metrics may differ.",
         "#3730a3", "#eef2ff"),
        ("Companies House (UK) / Handelsregister (DE)",
         "Incorporation data, registered address, and director information for UK and German entities. "
         "Free public registries — data reflects filings as of model training cutoff.",
         "#1565C0", "#e3f2fd"),
        ("LinkedIn",
         "Employee headcount estimates and leadership team composition. "
         "Figures are approximate; LinkedIn counts active profiles, not payroll headcount.",
         "#0a66c2", "#e8f4fd"),
        ("FT / TechCrunch / Company Press Releases",
         "Recent news, product announcements, partnerships, and market context. "
         "News signals reflect coverage available prior to the AI model's training cutoff (early 2025).",
         "#CC0605", "#fff5f5"),
    ]

    cards = ""
    for name, desc, color, bg in sources:
        cards += (
            f'<div style="background:{bg};border-left:3px solid {color};'
            f'padding:14px 16px;flex:1;min-width:200px">'
            f'<p style="font-size:10px;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:.08em;color:{color};margin-bottom:6px">{name}</p>'
            f'<p style="font-size:12px;color:#444;line-height:1.55">{desc}</p>'
            f'</div>'
        )

    return f"""
<section id="sources" style="margin-top:48px">
  <div style="border:1px solid var(--border);border-top:3px solid var(--navy)">
    <div style="background:var(--navy);padding:14px 20px;display:flex;align-items:center;gap:12px">
      <span style="font-size:10px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;
        color:rgba(255,255,255,.6)">Data Sources &amp; Reliability</span>
      <span style="background:#CC0605;color:#fff;font-size:10px;font-weight:700;
        padding:2px 8px;letter-spacing:.04em">AI-GENERATED — VERIFY BEFORE USE</span>
    </div>
    <div style="padding:16px;background:#fafafa;border-bottom:1px solid var(--border)">
      <p style="font-size:12px;color:#555;line-height:1.6">
        <strong style="color:var(--navy)">Important:</strong> All company profiles, financials,
        funding data, and market intelligence in this report are generated by Claude (Anthropic),
        an AI language model with a training data cutoff of <strong>early 2025</strong>.
        Data is synthesised from publicly available sources listed below — it is
        <strong>not pulled live</strong> from any database or API.
        All figures should be independently verified against primary sources before use in
        investment decisions, client presentations, or due diligence processes.
        The AI model does not have access to real-time data, proprietary deal databases,
        or non-public company information.
        <strong style="color:#CC0605">Final verification step recommended:</strong>
        Pull 2024–2025 year-end financials from Companies House, Crunchbase, or direct
        company disclosure before any client-facing use, as this report was generated in
        April 2026 against a training cutoff of early 2025.
      </p>
    </div>
    <div style="display:flex;flex-wrap:wrap;gap:1px;background:var(--border)">
      {cards}
    </div>
    <div style="padding:12px 16px;background:#fff;border-top:1px solid var(--border)">
      <p style="font-size:11px;color:#888;line-height:1.5">
        <strong>Recommended verification workflow:</strong>
        (1) Confirm company is still independently operating — check LinkedIn, Crunchbase, and company website →
        (2) Cross-reference funding and HQ on Crunchbase / PitchBook →
        (3) Check Companies House / Handelsregister for latest accounts filing →
        (4) Search FT, TechCrunch, and company newsrooms for events in 2025–2026 →
        (5) Verify ARR estimates against 2024 annual report or Companies House turnover figures.
        Flag any discrepancies before sharing externally.
      </p>
    </div>
  </div>
</section>"""


def build_html(bp: Dict, ts: Dict) -> str:
    buyer   = _h(bp.get("buyer",""))
    sector  = _h(ts.get("sector",""))
    geo     = _h(ts.get("geography",""))
    now     = datetime.now().strftime("%d %B %Y")
    is_sell = (ts.get("mode") == "sell")
    doc_type     = "Exit Strategy Analysis" if is_sell else "M&A Target Screening"
    nav_s2_lbl   = "Seller Profile"        if is_sell else "Buyer Profile"
    nav_s3_lbl   = "Acquirer Screening"    if is_sell else "Target Screening"
    nav_s4_lbl   = "Top 3 Acquirers"       if is_sell else "Top 3 Targets"

    s1 = sec_exec(bp, ts)
    s2 = sec_buyer(bp, ts)
    s3 = sec_targets(ts, bp)
    s4 = sec_top3(ts, bp, date_str=now)
    s5 = sec_strip_profile(ts)
    s6 = sec_client(ts, bp)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{doc_type} — {buyer}</title>
  <style>{CSS}</style>
</head>
<body>

<div class="cover-bar"></div>

<header>
  <div class="logo-wrap">
    {BULL_LOGO}
    <div class="logo-wordmark">Strategic Fit Engine</div>
  </div>
  <div class="header-right">
    <div class="doc-title">{doc_type} — {buyer}</div>
    <div class="doc-meta">{sector} &nbsp;·&nbsp; {geo}</div>
    <div class="doc-meta">{now}</div>
    <div><span class="confidential">Confidential &mdash; Not for Distribution</span></div>
  </div>
</header>

<nav>
  <a href="#s1">Executive Summary</a>
  <a href="#s2">{nav_s2_lbl}</a>
  <a href="#s3">{nav_s3_lbl}</a>
  <a href="#s4">{nav_s4_lbl}</a>
  <a href="#s5">Strip Profile</a>
  <a href="#s6">Summary</a>
</nav>

<div id="mo"><div class="modal"><div id="mc"></div></div></div>

<div class="fab-group">
  <a class="pptx-btn" href="/download/pptx" download>
    <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/>
    </svg>
    Download PPTX
  </a>
  <a class="pptx-btn" href="/download/excel" download
    style="background:#1D6F42">
    <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/>
    </svg>
    Download Excel
  </a>
  <button class="pdf-btn" onclick="downloadPDF()">
    <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/>
    </svg>
    Download PDF
  </button>
</div>

<div class="page">
  {s1}{s2}{s3}{s4}{s5}{s6}
  {_data_sources_box()}
</div>

<footer>
  <strong>Strategic Fit Engine</strong> &nbsp;&mdash;&nbsp;
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


def run(bp: Optional[Dict]=None, ts: Optional[Dict]=None,
        output_dir: Optional[Path]=None) -> str:
    if bp is None:
        with open(DATA_DIR/"buyer_profile.json",encoding="utf-8") as f: bp=json.load(f)
    if ts is None:
        with open(DATA_DIR/"targets_scored.json",encoding="utf-8") as f: ts=json.load(f)

    print("  Building report...")
    html = build_html(bp, ts)
    report_path = (Path(output_dir) / "report.html") if output_dir is not None else None
    save(html, report_path)

    print("  Building PowerPoint deck...")
    from strategic_fit_engine import step5_pptx
    step5_pptx.build_pptx(bp, ts, output_dir=output_dir)

    return str(report_path if report_path is not None else OUTPUT_DIR / "report.html")


if __name__ == "__main__":
    print("\n[Step 4] GP Bullhound Report Generation")
    print(run())
