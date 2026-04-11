"""
Strategic Fit Engine — Web Interface

Serves a form where the user inputs buyer, sector, and geography.
Runs the 4-step pipeline in a background thread and streams
real-time progress to the browser via Server-Sent Events (SSE).
When complete, the report opens automatically.

Run:
    cd "/Users/sohail/Documents/Claude VS"
    ANTHROPIC_API_KEY=sk-ant-... .venv/bin/python -m strategic_fit_engine.app

Open: http://localhost:5000
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, request, send_file

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

app = Flask(__name__)


def _h(v: str) -> str:
    """HTML-escape a value."""
    return (str(v)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))
BASE = Path(__file__).parent

# ---------------------------------------------------------------------------
# Job state (single-user — one analysis at a time)
# ---------------------------------------------------------------------------

_job: dict = {
    "running": False,
    "messages": [],
    "current_step": 0,
    "done": False,
    "error": None,
}
_lock = threading.Lock()


class _Capture:
    """Redirects print() calls from step modules into the job message list."""
    def write(self, text: str) -> None:
        if text.strip():
            _add("log", text.strip())
    def flush(self) -> None:
        pass


def _add(msg_type: str, text: str, step: int = None) -> None:
    with _lock:
        if step is not None:
            _job["current_step"] = step
        _job["messages"].append({
            "type": msg_type,
            "text": text,
            "step": _job["current_step"],
        })


def _run_pipeline(buyer: str, sector: str, geography: str) -> None:
    """Runs all 4 steps sequentially in a background thread."""
    # Re-load .env inside the thread to guarantee env vars are set
    _env_path = Path(__file__).parent.parent / ".env"
    if _env_path.exists():
        for line in _env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ[k.strip()] = v.strip()

    old_stdout = sys.stdout
    sys.stdout = _Capture()
    try:
        _add("info", f"Pipeline starting: {buyer} · {sector} · {geography}")

        (BASE / "data").mkdir(exist_ok=True)
        (BASE / "output").mkdir(exist_ok=True)

        # ── Step 1 ──────────────────────────────────────────────────────
        _add("step", "Step 1 / 4 — Buyer DNA Analysis", step=1)
        from strategic_fit_engine import step1_buyer_dna
        bp = step1_buyer_dna.run(buyer, sector)
        n_acq = len(bp.get("acquisitions", []))
        n_crit = len(bp.get("scoring_criteria", []))
        _add("done", f"✓ Step 1 complete — {n_acq} acquisitions researched, {n_crit} buyer-specific criteria derived")

        # ── Step 2 ──────────────────────────────────────────────────────
        _add("step", "Step 2 / 4 — Target Company Discovery", step=2)
        from strategic_fit_engine import step2_discovery
        tr = step2_discovery.run(sector, geography)
        n_tgt = len(tr.get("targets", []))
        _add("done", f"✓ Step 2 complete — {n_tgt} companies discovered")
        for t in tr.get("targets", [])[:5]:
            _add("log", f"   · {t['name']} ({t.get('country','')}) — {t.get('funding_stage','')}")
        if n_tgt > 5:
            _add("log", f"   · ... and {n_tgt - 5} more")

        # ── Step 3 ──────────────────────────────────────────────────────
        _add("step", "Step 3 / 4 — Strategic Fit Scoring (7 criteria, 2 batches)", step=3)
        from strategic_fit_engine import step3_scoring
        scored = step3_scoring.run(bp, tr)
        scored["sector"] = sector
        scored["geography"] = geography
        # Persist updated file (with sector/geography keys)
        with open(BASE / "data" / "targets_scored.json", "w", encoding="utf-8") as f:
            json.dump(scored, f, indent=2, ensure_ascii=False)
        top = scored["targets"][0] if scored.get("targets") else {}
        _add("done", f"✓ Step 3 complete — Top target: {top.get('name','?')} ({top.get('total_score','?')}/{top.get('max_score','?')})")
        for t in scored.get("targets", [])[:3]:
            _add("log", f"   #{t['rank']}: {t['name']} — {t['total_score']}/{t['max_score']}")

        # ── Step 4 ──────────────────────────────────────────────────────
        _add("step", "Step 4 / 4 — Generating Interactive Dashboard", step=4)
        from strategic_fit_engine import step4_output
        step4_output.run(bp, scored)
        _add("done", "✓ Step 4 complete — Dashboard saved to output/report.html")

        with _lock:
            _job["done"] = True
        _add("complete", "Analysis complete! Your report is ready.")

    except Exception as e:
        tb = traceback.format_exc()
        _add("error", f"Error: {e}")
        _add("error", tb)
        with _lock:
            _job["error"] = str(e)
    finally:
        sys.stdout = old_stdout
        with _lock:
            _job["running"] = False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return LANDING_HTML


@app.route("/run", methods=["POST"])
def run_analysis():
    global _job
    with _lock:
        if _job["running"]:
            return "An analysis is already running. Please wait.", 409
        buyer     = request.form.get("buyer", "Salesforce").strip()
        sector    = request.form.get("sector", "European Healthcare Vertical SaaS").strip()
        geography = request.form.get("geography", "UK/Germany/France/Nordics/Netherlands").strip()
        _job = {"running": True, "messages": [], "current_step": 0, "done": False, "error": None}

    t = threading.Thread(target=_run_pipeline, args=(buyer, sector, geography), daemon=True)
    t.start()
    return _progress_html(buyer, sector, geography)


@app.route("/stream")
def stream():
    def generate():
        last = 0
        while True:
            with _lock:
                msgs  = list(_job["messages"])
                done  = _job["done"]
                error = _job.get("error")

            for msg in msgs[last:]:
                yield f"data: {json.dumps(msg)}\n\n"
            last = len(msgs)

            if done or error:
                yield f"data: {json.dumps({'type': 'end', 'error': error})}\n\n"
                break
            time.sleep(0.25)

    resp = Response(generate(), mimetype="text/event-stream")
    resp.headers["Cache-Control"]      = "no-cache"
    resp.headers["X-Accel-Buffering"]  = "no"
    resp.headers["Connection"]         = "keep-alive"
    return resp


@app.route("/report")
def view_report():
    path = BASE / "output" / "report.html"
    if path.exists():
        return send_file(str(path.resolve()))
    return "Report not yet generated. Run an analysis first.", 404


# ---------------------------------------------------------------------------
# Landing page HTML
# ---------------------------------------------------------------------------

LANDING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Strategic Fit Engine — GP Bullhound</title>
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:'Segoe UI','Helvetica Neue',Arial,sans-serif;
      background:#0B1C3D;min-height:100vh;display:flex;flex-direction:column}
    header{padding:28px 48px;display:flex;justify-content:space-between;align-items:center;
      border-bottom:1px solid rgba(255,255,255,.08)}
    .brand{font-size:22px;font-weight:700;color:#C9A84C;letter-spacing:.5px}
    .brand-sub{font-size:12px;color:#7a8aab;margin-top:3px}
    .header-right{text-align:right;font-size:12px;color:#7a8aab}

    main{flex:1;display:flex;align-items:center;justify-content:center;padding:40px 20px}
    .container{width:100%;max-width:680px}

    h1{font-size:28px;font-weight:700;color:#fff;margin-bottom:8px}
    .subtitle{font-size:14px;color:#7a8aab;margin-bottom:36px;line-height:1.6}
    .subtitle strong{color:#C9A84C}

    .card{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.09);
      border-radius:12px;padding:36px;backdrop-filter:blur(8px)}

    .field{margin-bottom:22px}
    label{display:block;font-size:12px;font-weight:700;letter-spacing:.6px;
      text-transform:uppercase;color:#aab3c7;margin-bottom:8px}
    input,select{width:100%;border:1px solid rgba(255,255,255,.15);border-radius:7px;
      padding:13px 16px;font-size:14px;background:rgba(255,255,255,.06);
      color:#fff;outline:none;transition:border .2s}
    input::placeholder{color:#4a5568}
    input:focus,select:focus{border-color:#C9A84C;background:rgba(255,255,255,.09)}

    .hint{font-size:11px;color:#5a6a8a;margin-top:6px}
    .presets{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:24px}
    .preset-btn{background:rgba(201,168,76,.12);border:1px solid rgba(201,168,76,.3);
      color:#C9A84C;font-size:11px;font-weight:600;padding:6px 12px;border-radius:20px;
      cursor:pointer;transition:all .2s}
    .preset-btn:hover{background:rgba(201,168,76,.25);border-color:#C9A84C}

    .submit-btn{width:100%;padding:16px;background:#C9A84C;color:#0B1C3D;
      font-size:15px;font-weight:700;border:none;border-radius:8px;
      cursor:pointer;letter-spacing:.3px;transition:all .2s;margin-top:8px}
    .submit-btn:hover{background:#b8973d;transform:translateY(-1px)}
    .submit-btn:active{transform:translateY(0)}
    .submit-btn:disabled{background:#4a5568;cursor:not-allowed;transform:none}

    .steps-preview{display:flex;gap:0;margin-bottom:32px;
      background:rgba(255,255,255,.03);border-radius:8px;overflow:hidden;
      border:1px solid rgba(255,255,255,.06)}
    .step-preview{flex:1;padding:14px 10px;text-align:center;
      border-right:1px solid rgba(255,255,255,.06);font-size:11px;color:#5a6a8a}
    .step-preview:last-child{border-right:none}
    .step-preview .num{font-size:16px;color:#C9A84C;font-weight:700;display:block;margin-bottom:3px}

    .existing-report{margin-top:16px;text-align:center}
    .existing-report a{color:#7a8aab;font-size:13px;text-decoration:none;
      padding:8px 16px;border:1px solid rgba(255,255,255,.08);border-radius:5px;
      display:inline-block;transition:all .2s}
    .existing-report a:hover{color:#C9A84C;border-color:#C9A84C}

    footer{padding:20px 48px;text-align:center;font-size:12px;color:#3a4a6a;
      border-top:1px solid rgba(255,255,255,.05)}
    footer strong{color:#C9A84C}
  </style>
</head>
<body>
<header>
  <div>
    <div class="brand">GP Bullhound</div>
    <div class="brand-sub">Technology Investment Banking &amp; Strategic Advisory</div>
  </div>
  <div class="header-right">Strategic Fit Engine v2<br>Powered by Claude Sonnet 4.6</div>
</header>

<main>
  <div class="container">
    <h1>M&amp;A Target Screening</h1>
    <p class="subtitle">
      Enter a <strong>strategic buyer</strong>, <strong>target sector</strong>, and <strong>geography</strong>.
      The engine will research the buyer's acquisition DNA, discover relevant targets,
      score them across 7 criteria, and generate a full interactive analyst report — in minutes.
    </p>

    <div class="steps-preview">
      <div class="step-preview"><span class="num">01</span>Buyer DNA</div>
      <div class="step-preview"><span class="num">02</span>Discovery</div>
      <div class="step-preview"><span class="num">03</span>Scoring</div>
      <div class="step-preview"><span class="num">04</span>Dashboard</div>
    </div>

    <div class="card">
      <p style="font-size:12px;color:#5a6a8a;margin-bottom:18px;font-weight:600;
        text-transform:uppercase;letter-spacing:.5px">Quick Presets</p>
      <div class="presets">
        <button class="preset-btn" onclick="preset('Salesforce','European Healthcare Vertical SaaS','UK/Germany/France/Nordics/Netherlands')">
          Salesforce × EU Health
        </button>
        <button class="preset-btn" onclick="preset('Microsoft','European FinTech SaaS','UK/Germany/Netherlands/Sweden')">
          Microsoft × EU FinTech
        </button>
        <button class="preset-btn" onclick="preset('ServiceNow','European HR Tech SaaS','UK/Germany/France')">
          ServiceNow × EU HR Tech
        </button>
        <button class="preset-btn" onclick="preset('Workday','European Payroll & Workforce SaaS','UK/Germany/Netherlands')">
          Workday × EU Payroll
        </button>
      </div>

      <form method="POST" action="/run" id="analysis-form" onsubmit="handleSubmit(event)">
        <div class="field">
          <label>Strategic Buyer</label>
          <input type="text" name="buyer" id="buyer"
            placeholder="e.g. Salesforce, Microsoft, ServiceNow..."
            value="Salesforce" required>
          <p class="hint">The acquiring company — the engine will research their M&amp;A history and derive a custom scoring rubric.</p>
        </div>
        <div class="field">
          <label>Target Sector</label>
          <input type="text" name="sector" id="sector"
            placeholder="e.g. European Healthcare Vertical SaaS..."
            value="European Healthcare Vertical SaaS" required>
          <p class="hint">Be specific — vertical SaaS, FinTech payments, HR Tech, etc.</p>
        </div>
        <div class="field">
          <label>Geography / Region</label>
          <input type="text" name="geography" id="geography"
            placeholder="e.g. UK/Germany/France/Nordics..."
            value="UK/Germany/France/Nordics/Netherlands" required>
          <p class="hint">Countries or regions to screen. Separate with / or commas.</p>
        </div>
        <button type="submit" class="submit-btn" id="submit-btn">
          Run Analysis →
        </button>
      </form>
    </div>

    <div class="existing-report">
      <a href="/report" target="_blank">↗ View last generated report</a>
    </div>
  </div>
</main>

<footer>
  <strong>Strategic Fit Engine</strong> — Buyer-first M&amp;A screening powered by Claude AI
</footer>

<script>
function preset(buyer, sector, geo) {
  document.getElementById('buyer').value = buyer;
  document.getElementById('sector').value = sector;
  document.getElementById('geography').value = geo;
}
function handleSubmit(e) {
  document.getElementById('submit-btn').disabled = true;
  document.getElementById('submit-btn').textContent = 'Starting analysis...';
}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Progress page HTML (returned after form submit)
# ---------------------------------------------------------------------------

def _progress_html(buyer: str, sector: str, geography: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Running Analysis — GP Bullhound</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:'Segoe UI','Helvetica Neue',Arial,sans-serif;
      background:#0B1C3D;min-height:100vh;display:flex;flex-direction:column;color:#fff}}
    header{{padding:22px 48px;display:flex;justify-content:space-between;align-items:center;
      border-bottom:1px solid rgba(255,255,255,.08)}}
    .brand{{font-size:20px;font-weight:700;color:#C9A84C}}
    .brand-sub{{font-size:11px;color:#7a8aab;margin-top:2px}}

    main{{flex:1;padding:48px 20px;display:flex;justify-content:center}}
    .container{{width:100%;max-width:720px}}

    h2{{font-size:22px;font-weight:700;color:#fff;margin-bottom:4px}}
    .params{{font-size:13px;color:#7a8aab;margin-bottom:32px}}
    .params strong{{color:#C9A84C}}

    /* Steps */
    .steps{{display:flex;gap:12px;margin-bottom:36px;flex-wrap:wrap}}
    .step{{flex:1;min-width:140px;background:rgba(255,255,255,.04);
      border:1px solid rgba(255,255,255,.08);border-radius:8px;padding:14px 16px}}
    .step.active{{border-color:#C9A84C;background:rgba(201,168,76,.08)}}
    .step.complete{{border-color:#2E7D32;background:rgba(46,125,50,.08)}}
    .step.error{{border-color:#C62828;background:rgba(198,40,40,.08)}}
    .step-num{{font-size:10px;font-weight:700;letter-spacing:1px;
      text-transform:uppercase;color:#5a6a8a;margin-bottom:4px}}
    .step.active .step-num{{color:#C9A84C}}
    .step.complete .step-num{{color:#4CAF50}}
    .step-label{{font-size:13px;font-weight:600;color:#aab3c7}}
    .step.active .step-label{{color:#fff}}
    .step-icon{{float:right;font-size:18px;margin-top:-2px}}

    /* Progress bar */
    .progress-track{{background:rgba(255,255,255,.08);border-radius:4px;
      height:6px;margin-bottom:28px;overflow:hidden}}
    .progress-fill{{height:6px;background:linear-gradient(90deg,#C9A84C,#e8c96d);
      border-radius:4px;width:0%;transition:width .6s ease}}

    /* Log */
    .log-header{{font-size:11px;font-weight:700;letter-spacing:.6px;
      text-transform:uppercase;color:#5a6a8a;margin-bottom:10px}}
    .log{{background:rgba(0,0,0,.4);border:1px solid rgba(255,255,255,.06);
      border-radius:8px;padding:20px;height:320px;overflow-y:auto;
      font-family:'Courier New',monospace;font-size:12px;line-height:1.8}}
    .log .msg-log{{color:#8a9ab8}}
    .log .msg-info{{color:#aab3c7}}
    .log .msg-step{{color:#C9A84C;font-weight:700}}
    .log .msg-done{{color:#66BB6A;font-weight:600}}
    .log .msg-error{{color:#EF5350}}
    .log .msg-complete{{color:#C9A84C;font-weight:700;font-size:13px}}

    /* Result */
    .result-box{{margin-top:28px;padding:24px;border-radius:8px;
      background:rgba(46,125,50,.12);border:1px solid rgba(46,125,50,.4);
      text-align:center;display:none}}
    .result-box.show{{display:block}}
    .open-btn{{display:inline-block;margin-top:12px;padding:14px 32px;
      background:#C9A84C;color:#0B1C3D;font-size:15px;font-weight:700;
      border-radius:7px;text-decoration:none;transition:all .2s}}
    .open-btn:hover{{background:#b8973d;transform:translateY(-1px)}}
    .new-btn{{display:inline-block;margin:12px 0 0 14px;padding:14px 24px;
      background:transparent;color:#aab3c7;font-size:14px;font-weight:600;
      border:1px solid rgba(255,255,255,.15);border-radius:7px;
      text-decoration:none;transition:all .2s}}
    .new-btn:hover{{border-color:#fff;color:#fff}}

    .error-box{{margin-top:28px;padding:20px;border-radius:8px;
      background:rgba(198,40,40,.1);border:1px solid rgba(198,40,40,.3);display:none}}
    .error-box.show{{display:block}}

    /* Spinner */
    @keyframes spin{{to{{transform:rotate(360deg)}}}}
    .spinner{{display:inline-block;width:16px;height:16px;
      border:2px solid rgba(201,168,76,.3);border-top-color:#C9A84C;
      border-radius:50%;animation:spin .8s linear infinite;vertical-align:middle;
      margin-right:6px}}
    @keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}
    .pulsing{{animation:pulse 1.5s ease-in-out infinite}}
  </style>
</head>
<body>
<header>
  <div>
    <div class="brand">GP Bullhound</div>
    <div class="brand-sub">Strategic Fit Engine</div>
  </div>
  <a href="/" style="font-size:12px;color:#5a6a8a;text-decoration:none">← New Analysis</a>
</header>

<main>
  <div class="container">
    <h2><span class="spinner pulsing"></span>Running Analysis</h2>
    <div class="params">
      <strong>{_h(buyer)}</strong> &nbsp;·&nbsp;
      {_h(sector)} &nbsp;·&nbsp;
      {_h(geography)}
    </div>

    <div class="steps">
      <div class="step" id="step1">
        <div class="step-num">Step 1</div>
        <div class="step-label">Buyer DNA</div>
        <span class="step-icon" id="icon1">○</span>
      </div>
      <div class="step" id="step2">
        <div class="step-num">Step 2</div>
        <div class="step-label">Discovery</div>
        <span class="step-icon" id="icon2">○</span>
      </div>
      <div class="step" id="step3">
        <div class="step-num">Step 3</div>
        <div class="step-label">Scoring</div>
        <span class="step-icon" id="icon3">○</span>
      </div>
      <div class="step" id="step4">
        <div class="step-num">Step 4</div>
        <div class="step-label">Dashboard</div>
        <span class="step-icon" id="icon4">○</span>
      </div>
    </div>

    <div class="progress-track">
      <div class="progress-fill" id="progress-fill"></div>
    </div>

    <div class="log-header">Live Output</div>
    <div class="log" id="log"></div>

    <div class="result-box" id="result-box">
      <div style="font-size:18px;font-weight:700;color:#fff;margin-bottom:4px">
        ✓ Analysis Complete
      </div>
      <div style="font-size:13px;color:#aab3c7;margin-bottom:4px">
        Your report is ready. Opens in a new tab.
      </div>
      <a href="/report" target="_blank" class="open-btn">Open Report →</a>
      <a href="/" class="new-btn">Run Another</a>
    </div>

    <div class="error-box" id="error-box">
      <div style="font-size:15px;font-weight:700;color:#EF5350;margin-bottom:8px">
        ✗ Analysis Failed
      </div>
      <div id="error-msg" style="font-size:13px;color:#aab3c7;margin-bottom:12px"></div>
      <a href="/" style="color:#C9A84C;font-size:13px">← Try again</a>
    </div>
  </div>
</main>

<script>
const log = document.getElementById('log');
const progress = document.getElementById('progress-fill');

function appendLog(msg) {{
  const div = document.createElement('div');
  div.className = 'msg-' + msg.type;
  div.textContent = msg.text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}}

function setStep(n) {{
  [1,2,3,4].forEach(i => {{
    const el = document.getElementById('step' + i);
    const icon = document.getElementById('icon' + i);
    if (i < n) {{
      el.className = 'step complete';
      icon.textContent = '✓';
    }} else if (i === n) {{
      el.className = 'step active';
      icon.textContent = '⟳';
    }} else {{
      el.className = 'step';
      icon.textContent = '○';
    }}
  }});
  progress.style.width = ((n - 1) / 4 * 100) + '%';
}}

const src = new EventSource('/stream');
src.onmessage = function(e) {{
  const msg = JSON.parse(e.data);

  if (msg.type === 'end') {{
    src.close();
    if (msg.error) {{
      document.getElementById('error-msg').textContent = msg.error;
      document.getElementById('error-box').classList.add('show');
      [1,2,3,4].forEach(i => {{
        document.getElementById('step'+i).classList.remove('active');
      }});
    }} else {{
      progress.style.width = '100%';
      [1,2,3,4].forEach(i => {{
        document.getElementById('step'+i).className = 'step complete';
        document.getElementById('icon'+i).textContent = '✓';
      }});
      document.getElementById('result-box').classList.add('show');
      // Auto-open report after brief delay
      setTimeout(() => window.open('/report', '_blank'), 1200);
    }}
    return;
  }}

  if (msg.step && msg.step > 0) setStep(msg.step);
  appendLog(msg);
}};

src.onerror = function() {{
  src.close();
  appendLog({{type:'error', text:'Connection to server lost. Check terminal for errors.'}});
}};
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("\n" + "="*60)
    print("  Strategic Fit Engine — Web Interface")
    print("="*60)
    print(f"\n  Open http://localhost:{port} in your browser\n")
    print("  Press Ctrl+C to stop\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
