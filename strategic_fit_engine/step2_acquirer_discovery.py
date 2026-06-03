"""
Step 2 (Sell-Side) — Acquirer Discovery

Uses the seller's profile from Step 1 to generate a longlist of the most
credible potential acquirers — strategic corporates and PE/growth funds —
that would pay a premium to acquire this company.

For each acquirer, captures acquisition appetite signals so the shortlist
can be filtered by both fit and timing.

Uses the same output schema as step2_discovery.py so steps 3 and 4
work without modification.

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


def _call_claude(client: anthropic.Anthropic, prompt: str, max_tokens: int = 6000) -> str:
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


ACQUIRER_PROMPT = """You are a senior M&A sell-side analyst at GP Bullhound. Identify EXACTLY {count} credible potential acquirers for a {sector} company based in {geography} matching the seller profile below.
{exclude_clause}
SELLER PROFILE
What makes this seller attractive: {strategic_summary}
Ideal acquirer profile: {target_brief}
Seller financials / deal size: {dry_powder}

ELIGIBILITY RULES — an acquirer MUST pass ALL of these:
1. Active company with a track record of acquisitions OR stated M&A appetite in this sector.
2. Sufficient financial capacity: public company, well-capitalised corporate, or PE/growth fund with relevant AUM.
3. Real company with a verifiable website. Never fabricate names.
4. Do NOT repeat acquirers in the exclude list above.
{size_clause}{sale_clause}

TIER CLASSIFICATION — assign acquirer_tier to each acquirer:
- Tier 1 (Strategic Natural): obvious strategic fit, would pay 20-30% above fair value to prevent rivals acquiring this capability. Approach LAST in the process to avoid price anchoring.
- Tier 2 (Strategic Stretch): compelling rationale, will compete on price if Tier 1 enters the process. Approach SECOND.
- Tier 3 (Financial Sponsor): PE/growth equity fund, disciplined valuation-driven buyers, set the price floor. Approach FIRST to establish a baseline bid before strategics enter.

APPROACH SEQUENCE: assign approach_sequence (integer 1=first to contact, higher=later) based on:
- Tier 3 sponsors: approach first (1-5) to build price floor before strategics enter
- Tier 2 strategics: approach second (6-10) to create competitive pressure
- Tier 1 naturals: approach last (11-15+) after competitive tension is established

DATA ACCURACY RULES:
- name: the acquirer company name (strategic corporate or PE fund)
- country: acquirer HQ country
- founded: year acquirer was founded
- funding_stage: for strategics use "Public", "Private", or "PE-backed"; for PE funds use "Growth Equity" or "Buyout"
- total_raised_usd_m: for PE funds, relevant fund size in USD M; for corporates, market cap or last disclosed revenue in USD M
- arr_usd_m: acquirer's own annual revenue in USD M (not the seller's) — estimate if not public
- employees: acquirer headcount
- product_description: max 25 words — what the acquirer does and why they would want this seller
- key_customers: acquirer's notable clients or portfolio companies
- key_investors: acquirer's major shareholders or LPs
- recent_news: most recent known news about the acquirer relevant to M&A or this sector (2023-2025)
- website: acquirer website
- buyer_fit_rationale: max 15 words — why this acquirer would pay a premium for the seller
- acquirer_tier: integer 1, 2, or 3 (see TIER CLASSIFICATION above)
- approach_sequence: integer 1-20 (see APPROACH SEQUENCE above — lower = contact earlier)
- premium_rationale: max 20 words — specific reason this acquirer would pay ABOVE fair value (e.g. "Only path to real-time simulation capability before SAP acquires rival")
- readiness_signals: acquisition APPETITE signals (not seller readiness):
    recent_fundraise_or_ipo: "acquirer recently raised capital or IPO'd giving them dry powder" or "Not detected"
    stated_ma_intent: "press release / earnings call / investor day stating acquisition appetite in this sector" or "Not detected"
    competitor_acquisition: "rival acquirer just bought a similar company, creating urgency" or "Not detected"
    strategic_gap: "specific product or distribution gap the seller would fill" or "Not detected"
    existing_partnership: "acquirer already works with seller or has relationships in this space" or "Not detected"
- readiness_score 1-10: 4+ appetite signals=8-10, 2-3=5-7, 0-1=1-4
- All string fields: ASCII characters only
- Keep ALL string fields SHORT: product_description <= 25 words, all others <= 20 words

