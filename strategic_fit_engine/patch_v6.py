"""
Patch the Duolingo v6 HTML with 4 formatting changes.
Usage: python strategic_fit_engine/patch_v6.py <path_to_v6.html>
"""
import re, sys
from pathlib import Path

src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/v6.html")
html = src.read_text(encoding="utf-8")

# ── 1. ADD EXCEL BUTTON (before the PDF button) ───────────────────────────────
html = html.replace(
    '  <button class="pdf-btn" onclick="downloadPDF()">',
    '''  <a class="pptx-btn" href="/download/excel" download style="background:#1D6F42">
    <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/>
    </svg>
    Download Excel
  </a>
  <button class="pdf-btn" onclick="downloadPDF()">''',
    1
)

# ── 2. REPLACE CALLOUT WITH TOP 3 CARDS ──────────────────────────────────────
top3 = '''
  <div style="margin-top:20px;margin-bottom:20px">
    <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
      color:var(--muted);margin-bottom:12px;font-family:'IBM Plex Mono',monospace">Top 3 Recommended Targets</div>
    <div style="display:flex;gap:16px">

      <div style="flex:1;background:#fff;border:1.5px solid #2E7D32;border-radius:6px;padding:16px 18px;border-top:4px solid #2E7D32;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
          <div>
            <span style="font-size:9px;font-weight:700;color:#2E7D32;text-transform:uppercase;letter-spacing:.5px">#1 Recommendation</span>
            <div style="font-size:15px;font-weight:700;color:var(--navy);margin-top:2px">Mimo (Germany)</div>
            <div style="font-size:11px;color:var(--muted)">Germany &middot; Seed</div>
          </div>
          <div style="text-align:right">
            <div style="font-size:22px;font-weight:700;color:#2E7D32">30</div>
            <div style="font-size:9px;color:var(--muted)">out of 40</div>
          </div>
        </div>
        <p style="font-size:11.5px;color:#374151;line-height:1.6;margin-bottom:10px">Mimo is a mobile-first, bite-sized coding education app teaching Python, JavaScript, and SQL through gamified lessons, with 15 million downloads.</p>
        <div style="display:flex;gap:12px;font-size:10.5px;color:var(--muted);padding-top:8px;border-top:1px solid var(--border)">
          <span>ARR: <strong style="color:var(--navy)">$10M</strong></span>
          <span>Raised: <strong style="color:var(--navy)">$28.6M</strong></span>
          <span>Employees: <strong style="color:var(--navy)">50</strong></span>
        </div>
      </div>

      <div style="flex:1;background:#fff;border:1.5px solid #2E7D32;border-radius:6px;padding:16px 18px;border-top:4px solid #2E7D32;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
          <div>
            <span style="font-size:9px;font-weight:700;color:#2E7D32;text-transform:uppercase;letter-spacing:.5px">#2 Recommendation</span>
            <div style="font-size:15px;font-weight:700;color:var(--navy);margin-top:2px">Enki (UK)</div>
            <div style="font-size:11px;color:var(--muted)">United Kingdom &middot; Seed</div>
          </div>
          <div style="text-align:right">
            <div style="font-size:22px;font-weight:700;color:#2E7D32">28</div>
            <div style="font-size:9px;color:var(--muted)">out of 40</div>
          </div>
        </div>
        <p style="font-size:11.5px;color:#374151;line-height:1.6;margin-bottom:10px">Enki is an AI-driven daily coding skill-building platform delivering bite-sized mobile lessons for working professionals, powered by GPT-4 personalised mentoring.</p>
        <div style="display:flex;gap:12px;font-size:10.5px;color:var(--muted);padding-top:8px;border-top:1px solid var(--border)">
          <span>ARR: <strong style="color:var(--navy)">$500K</strong></span>
          <span>Raised: <strong style="color:var(--navy)">$5.5M</strong></span>
          <span>Employees: <strong style="color:var(--navy)">67</strong></span>
        </div>
      </div>

      <div style="flex:1;background:#fff;border:1.5px solid #2E7D32;border-radius:6px;padding:16px 18px;border-top:4px solid #2E7D32;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
          <div>
            <span style="font-size:9px;font-weight:700;color:#2E7D32;text-transform:uppercase;letter-spacing:.5px">#3 Recommendation</span>
            <div style="font-size:15px;font-weight:700;color:var(--navy);margin-top:2px">CoderPad</div>
            <div style="font-size:11px;color:var(--muted)">France &middot; Series B</div>
          </div>
          <div style="text-align:right">
            <div style="font-size:22px;font-weight:700;color:#2E7D32">24</div>
            <div style="font-size:9px;color:var(--muted)">out of 40</div>
          </div>
        </div>
        <p style="font-size:11.5px;color:#374151;line-height:1.6;margin-bottom:10px">CoderPad is a real-time collaborative coding interview and assessment platform supporting 30-plus languages, primarily serving enterprise clients.</p>
        <div style="display:flex;gap:12px;font-size:10.5px;color:var(--muted);padding-top:8px;border-top:1px solid var(--border)">
          <span>ARR: <strong style="color:var(--navy)">&euro;18M</strong></span>
          <span>Raised: <strong style="color:var(--navy)">&euro;31M</strong></span>
          <span>Employees: <strong style="color:var(--navy)">110</strong></span>
        </div>
      </div>

    </div>
  </div>'''

