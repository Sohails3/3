"""
Step 2 — Buyer-Led Target Discovery

Uses the buyer's strategy, dry powder, and target brief from Step 1 to generate
a comprehensive longlist of ALL credible acquisition targets in the sector/geography.

Rather than a generic sector scan, this prompt is personalised to the buyer's
specific M&A thesis: what capabilities they need, what deal sizes are realistic,
and what strategic gaps they are trying to fill.

For each company, also captures acquisition readiness signals so the shortlist
can be filtered by timing as well as fit.

Outputs: data/targets_raw.json
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

DATA_DIR = Path(__file__).parent / "data"
MODEL    = "claude-sonnet-4-6"


REQUIRED_FIELDS = [
    "name", "country", "founded", "funding_stage", "total_raised_usd_m",
    "arr_usd_m", "employees", "product_description", "key_customers",
    "key_investors", "recent_news", "website",
]
LIST_FIELDS = {"key_customers", "key_investors"}


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _extract_json(raw: str) -> Any:
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
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"JSON parse failed.\nRaw (first 800 chars):\n{raw[:800]}")


def _call_claude_with_search(client: anthropic.Anthropic, prompt: str, max_tokens: int = 6000) -> str:
    """Standard single call — web search removed to stay within Tier 1 token limits."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return "\n".join(b.text for b in response.content if hasattr(b, "text"))


def _with_retry(fn, retries: int = 5):
    last_exc = None
    for attempt in range(retries):
        try:
            return fn()
        except anthropic.RateLimitError as e:
            last_exc = e
            wait = 30 * (2 ** attempt)
            print(f"  [Rate limit] Waiting {wait}s before retry {attempt + 1}/{retries}...")
            time.sleep(wait)
        except anthropic.APIStatusError as e:
            last_exc = e
            if attempt == retries - 1:
                raise
            wait = 5 * (2 ** attempt)
            print(f"  [API error {e.status_code}] Retrying in {wait}s...")
            time.sleep(wait)
        except Exception as e:
            last_exc = e
            if attempt == retries - 1:
                raise
            wait = 5 * (2 ** attempt)
            print(f"  [Error: {type(e).__name__}: {e}] Retrying in {wait}s...")
            time.sleep(wait)
    raise RuntimeError(f"Max retries exceeded. Last error: {last_exc}")


DISCOVERY_PROMPT = """You are a senior M&A analyst. Identify EXACTLY {count} ACTIVE, INDEPENDENT private
acquisition targets in {sector} / {geography} that fit {buyer}'s acquisition brief below.
{exclude_clause}
BUYER BRIEF
Strategic thesis: {strategic_summary}
Target profile: {target_brief}
Financial parameters: {dry_powder}

STRICT ELIGIBILITY RULES — a company MUST pass ALL of these to be included:
1. Still operating as an independent company today (2025/2026). NEVER include companies that have
   been shut down, discontinued, wound up, or fully absorbed by a parent since acquisition.
2. Primary HQ must be inside {geography}. Ignore EU satellite offices — use the country where
   the company is legally registered and management is based. A US-HQ'd company with a London
   office does NOT qualify.
3. Real company with a verifiable website confirmed via search. Never fabricate names.
4. Do NOT repeat companies in the exclude list above.
{size_clause}

DATA ACCURACY RULES:
- country: PRIMARY headquarters country only (where founders and C-suite are based).
- arr_usd_m: Use the most recent figure found via web search. If not publicly disclosed, estimate
  from headcount and funding stage (e.g., ~$10k–$20k ARR per employee for early-stage edtech;
  ~$30k–$50k for growth stage). Return a numeric estimate — only use "Not publicly available"
  if you truly cannot produce even a rough estimate.
- recent_news: Most recent known news about the company (2023–2025 preferred).
- All string fields: ASCII characters only — no non-Latin scripts anywhere in the output.
- Keep ALL string fields SHORT: product_description ≤ 25 words, all other strings ≤ 15 words.
- key_customers and key_investors: list of short strings (names only, no descriptions).
- readiness signal values: one short phrase or "Not detected".
- Readiness score 1-10: 4+ signals=8-10, 2-3=5-7, 0-1=1-4.

Return ONLY valid JSON, no markdown fences, no preamble, no trailing text:
{{"sector":"{sector}","geography":"{geography}","buyer":"{buyer}","targets":[{{"name":"string","country":"string","founded":2018,"funding_stage":"string","total_raised_usd_m":45.0,"arr_usd_m":5.0,"employees":120,"product_description":"string max 25 words","key_customers":["string"],"key_investors":["string"],"recent_news":"string max 15 words","website":"string","buyer_fit_rationale":"string max 15 words","readiness_signals":{{"recent_funding":"string or Not detected","leadership_change":"string or Not detected","product_pivot":"string or Not detected","market_expansion":"string or Not detected","strategic_partnership":"string or Not detected"}},"readiness_score":7,"readiness_summary":"string max 15 words"}}]}}
"""


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def _score_readiness(signals: Dict) -> int:
    """Recalculate readiness score in Python from signal dict."""
    positive = sum(
        1 for v in signals.values()
        if v and v.lower() not in ("not detected", "not publicly available", "n/a", "none")
    )
    if positive >= 4: return min(10, 7 + positive - 3)
    if positive >= 2: return 4 + positive
    return max(1, positive * 2 + 1)


