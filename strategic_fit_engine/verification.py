"""
Step 2.5 — Data Quality & Verification

Cross-checks the Step-2 longlist against live sources to close the
"Data Quality & Verification" gap: discovery produces companies and financials
from the model's training knowledge, which must be verified before a client-ready
document.

Per surfaced company this step:
  1. Gathers live evidence from a provider (real company? funding / revenue / employees / recent news)
  2. Has Claude judge whether the evidence genuinely matches the CLAIMED company
     (name + sector + geography) — a fuzzy or different company does NOT count
  3. Cross-checks the claimed figures and assigns confidence + a verification flag
     that Steps 3-4 surface in the report.

Providers (auto-selected, prefer Exa):
  • exa     — Exa web-search REST API. Set EXA_API_KEY. Simple x-api-key auth, no OAuth;
              works fine from the deployed server. RECOMMENDED.
  • bigdata — Bigdata.com via the Anthropic MCP connector. Set BIGDATA_MCP_URL + BIGDATA_MCP_TOKEN.
              (Bigdata's OAuth-only access usually can't issue a server token — see notes.)

Until a provider is configured this module is a safe no-op (targets pass through
flagged "skipped"), so the pipeline keeps working without it.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

import anthropic
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

MODEL = "claude-sonnet-4-6"
MCP_BETA = "mcp-client-2025-04-04"

# --- Provider config -------------------------------------------------------
EXA_API_KEY = os.environ.get("EXA_API_KEY", "").strip()
EXA_SEARCH_URL = os.environ.get("EXA_SEARCH_URL", "https://api.exa.ai/search").strip()

BIGDATA_MCP_URL = os.environ.get("BIGDATA_MCP_URL", "").strip()
BIGDATA_MCP_TOKEN = os.environ.get("BIGDATA_MCP_TOKEN", "").strip()

# "auto" (default) picks exa if its key is set, else bigdata. Force with VERIFICATION_PROVIDER.
_PROVIDER = os.environ.get("VERIFICATION_PROVIDER", "auto").strip().lower()
# "auto"/"on" run when a provider exists; "off"/"0"/"false" force-disable.
_FLAG = os.environ.get("VERIFICATION_ENABLED", "auto").strip().lower()

# Cap companies cross-checked per run, to bound cost/latency.
MAX_VERIFY = int(os.environ.get("VERIFICATION_MAX", "12"))

_CLAIM_FIELDS = ["country", "funding_stage", "arr_usd_m",
                 "total_raised_usd_m", "employees", "website"]


def active_provider() -> Optional[str]:
    """Which provider will run, or None if disabled/unconfigured."""
    if _FLAG in ("0", "false", "off", "no"):
        return None
    if _PROVIDER == "exa":
        return "exa" if EXA_API_KEY else None
    if _PROVIDER == "bigdata":
        return "bigdata" if (BIGDATA_MCP_URL and BIGDATA_MCP_TOKEN) else None
    # auto — prefer Exa
    if EXA_API_KEY:
        return "exa"
    if BIGDATA_MCP_URL and BIGDATA_MCP_TOKEN:
        return "bigdata"
    return None


def is_enabled() -> bool:
    return active_provider() is not None


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _extract_json(raw: str) -> Dict:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"JSON parse failed.\nRaw (first 800 chars):\n{raw[:800]}")


def _with_retry(fn, retries: int = 4):
    last_exc = None
    for attempt in range(retries):
        try:
            return fn()
        except anthropic.RateLimitError as e:
            last_exc = e
            wait = 30 * (2 ** attempt)
            print(f"  [Rate limit] Waiting {wait}s before retry {attempt + 1}/{retries}...")
            time.sleep(wait)
        except Exception as e:
            last_exc = e
            if attempt == retries - 1:
                raise
            wait = 5 * (2 ** attempt)
            print(f"  [Verify error: {type(e).__name__}: {e}] Retrying in {wait}s...")
            time.sleep(wait)
    raise RuntimeError(f"Max retries exceeded. Last error: {last_exc}")


# ---------------------------------------------------------------------------
# Evidence gathering
# ---------------------------------------------------------------------------

def _exa_search(query: str, n: int = 5) -> List[Dict]:
    """One Exa web search → list of {title, url, published, text}."""
    resp = requests.post(
        EXA_SEARCH_URL,
        headers={"x-api-key": EXA_API_KEY, "Content-Type": "application/json"},
        json={"query": query, "numResults": n, "type": "auto",
              "contents": {"text": {"maxCharacters": 700}, "highlights": True}},
        timeout=30,
    )
    resp.raise_for_status()
    out = []
    for r in resp.json().get("results", []):
        text = " ".join(r.get("highlights", []) or []) or (r.get("text", "") or "")
        out.append({"title": r.get("title"), "url": r.get("url"),
                    "published": r.get("publishedDate"), "text": text[:700]})
    return out


def _gather_exa(subset: List[Dict], sector: str, geography: str) -> Dict[str, List[Dict]]:
    evidence: Dict[str, List[Dict]] = {}
    for t in subset:
        name = t.get("name", "")
        query = (f"{name} — {sector} company in {geography}: total funding raised, "
                 f"revenue or ARR, employee count, and recent news")
        try:
            evidence[name] = _exa_search(query, n=5)
        except Exception as e:
            print(f"  [Exa] search failed for {name}: {e}")
            evidence[name] = []
    return evidence


# ---------------------------------------------------------------------------
# Judgment
# ---------------------------------------------------------------------------

_JUDGE_PROMPT = """You are a data-verification analyst at an M&A advisory firm. A screening model produced \
the longlist below from its training knowledge — treat every figure as unverified. For each company you are \
given LIVE web evidence retrieved from Exa. Judge each company strictly.