html = re.sub(
    r'<div class="callout">\s*<strong>Primary Recommendations[^<]*</strong>.*?</div>',
    top3, html, count=1, flags=re.DOTALL
)

# ── 3. ADD EMPLOYEES TO TARGET LIST STAT BOXES ───────────────────────────────
replacements = [
    ('ARR: $10M<br>Raised: $28.6M',      'ARR: $10M<br>Raised: $28.6M<br>Emp: 50'),
    ('ARR: $500K<br>Raised: $5.5M',       'ARR: $500K<br>Raised: $5.5M<br>Emp: 67'),
    ('ARR: \u20ac18M<br>Raised: \u20ac31M','ARR: \u20ac18M<br>Raised: \u20ac31M<br>Emp: 110'),
    ('ARR: \u20ac1M<br>Raised: \u20ac2M', 'ARR: \u20ac1M<br>Raised: \u20ac2M<br>Emp: N/A'),
    ('ARR: $1.9M<br>Raised: $540K',       'ARR: $1.9M<br>Raised: $540K<br>Emp: N/A'),
    ('ARR: $9M<br>Raised: N/A',           'ARR: $9M<br>Raised: N/A<br>Emp: N/A'),
    ('ARR: $4M<br>Raised: $770K',         'ARR: $4M<br>Raised: $770K<br>Emp: N/A'),
    ('ARR: N/A<br>Raised: $0',            'ARR: N/A<br>Raised: $0<br>Emp: N/A'),
    ('ARR: \u20ac2M<br>Raised: \u20ac2M', 'ARR: \u20ac2M<br>Raised: \u20ac2M<br>Emp: N/A'),
]
# Handle the two N/A<br>N/A entries (Qualified.io and Futurice) — replace both
html = html.replace('ARR: N/A<br>Raised: N/A', 'ARR: N/A<br>Raised: N/A<br>Emp: N/A')
for old, new in replacements:
    html = html.replace(old, new)

# ── 4. ADD EMPLOYEES TO s4 TOP3 CARD HEADERS ─────────────────────────────────
html = html.replace(
    'Germany \u00b7  \u00b7 Raised $28.6m',
    'Germany \u00b7 Seed \u00b7 50 employees \u00b7 Raised $28.6m'
)
html = html.replace(
    'United Kingdom \u00b7  \u00b7 Raised $5.5m',
    'United Kingdom \u00b7 Seed \u00b7 67 employees \u00b7 Raised $5.5m'
)
html = html.replace(
    'France \u00b7 Series B \u00b7 Raised \u20ac31M',
    'France \u00b7 Series B \u00b7 110 employees \u00b7 Raised \u20ac31M'
)

out = Path("/Users/sohail/Documents/Claude VS/strategic_fit_engine/output/report.html")
out.write_text(html, encoding="utf-8")
print(f"Done — {len(html):,} chars written to {out}")