def _ascii_clean(v) -> str:
    """Strip non-ASCII / non-Latin characters from a string (prevents Arabic/CJK hallucinations)."""
    if not isinstance(v, str):
        return str(v)
    # Keep printable ASCII + common Western-European accented chars (Latin-1 supplement)
    cleaned = "".join(c for c in v if ord(c) < 256 and (c.isprintable() or c in ("\n", "\t")))
    return cleaned.strip()


def _estimate_arr(t: Dict) -> Optional[float]:
    """
    Estimate ARR in USD millions from headcount + funding stage when the model
    returns 'Not publicly available'.  Uses conservative edtech benchmarks.
    """
    emp = t.get("employees")
    stage = str(t.get("funding_stage", "")).lower()
    try:
        emp_n = int(emp)
    except (TypeError, ValueError):
        emp_n = None

    if emp_n and emp_n > 0:
        # ARR-per-head heuristic by stage (edtech / consumer-subscription benchmarks)
        if "pre-seed" in stage or "seed" in stage:
            arr_per_head = 0.010   # ~$10k per head
        elif "series a" in stage or "series-a" in stage:
            arr_per_head = 0.020
        elif "series b" in stage:
            arr_per_head = 0.035
        elif "series c" in stage or "series d" in stage:
            arr_per_head = 0.055
        elif "growth" in stage or "late" in stage:
            arr_per_head = 0.070
        else:
            arr_per_head = 0.015   # conservative default

        return round(emp_n * arr_per_head, 1)

    # Fallback: rough % of total raised
    raised = t.get("total_raised_usd_m")
    try:
        r = float(raised)
        return round(r * 0.15, 1)   # ~15% of total raised as ARR proxy
    except (TypeError, ValueError):
        pass
    return None


def normalize_targets(targets: List[Dict]) -> List[Dict]:
    normalized = []
    for t in targets:
        clean = {}
        for field in REQUIRED_FIELDS:
            val = t.get(field)
            if val is None or val == "" or val == []:
                clean[field] = ["Not publicly available"] if field in LIST_FIELDS else "Not publicly available"
            elif field in LIST_FIELDS:
                # Sanitise each item in list fields
                if isinstance(val, list):
                    clean[field] = [_ascii_clean(x) for x in val if x and x != "Not publicly available"] or ["Not publicly available"]
                else:
                    clean[field] = [_ascii_clean(str(val))]
            elif isinstance(val, str):
                clean[field] = _ascii_clean(val)
            else:
                clean[field] = val

        # ARR estimation: if missing or explicitly "not available", estimate it
        arr_raw = clean.get("arr_usd_m", "Not publicly available")
        arr_is_missing = (
            arr_raw in ("Not publicly available", "N/A", "", None)
            or (isinstance(arr_raw, str) and "not" in arr_raw.lower())
        )
        if arr_is_missing:
            est = _estimate_arr(t)
            if est is not None:
                clean["arr_usd_m"] = est
                clean["arr_estimated"] = True
            else:
                clean["arr_usd_m"] = "Not publicly available"
                clean["arr_estimated"] = False
        else:
            clean["arr_estimated"] = False

        # Readiness signals
        signals = t.get("readiness_signals") or {}
        if not isinstance(signals, dict):
            signals = {}
        for sig in ["recent_funding", "leadership_change", "product_pivot",
                    "market_expansion", "strategic_partnership"]:
            if sig not in signals or not signals[sig]:
                signals[sig] = "Not detected"
            else:
                signals[sig] = _ascii_clean(str(signals[sig]))
        clean["readiness_signals"] = signals

        # Recalculate readiness score in Python
        clean["readiness_score"] = _score_readiness(signals)
        rs = t.get("readiness_summary", "No readiness signals identified.")
        clean["readiness_summary"] = _ascii_clean(str(rs))

        normalized.append(clean)
    return normalized


def save(data: Dict, path: Optional[Path] = None) -> None:
    if path is None:
        path = DATA_DIR / "targets_raw.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  [Saved] {path}")