CRITICAL: the evidence must genuinely correspond to the CLAIMED company — same name, operating in {sector}, \
based in/around {geography}. Web search always returns *something*; a different company with a similar name, \
or an unrelated result, does NOT confirm the claim. If nothing in the evidence clearly matches the claimed \
company, set exists=false and flag="not_found".

For each matched company, verify EACH financial metric against the evidence. For a metric, fill verified_figures \
ONLY if a source in the evidence corroborates it — give {{"value": <number in USD millions>, "source": "<source \
name or URL taken from the evidence>"}}. If no source corroborates a metric, set that metric to null — do NOT \
guess or copy the claimed figure. Note any material discrepancy (claimed vs sourced off ~15%+, or wrong \
stage/country) in discrepancies.

Assign:
  - confidence: "high" (clearly the right company AND figures corroborated), "medium" (right company but \
figures unconfirmed/approximate), "low" (weak/ambiguous evidence).
  - flag: "verified" | "partial" | "unverified" | "not_found".

DATA (claims + Exa evidence):
{bundle}

Return ONLY raw JSON — no markdown, no preamble. Start with {{ and end with }}:
{{
  "results": [
    {{
      "name": "<exact company name as given>",
      "exists": true,
      "confidence": "high|medium|low",
      "flag": "verified|partial|unverified|not_found",
      "verified_figures": {{
        "arr_or_revenue_usd_m": {{"value": 30, "source": "businesswire.com/..."}},
        "total_raised_or_fundsize_usd_m": null,
        "employees": {{"value": 345, "source": "linkedin.com/..."}},
        "market_cap_usd_m": null,
        "cash_usd_m": null
      }},
      "discrepancies": ["claimed ARR $50m vs sources ~$30m"],
      "source": "Exa",
      "notes": "one short sentence with the strongest corroborating or disconfirming fact"
    }}
  ]
}}"""


def _judge_with_claude(client: anthropic.Anthropic, sector: str, geography: str,
                       claims: List[Dict], evidence: Dict[str, List[Dict]]) -> Dict:
    bundle = json.dumps({"companies": [{"claim": c, "evidence": evidence.get(c["name"], [])}
                                       for c in claims]}, indent=2, ensure_ascii=False)
    prompt = _JUDGE_PROMPT.format(sector=sector, geography=geography, bundle=bundle)
    raw = _with_retry(lambda: "\n".join(
        b.text for b in client.messages.create(
            model=MODEL, max_tokens=8000,
            messages=[{"role": "user", "content": prompt}],
        ).content if hasattr(b, "text")))
    return _extract_json(raw)


# --- Bigdata.com MCP-connector path (fallback provider) --------------------

_BIGDATA_PROMPT = """You are a data-verification analyst. You have Bigdata.com tools via MCP \
(find_securities, bigdata_company_tearsheet, bigdata_search). Verify each company below: resolve it with \
find_securities (no resolution → exists=false, flag="not_found"); for PUBLIC pull a tearsheet, for PRIVATE \
use metadata + one search; cross-check claimed figures. Be skeptical — a plausible name is not proof. \
Sector {sector}, geography {geography}.

Companies:
{claims}