Return ONLY valid JSON, no markdown fences, no preamble, no trailing text:
{{"sector":"{sector}","geography":"{geography}","buyer":"{seller}","targets":[{{"name":"string","country":"string","founded":2010,"funding_stage":"Public","total_raised_usd_m":5000.0,"arr_usd_m":2000.0,"employees":5000,"product_description":"string max 25 words","key_customers":["string"],"key_investors":["string"],"recent_news":"string max 15 words","website":"string","buyer_fit_rationale":"string max 15 words","acquirer_tier":1,"approach_sequence":12,"premium_rationale":"string max 20 words","readiness_signals":{{"recent_fundraise_or_ipo":"string or Not detected","stated_ma_intent":"string or Not detected","competitor_acquisition":"string or Not detected","strategic_gap":"string or Not detected","existing_partnership":"string or Not detected"}},"readiness_score":7,"readiness_summary":"string max 15 words"}}]}}
"""


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def _score_appetite(signals: Dict) -> int:
    positive = sum(
        1 for v in signals.values()
        if v and v.lower() not in ("not detected", "not publicly available", "n/a", "none")
    )
    if positive >= 4: return min(10, 7 + positive - 3)
    if positive >= 2: return 4 + positive
    return max(1, positive * 2 + 1)


def _ascii_clean(v) -> str:
    if not isinstance(v, str):
        return str(v)
    cleaned = "".join(c for c in v if ord(c) < 256 and (c.isprintable() or c in ("\n", "\t")))
    return cleaned.strip()


def normalize_acquirers(targets: List[Dict]) -> List[Dict]:
    normalized = []
    for t in targets:
        clean = {}
        for field in REQUIRED_FIELDS:
            val = t.get(field)
            if val is None or val == "" or val == []:
                clean[field] = ["Not publicly available"] if field in LIST_FIELDS else "Not publicly available"
            elif field in LIST_FIELDS:
                if isinstance(val, list):
                    clean[field] = [_ascii_clean(x) for x in val if x and x != "Not publicly available"] or ["Not publicly available"]
                else:
                    clean[field] = [_ascii_clean(str(val))]
            elif isinstance(val, str):
                clean[field] = _ascii_clean(val)
            else:
                clean[field] = val

        # Keep arr_usd_m as-is for acquirers (it's their revenue, not estimated)
        arr_raw = clean.get("arr_usd_m", "Not publicly available")
        arr_is_missing = (
            arr_raw in ("Not publicly available", "N/A", "", None)
            or (isinstance(arr_raw, str) and "not" in arr_raw.lower())
        )
        clean["arr_estimated"] = arr_is_missing

        # Normalise readiness signals (support both naming conventions)
        signals = t.get("readiness_signals") or {}
        if not isinstance(signals, dict):
            signals = {}
        # Map from acquirer-signal names to standard readiness_signals keys
        signal_map = {
            "recent_fundraise_or_ipo": "recent_funding",
            "stated_ma_intent": "leadership_change",
            "competitor_acquisition": "product_pivot",
            "strategic_gap": "market_expansion",
            "existing_partnership": "strategic_partnership",
        }
        normalised_signals = {}
        for acq_key, std_key in signal_map.items():
            val = signals.get(acq_key) or signals.get(std_key, "Not detected")
            normalised_signals[std_key] = _ascii_clean(str(val)) if val else "Not detected"
        clean["readiness_signals"] = normalised_signals
        clean["readiness_score"] = _score_appetite(normalised_signals)
        rs = t.get("readiness_summary", "No acquisition appetite signals identified.")
        clean["readiness_summary"] = _ascii_clean(str(rs))

        # Preserve new IB sell-side fields
        clean["acquirer_tier"]     = int(t.get("acquirer_tier", 2)) if str(t.get("acquirer_tier", 2)).isdigit() else 2
        clean["approach_sequence"] = int(t.get("approach_sequence", 5)) if str(t.get("approach_sequence", 5)).isdigit() else 5
        clean["premium_rationale"] = _ascii_clean(str(t.get("premium_rationale", "")))

        normalized.append(clean)
    return normalized


def save(data: Dict, path: Optional[Path] = None) -> None:
    if path is None:
        path = DATA_DIR / "targets_raw.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  [Saved] {path}")


def _run_batch(client, sector: str, geography: str, seller: str,
               strategic_summary: str, target_brief: str, dry_powder: str,
               count: int, exclude: List[str], batch_label: str,
               size_range: str = "Any size",
               sale_type: str = "Full Sale (100%)") -> List[Dict]:
    exclude_clause = (
        f"Do NOT repeat these already-identified acquirers: {', '.join(exclude)}.\n"
        if exclude else ""
    )
    size_clause = (
        f"5. Acquirer must have sufficient financial capacity to fund an acquisition of a "
        f"{size_range} ARR company. Exclude undercapitalised buyers that could not credibly "
        f"fund a deal at this scale.\n"
        if size_range and size_range.lower() != "any size" else ""
    )
    _SALE_GUIDANCE = {
        "Minority / Growth Investment":
            "weight the longlist heavily toward growth-equity and minority investors that take "
            "non-control stakes; only include strategics that make minority/structured investments.",
        "Majority Stake (control)":
            "weight toward buyout funds and control-oriented strategics that acquire majority stakes.",
        "Strategic Merger":
            "weight toward trade/strategic buyers where a merger unlocks synergies; de-prioritise "
            "pure financial sponsors.",
        "Full Sale (100%)":
            "include the full mix of control buyers — strategics and buyout funds capable of a 100% acquisition.",
    }
    sale_clause = (
        f"6. Transaction type sought: {sale_type}. When building the longlist and assigning tiers, "
        f"{_SALE_GUIDANCE.get(sale_type, 'match acquirers to this deal structure.')}\n"
        if sale_type else ""
    )
    prompt = ACQUIRER_PROMPT.format(
        sector=sector,
        geography=geography,
        seller=seller,
        strategic_summary=strategic_summary,
        target_brief=target_brief,
        dry_powder=dry_powder,
        count=count,
        exclude_clause=exclude_clause,
        size_clause=size_clause,
        sale_clause=sale_clause,
    )

    raw = _with_retry(lambda: _call_claude(client, prompt, max_tokens=6000))

    debug_path = Path(__file__).parent.parent / ".tmp" / f"debug_step2_sell_{batch_label}.txt"
    debug_path.parent.mkdir(parents=True, exist_ok=True)
    debug_path.write_text(raw, encoding="utf-8")

    try:
        data = _extract_json(raw)
    except ValueError as e:
        raise ValueError(f"Batch {batch_label} JSON parse failed. Raw saved to {debug_path}.\n{e}")

    return data.get("targets", [])


def run(sector: str, geography: str, buyer_profile: Optional[Dict] = None,
        size_range: str = "Any size", sale_type: str = "Full Sale (100%)") -> Dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=api_key)

    bp = buyer_profile or {}
    seller            = bp.get("buyer", "the seller company")
    strategic_summary = bp.get("strategic_summary", f"{seller} is seeking acquirers in {sector}.")
    target_brief      = bp.get("target_brief", f"Strategic or financial acquirers active in {sector}.")
    dry_powder        = bp.get("dry_powder", "Deal size parameters not specified.")

    print(f"  Building acquirer longlist for {seller} in {sector} / {geography}...")

    # Batch A — first 6 acquirers (mix of Tier 1 + 2)
    print(f"  Batch 1/3: identifying first 6 acquirers...")
    batch_a = _run_batch(client, sector, geography, seller,
                         strategic_summary, target_brief, dry_powder,
                         count=6, exclude=[], batch_label="A", size_range=size_range,
                         sale_type=sale_type)

    # Batch B — 6 more (focus on different tier / geography)
    exclude_names_b = [t.get("name", "") for t in batch_a if t.get("name")]
    print(f"  Batch 2/3: identifying 6 additional acquirers...")
    batch_b: List[Dict] = []
    try:
        batch_b = _run_batch(client, sector, geography, seller,
                             strategic_summary, target_brief, dry_powder,
                             count=6, exclude=exclude_names_b, batch_label="B",
                             size_range=size_range, sale_type=sale_type)
    except Exception as e:
        print(f"  [WARNING] Batch B failed ({e}). Continuing with batch A only.")

    # Batch C — up to 4 more (PE / financial sponsors if not yet represented)
    exclude_names_c = exclude_names_b + [t.get("name", "") for t in batch_b if t.get("name")]
    print(f"  Batch 3/3: identifying up to 4 additional acquirers (financial sponsors / wildcards)...")
    batch_c: List[Dict] = []
    try:
        batch_c = _run_batch(client, sector, geography, seller,
                             strategic_summary, target_brief, dry_powder,
                             count=4, exclude=exclude_names_c, batch_label="C",
                             size_range=size_range, sale_type=sale_type)
    except Exception as e:
        print(f"  [WARNING] Batch C failed ({e}). Continuing with batches A+B.")

    all_acquirers = batch_a + batch_b + batch_c

    # Deduplicate by normalised name
    _SUFFIXES = re.compile(
        r'\s+(gmbh|ltd|limited|inc|llc|ag|bv|ab|oy|as|sas|srl|sarl|plc|co\.?)\s*$',
        re.IGNORECASE,
    )

    def _norm_name(name: str) -> str:
        return _SUFFIXES.sub("", name.lower().strip())

    seen: set = set()
    unique_acquirers = []
    for t in all_acquirers:
        key = _norm_name(t.get("name", ""))
        if key and key not in seen:
            seen.add(key)
            unique_acquirers.append(t)

    acquirers = unique_acquirers
    if len(acquirers) < 6:
        print(f"  [WARNING] Only {len(acquirers)} acquirers found.")
    else:
        print(f"  Acquirer longlist: {len(acquirers)} companies identified (target: 15-16).")

    normalised = normalize_acquirers(acquirers)

    data = {
        "sector":    sector,
        "geography": geography,
        "buyer":     seller,
        "targets":   normalised,
    }
    save(data)
    return data


# ---------------------------------------------------------------------------
# Standalone entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    sector    = sys.argv[1] if len(sys.argv) > 1 else "Corporate EdTech SaaS"
    geography = sys.argv[2] if len(sys.argv) > 2 else "Global"
    print(f"\n[Step 2 - Sell Side] Acquirer Discovery: {sector} / {geography}")
    data = run(sector, geography)
    print(f"\nAcquirers identified:")
    for t in data["targets"]:
        rs = t.get("readiness_score", "?")
        print(f"  - {t['name']} ({t['country']}) — Appetite Score: {rs}/10")
    print("Done.\n")