def _run_batch(client, sector: str, geography: str, buyer: str,
               strategic_summary: str, target_brief: str, dry_powder: str,
               count: int, exclude: List[str], batch_label: str,
               size_range: str = "Any size") -> List[Dict]:
    """Run a single discovery batch, returning a list of target dicts."""
    exclude_clause = (
        f"Do NOT repeat these already-identified companies: {', '.join(exclude)}.\n"
        if exclude else ""
    )
    size_clause = (
        f"5. Target ARR must be approximately in the range {size_range}. Exclude companies "
        f"that are clearly outside this size band.\n"
        if size_range and size_range.lower() != "any size" else ""
    )
    prompt = DISCOVERY_PROMPT.format(
        sector=sector,
        geography=geography,
        buyer=buyer,
        strategic_summary=strategic_summary,
        target_brief=target_brief,
        dry_powder=dry_powder,
        count=count,
        exclude_clause=exclude_clause,
        size_clause=size_clause,
    )

    raw = _with_retry(lambda: _call_claude_with_search(client, prompt, max_tokens=6000))

    debug_path = Path(__file__).parent.parent / ".tmp" / f"debug_step2_{batch_label}.txt"
    debug_path.parent.mkdir(parents=True, exist_ok=True)
    debug_path.write_text(raw, encoding="utf-8")

    try:
        data = _extract_json(raw)
    except ValueError as e:
        raise ValueError(f"Batch {batch_label} JSON parse failed. Raw saved to {debug_path}.\n{e}")

    return data.get("targets", [])


def run(sector: str, geography: str, buyer_profile: Optional[Dict] = None,
        size_range: str = "Any size") -> Dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=api_key)

    bp = buyer_profile or {}
    buyer             = bp.get("buyer", "the strategic buyer")
    strategic_summary = bp.get("strategic_summary", f"{buyer} is seeking acquisitions in {sector}.")
    target_brief      = bp.get("target_brief", f"Private companies in {sector} within {geography}.")
    dry_powder        = bp.get("dry_powder", "Deal size parameters not specified.")

    print(f"  Building buyer-led longlist for {buyer} in {sector} / {geography}...")

    # Batch A — first 6 companies
    print(f"  Batch 1/2: identifying first 6 targets...")
    batch_a = _run_batch(client, sector, geography, buyer,
                         strategic_summary, target_brief, dry_powder,
                         count=6, exclude=[], batch_label="A", size_range=size_range)

    # Batch B — up to 4 more, excluding batch A; non-fatal if it fails
    exclude_names = [t.get("name", "") for t in batch_a if t.get("name")]
    print(f"  Batch 2/2: identifying up to 4 additional targets...")
    batch_b: List[Dict] = []
    try:
        batch_b = _run_batch(client, sector, geography, buyer,
                             strategic_summary, target_brief, dry_powder,
                             count=4, exclude=exclude_names, batch_label="B",
                             size_range=size_range)
    except Exception as e:
        print(f"  [WARNING] Batch B failed ({e}). Continuing with batch A only.")

    all_targets = batch_a + batch_b

    # Deduplicate by normalised name (strip legal suffixes so "Mimo" == "Mimo GmbH")
    _SUFFIXES = re.compile(
        r'\s+(gmbh|ltd|limited|inc|llc|ag|bv|ab|oy|as|sas|srl|sarl|plc|co\.?)\s*$',
        re.IGNORECASE,
    )

    def _norm_name(name: str) -> str:
        return _SUFFIXES.sub("", name.lower().strip())

    seen: set = set()
    unique_targets = []
    for t in all_targets:
        key = _norm_name(t.get("name", ""))
        if key and key not in seen:
            seen.add(key)
            unique_targets.append(t)

    targets = unique_targets
    if len(targets) < 6:
        print(f"  [WARNING] Only {len(targets)} companies found.")
    else:
        print(f"  Longlist: {len(targets)} companies identified.")

    normalised = normalize_targets(targets)

    data = {
        "sector":    sector,
        "geography": geography,
        "buyer":     buyer,
        "targets":   normalised,
    }
    save(data)
    return data


# ---------------------------------------------------------------------------
# Standalone entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    sector    = sys.argv[1] if len(sys.argv) > 1 else "European Healthcare Vertical SaaS"
    geography = sys.argv[2] if len(sys.argv) > 2 else "UK/Germany/France/Nordics/Netherlands"
    print(f"\n[Step 2] Buyer-Led Target Discovery: {sector} / {geography}")
    data = run(sector, geography)
    print(f"\nCompanies discovered:")
    for t in data["targets"]:
        rs = t.get("readiness_score", "?")
        print(f"  - {t['name']} ({t['country']}) — Readiness: {rs}/10")
    print("Done.\n")