Return ONLY raw JSON, start with {{ end with }}:
{{"results":[{{"name":"<exact>","exists":true,"confidence":"high|medium|low","flag":"verified|partial|unverified|not_found","verified_figures":{{"revenue_or_arr_usd_m":null,"total_raised_usd_m":null,"employees":null}},"discrepancies":[],"source":"Bigdata.com","notes":""}}]}}"""


def _judge_with_bigdata(client: anthropic.Anthropic, sector: str, geography: str,
                        claims: List[Dict]) -> Dict:
    prompt = _BIGDATA_PROMPT.format(
        sector=sector, geography=geography,
        claims=json.dumps(claims, indent=2, ensure_ascii=False))
    raw = _with_retry(lambda: "\n".join(
        b.text for b in client.beta.messages.create(
            model=MODEL, max_tokens=8000,
            messages=[{"role": "user", "content": prompt}],
            mcp_servers=[{"type": "url", "url": BIGDATA_MCP_URL,
                          "name": "bigdata", "authorization_token": BIGDATA_MCP_TOKEN}],
            betas=[MCP_BETA],
        ).content if getattr(b, "type", None) == "text"))
    return _extract_json(raw)


# ---------------------------------------------------------------------------
# Per-metric reconciliation — correct to source, or mark unverified
# ---------------------------------------------------------------------------

# metric key -> (target field, verified_figures key)
_METRIC_MAP = {
    "arr":        ("arr_usd_m",          "arr_or_revenue_usd_m"),
    "raised":     ("total_raised_usd_m", "total_raised_or_fundsize_usd_m"),
    "employees":  ("employees",          "employees"),
    "market_cap": ("market_cap_usd_m",   "market_cap_usd_m"),
    "cash":       ("cash_usd_m",         "cash_usd_m"),
}
_MISSING = (None, "", "Not publicly available", "N/A")


def _to_num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _unverified_metrics(t: Dict) -> Dict:
    """Mark every present financial figure as unverified (used when no verdict came back)."""
    out = {}
    for key, (field, _) in _METRIC_MAP.items():
        if t.get(field) not in _MISSING:
            cv = _to_num(t.get(field))
            out[key] = {"status": "unverified", "source": None, "original": cv, "value": cv}
    return out


def _reconcile_metrics(t: Dict, verdict: Dict) -> Dict:
    """Per metric: corroborated→verified; corroborated-but-different→correct in place; else→unverified.
    Mutates t (overwrites corrected figures) and sets verdict['metrics'] + a coverage-based flag."""
    vf = verdict.get("verified_figures") or {}
    metrics: Dict[str, Dict] = {}
    for key, (field, vfkey) in _METRIC_MAP.items():
        claimed = _to_num(t.get(field))
        src_obj = vf.get(vfkey)
        sourced, source = None, None
        if isinstance(src_obj, dict):
            sourced, source = _to_num(src_obj.get("value")), src_obj.get("source")
        elif isinstance(src_obj, (int, float)) and not isinstance(src_obj, bool):
            sourced = float(src_obj)

        if sourced is not None:
            if claimed not in (None, 0) and abs(sourced - claimed) / abs(claimed) <= 0.15:
                status = "verified"
            else:
                status = "corrected"
                t[field] = sourced  # use the sourced value everywhere downstream
            metrics[key] = {"status": status, "source": source, "original": claimed, "value": sourced}
        elif t.get(field) not in _MISSING:
            metrics[key] = {"status": "unverified", "source": None, "original": claimed, "value": claimed}

    verdict["metrics"] = metrics
    # Coverage-based flag (preserve not_found / non-existent companies)
    if verdict.get("flag") != "not_found" and verdict.get("exists") is not False and metrics:
        n_ok = sum(1 for m in metrics.values() if m["status"] in ("verified", "corrected"))
        verdict["flag"] = "verified" if n_ok == len(metrics) else ("partial" if n_ok else "unverified")
    return verdict


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def verify_targets(targets: List[Dict], sector: str, geography: str,
                   client: Optional[anthropic.Anthropic] = None) -> List[Dict]:
    """Annotate each target with a `verification` dict. Safe no-op when disabled."""
    if not targets:
        return targets

    provider = active_provider()
    if provider is None:
        reason = "disabled" if _FLAG in ("0", "false", "off", "no") else "no provider configured"
        for t in targets:
            t["verification"] = {"flag": "skipped", "confidence": None, "source": None,
                                 "notes": f"Verification {reason}"}
        return targets

    client = client or anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    subset = targets[:MAX_VERIFY]
    if len(targets) > MAX_VERIFY:
        print(f"  [Verify] Verifying first {MAX_VERIFY} of {len(targets)} targets (cap).")

    claims = [{"name": t.get("name", ""), **{f: t.get(f) for f in _CLAIM_FIELDS}} for t in subset]
    print(f"  Verifying {len(subset)} companies via {provider}...")

    try:
        if provider == "exa":
            evidence = _gather_exa(subset, sector, geography)
            data = _judge_with_claude(client, sector, geography, claims, evidence)
        else:  # bigdata
            data = _judge_with_bigdata(client, sector, geography, claims)
        verdicts = {_norm(r.get("name", "")): r for r in data.get("results", [])}
    except Exception as e:
        debug = Path(__file__).parent.parent / ".tmp" / "debug_verification.txt"
        debug.parent.mkdir(parents=True, exist_ok=True)
        debug.write_text(str(e), encoding="utf-8")
        print(f"  [WARNING] Verification failed ({type(e).__name__}: {e}). Flagging as unverified.")
        verdicts = {}

    for t in targets:
        v = verdicts.get(_norm(t.get("name", "")))
        if v:
            t["verification"] = _reconcile_metrics(t, v)
        else:
            t["verification"] = {"flag": "unverified", "confidence": "low", "source": provider,
                                 "notes": "Not verified (no result returned)",
                                 "metrics": _unverified_metrics(t)}
    return targets


def summarize(targets: List[Dict]) -> Dict[str, int]:
    out = {"verified": 0, "partial": 0, "unverified": 0, "not_found": 0, "skipped": 0}
    for t in targets:
        flag = (t.get("verification") or {}).get("flag", "skipped")
        out[flag] = out.get(flag, 0) + 1
    return out
