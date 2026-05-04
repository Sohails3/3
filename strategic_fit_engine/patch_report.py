"""Apply 4 formatting changes to Duolingo v6 report.html"""
import sys, re
from pathlib import Path

src = Path("/Users/sohail/Documents/Claude VS/strategic_fit_engine/output/report_apple_backup.html")
# We'll read from the v6 content passed via stdin
html = sys.stdin.read()

# ── 1. ADD EXCEL DOWNLOAD BUTTON ─────────────────────────────────────────────
excel_btn = '''  <a class="pptx-btn" href="/download/excel" download
    style="background:#1D6F42">
    <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/>
    </svg>
    Download Excel
  </a>
  <button class="pdf-btn"'''

html = html.replace(
    '  <button class="pdf-btn"',
    excel_btn,
    1
)

# ── 2. REPLACE CALLOUT WITH TOP 3 CARDS ──────────────────────────────────────
top3_cards = '''
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
        <p style="font-size:11.5px;color:#374151;line-height:1.6;margin-bottom:10px">Mimo is a mobile-first, bite-sized coding education app teaching Python, JavaScript, and SQL through gamified lessons, with 15 million downloads representing a dominant presence in the mobile-native learning market.</p>
        <div style="display:flex;gap:16px;font-size:10.5px;color:var(--muted);padding-top:8px;border-top:1px solid var(--border)">
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
        <p style="font-size:11.5px;color:#374151;line-height:1.6;margin-bottom:10px">Enki is an AI-driven daily coding skill-building platform delivering bite-sized mobile lessons for working professionals, powered by GPT-4 personalised mentoring and adaptive skill paths.</p>
        <div style="display:flex;gap:16px;font-size:10.5px;color:var(--muted);padding-top:8px;border-top:1px solid var(--border)">
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
        <p style="font-size:11.5px;color:#374151;line-height:1.6;margin-bottom:10px">CoderPad is a real-time collaborative coding interview and technical assessment platform supporting 30-plus languages, primarily serving enterprise clients for technical hiring and recruitment.</p>
        <div style="display:flex;gap:16px;font-size:10.5px;color:var(--muted);padding-top:8px;border-top:1px solid var(--border)">
          <span>ARR: <strong style="color:var(--navy)">&euro;18M</strong></span>
          <span>Raised: <strong style="color:var(--navy)">&euro;31M</strong></span>
          <span>Employees: <strong style="color:var(--navy)">110</strong></span>
        </div>
      </div>
    </div>
  </div>'''

# Replace the callout div (Primary Recommendations line)
html = re.sub(
    r'<div class="callout">\s*<strong>Primary Recommendations[^<]*</strong>[^<]*(?:<strong[^>]*>[^<]*</strong>[^<]*)*</div>',
    top3_cards,
    html,
    count=1,
    flags=re.DOTALL
)

# ── 3. ADD EMPLOYEES TO TARGET LIST STATS (s3) ───────────────────────────────
html = html.replace(
    '<div style="min-width:90px;text-align:right;font-size:11px;color:var(--muted);white-space:nowrap">ARR: $10M<br>Raised: $28.6M</div>',
    '<div style="min-width:90px;text-align:right;font-size:11px;color:var(--muted);white-space:nowrap">ARR: $10M<br>Raised: $28.6M<br>Emp: 50</div>'
)
html = html.replace(
    '<div style="min-width:90px;text-align:right;font-size:11px;color:var(--muted);white-space:nowrap">ARR: $500K<br>Raised: $5.5M</div>',
    '<div style="min-width:90px;text-align:right;font-size:11px;color:var(--muted);white-space:nowrap">ARR: $500K<br>Raised: $5.5M<br>Emp: 67</div>'
)
html = html.replace(
    '<div style="min-width:90px;text-align:right;font-size:11px;color:var(--muted);white-space:nowrap">ARR: \u20ac18M<br>Raised: \u20ac31M</div>',
    '<div style="min-width:90px;text-align:right;font-size:11px;color:var(--muted);white-space:nowrap">ARR: \u20ac18M<br>Raised: \u20ac31M<br>Emp: 110</div>'
)
html = html.replace(
    '<div style="min-width:90px;text-align:right;font-size:11px;color:var(--muted);white-space:nowrap">ARR: \u20ac1M<br>Raised: \u20ac2M</div>',
    '<div style="min-width:90px;text-align:right;font-size:11px;color:var(--muted);white-space:nowrap">ARR: \u20ac1M<br>Raised: \u20ac2M<br>Emp: N/A</div>'
)
html = html.replace(
    '<div style="min-width:90px;text-align:right;font-size:11px;color:var(--muted);white-space:nowrap">ARR: N/A<br>Raised: N/A</div>',
    '<div style="min-width:90px;text-align:right;font-size:11px;color:var(--muted);white-space:nowrap">ARR: N/A<br>Raised: N/A<br>Emp: N/A</div>',
)
html = html.replace(
    '<div style="min-width:90px;text-align:right;font-size:11px;color:var(--muted);white-space:nowrap">ARR: $1.9M<br>Raised: $540K</div>',
    '<div style="min-width:90px;text-align:right;font-size:11px;color:var(--muted);white-space:nowrap">ARR: $1.9M<br>Raised: $540K<br>Emp: N/A</div>'
)
html = html.replace(
    '<div style="min-width:90px;text-align:right;font-size:11px;color:var(--muted);white-space:nowrap">ARR: $9M<br>Raised: N/A</div>',
    '<div style="min-width:90px;text-align:right;font-size:11px;color:var(--muted);white-space:nowrap">ARR: $9M<br>Raised: N/A<br>Emp: N/A</div>'
)
html = html.replace(
    '<div style="min-width:90px;text-align:right;font-size:11px;color:var(--muted);white-space:nowrap">ARR: $4M<br>Raised: $770K</div>',
    '<div style="min-width:90px;text-align:right;font-size:11px;color:var(--muted);white-space:nowrap">ARR: $4M<br>Raised: $770K<br>Emp: N/A</div>'
)
html = html.replace(
    '<div style="min-width:90px;text-align:right;font-size:11px;color:var(--muted);white-space:nowrap">ARR: N/A<br>Raised: $0</div>',
    '<div style="min-width:90px;text-align:right;font-size:11px;color:var(--muted);white-space:nowrap">ARR: N/A<br>Raised: $0<br>Emp: N/A</div>'
)
html = html.replace(
    '<div style="min-width:90px;text-align:right;font-size:11px;color:var(--muted);white-space:nowrap">ARR: \u20ac2M<br>Raised: \u20ac2M</div>',
    '<div style="min-width:90px;text-align:right;font-size:11px;color:var(--muted);white-space:nowrap">ARR: \u20ac2M<br>Raised: \u20ac2M<br>Emp: N/A</div>'
)

# ── 4. ADD EMPLOYEES TO s4 TOP3 HEADER LINES ─────────────────────────────────
html = html.replace(
    'Germany &middot;  &middot; Raised $28.6m',
    'Germany &middot; Seed &middot; Raised $28.6m &middot; 50 employees'
)
html = html.replace(
    'United Kingdom &middot;  &middot; Raised $5.5m',
    'United Kingdom &middot; Seed &middot; Raised $5.5m &middot; 67 employees'
)
html = html.replace(
    'France &middot; Series B &middot; Raised \u20ac31M',
    'France &middot; Series B &middot; Raised \u20ac31M &middot; 110 employees'
)

out = Path("/Users/sohail/Documents/Claude VS/strategic_fit_engine/output/report.html")
out.write_text(html, encoding="utf-8")
print(f"Written {len(html):,} chars to {out}")
