"""
Step 1 (Sell-Side) — Seller Profile & Acquirer Criteria

Researches the seller company via web search to understand:
- What makes them an attractive acquisition target
- Their financials, IP, customers, team, competitive position
- Which types of acquirers would want them and why

Derives exactly 4 seller-specific criteria (C1-C4) that define what
an ideal acquirer looks like from the seller's perspective.

Uses the same output schema as step1_buyer_dna.py so steps 3 and 4
work without modification.

Outputs: data/buyer_profile.json (seller perspective)
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


# ---------------------------------------------------------------------------
# Web search loop (identical to step1_buyer_dna.py)
# ---------------------------------------------------------------------------

def _run_with_web_search(client: anthropic.Anthropic, prompt: str,
                          max_tokens: int = 6000, max_iterations: int = 3) -> str:
    messages: List[Dict] = [{"role": "user", "content": prompt}]
    tools = [{"type": "web_search_20250305", "name": "web_search"}]
    iterations = 0

    while iterations < max_iterations:
        response = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            tools=tools,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            return "\n".join(b.text for b in response.content if hasattr(b, "text"))

        if response.stop_reason == "tool_use":
            iterations += 1
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "",
                    })
            if tool_results:
                messages.append({"role": "user", "content": tool_results})
            continue

        return "\n".join(b.text for b in response.content if hasattr(b, "text"))

    return "\n".join(b.text for b in response.content if hasattr(b, "text"))


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


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

SELLER_PROFILE_PROMPT = """You are a senior M&A sell-side advisor at GP Bullhound. Do ONE focused web search for "{seller} company funding revenue product 2024 2025" to get current data, then return the JSON below. Do not search more than 3 times total.

Produce a sell-side intelligence brief for {seller} — a company in {sector} that is exploring an exit. Your goal is to identify what makes this company attractive to acquirers, what comparable exits have been valued at, and which types of buyers would pay a strategic premium.

Derive C1 from the build-vs-buy urgency for potential acquirers. Derive C2 from the acquirer's financial capacity and M&A track record. Derive C3 from integration quality (will they retain the team and realise synergies). Derive C4 from the likelihood of paying above fair value (premium likelihood signals).

Return ONLY raw JSON — absolutely no markdown fences, no ```json, no preamble, no trailing text. Start your response with {{ and end with }}.

JSON schema (fill every field — use the seller's perspective throughout):
{{
  "buyer": "{seller}",
  "mode": "sell",
  "analysis_approach": "web_search_live",
  "strategic_summary": "2-3 sentences: what this company does, why it is a compelling acquisition target, what capability it offers acquirers",
  "target_brief": "3-4 sentences: profile of the ideal acquirer — what sector, size, strategic gaps, geography, deal appetite",
  "dry_powder": "seller financials: estimated ARR, growth rate, funding raised, estimated valuation range (e.g. 5-8x ARR), deal size expected",
  "acqui_hire_posture": "1-2 sentences on team quality and acqui-hire appeal",
  "buyer_acquisitions": [
    {{"name": "key milestone or partnership that signals value", "year": 0, "deal_size_usd_bn": null, "rationale": "why this milestone makes the seller more attractive"}}
  ],
  "acquisition_pattern_summary": "2-3 sentences: pattern of companies like this seller that have been acquired — by whom, at what multiples",
  "competitors_mapped": [
    {{"competitor": "competitor to seller", "acquisitions": [{{"name": "company that acquired a similar seller", "year": 0, "deal_size_usd_bn": null, "capability_gained": "what the acquirer got", "threat_to_buyer": "why this sale to a rival would be bad for the potential acquirer"}}]}}
  ],
  "market_signals": [
    {{"trend": "trend name", "description": "1-2 sentences", "capability_made_urgent": "what seller capability this makes urgent", "timing": "why now"}}
  ],
  "strategic_gaps": ["gap acquirers have that this seller fills — be specific"],
  "competitive_urgency_summary": "2-3 sentences: why acquirers need to move now — competitive pressure, market window, rival interest",
  "strategic_priorities": ["seller's key strengths that drive acquisition appeal"],
  "current_product_gaps": ["gaps in acquirers' portfolios that the seller would fill"],
  "acquisitions": [],
  "valuation_comps": [
    {{
      "target": "company name that was acquired",
      "acquirer": "acquirer name",
      "year": 2023,
      "ev_usd_m": 450,
      "arr_multiple": 8.5,
      "rationale": "1 sentence: why this comp is relevant to {seller}'s valuation"
    }}
  ],
  "revenue_quality": {{
    "nrr_pct": "estimated NRR % (e.g. 115%) or Not Available",
    "arr_services_mix": "estimated % ARR vs % services revenue (e.g. 80% ARR / 20% services)",
    "customer_concentration": "top customer as % of ARR (e.g. <10% or name if known)",
    "churn_signal": "Low / Medium / High / Not Available"
  }},
  "valuation_range": {{
    "floor_arr_multiple": 5,
    "ceiling_arr_multiple": 10,
    "strategic_premium_pct": 25,
    "rationale": "1-2 sentences: why strategic buyers would pay above the floor multiple"
  }},
  "seller_story_strategic": "2-3 sentences framing {seller} for strategic acquirers: the build-vs-buy argument, capability gap filled, and why now is the right time",
  "seller_story_pe": "2-3 sentences framing {seller} for PE/growth equity: ARR quality, growth rate, path to profitability, and exit multiple thesis",
  "process_recommendation": "auction or bilateral — and 1 sentence explaining why given the number of credible strategic buyers and competitive tension signals",
  "scoring_criteria": [
    {{"id":"C1","name":"3-6 words: build-vs-buy urgency signal","description":"Measures how urgently this acquirer needs the seller capability vs building it in-house. Score 1=can build easily; 5=must acquire to remain competitive.","justification":"cites specific capability gap or competitive threat that makes acquisition urgent for this acquirer type","source":"competitive_threat"}},
    {{"id":"C2","name":"3-6 words: financial capacity and M&A track record","description":"Measures whether this acquirer can fund the deal and has successfully closed comparable transactions. Score 1=limited capacity or no deal history; 5=well-capitalised with multiple relevant closed deals.","justification":"cites specific acquirer financial profile or deal history relevant to a transaction of this size","source":"competitive_threat"}},
    {{"id":"C3","name":"3-6 words: integration and team retention quality","description":"Measures whether this acquirer retains acquired teams and realises synergies post-close. Score 1=poor retention, team-destroyers; 5=proven integration playbook and retention track record.","justification":"cites acquirer's historical integration quality or cultural fit with {sector} companies","source":"market_signal"}},
    {{"id":"C4","name":"3-6 words: premium likelihood and urgency signals","description":"Measures how likely this acquirer is to pay above fair value. Score 1=disciplined buyer, will not overpay; 5=high likelihood of 25-40% strategic premium due to competitive pressure or must-have status.","justification":"cites specific signals that this acquirer type faces competitive pressure or urgency that drives premium pricing","source":"market_signal"}}
  ]
}}

IMPORTANT: valuation_comps must contain 3-5 real, verifiable comparable acquisitions in {sector} with actual EV and ARR multiple data. Do not fabricate these — if you cannot find real comps, use 2-3 and note estimates.
"""


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def validate_profile(profile: Dict) -> Dict:
    criteria = profile.get("scoring_criteria", [])
    if len(criteria) != 4:
        raise ValueError(f"Expected 4 scoring_criteria, got {len(criteria)}.")
    for i, c in enumerate(criteria):
        c["id"] = f"C{i+1}"
        for field in ["name", "description", "justification"]:
            if not c.get(field):
                c[field] = "Not available"
    for key in ["competitors_mapped", "market_signals", "strategic_gaps",
                "strategic_priorities", "current_product_gaps", "acquisitions",
                "buyer_acquisitions", "valuation_comps"]:
        if key not in profile:
            profile[key] = []
    for key in ["acquisition_pattern_summary", "competitive_urgency_summary",
                "acqui_hire_posture", "dry_powder", "strategic_summary", "target_brief",
                "seller_story_strategic", "seller_story_pe", "process_recommendation"]:
        if key not in profile:
            profile[key] = "Not available"
    # Validate / default revenue_quality block
    rq = profile.get("revenue_quality")
    if not isinstance(rq, dict):
        rq = {}
    profile["revenue_quality"] = {
        "nrr_pct":              rq.get("nrr_pct", "Not Available"),
        "arr_services_mix":     rq.get("arr_services_mix", "Not Available"),
        "customer_concentration": rq.get("customer_concentration", "Not Available"),
        "churn_signal":         rq.get("churn_signal", "Not Available"),
    }
    # Validate / default valuation_range block
    vr = profile.get("valuation_range")
    if not isinstance(vr, dict):
        vr = {}
    profile["valuation_range"] = {
        "floor_arr_multiple":   vr.get("floor_arr_multiple", 5),
        "ceiling_arr_multiple": vr.get("ceiling_arr_multiple", 10),
        "strategic_premium_pct": vr.get("strategic_premium_pct", 25),
        "rationale":            vr.get("rationale", "Not available"),
    }
    # Always mark as sell-side so downstream steps can check
    profile["mode"] = "sell"
    return profile


def save(profile: Dict, path: Optional[Path] = None) -> None:
    if path is None:
        path = DATA_DIR / "buyer_profile.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
    print(f"  [Saved] {path}")


def run(seller: str, sector: str) -> Dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=api_key)

    prompt = SELLER_PROFILE_PROMPT.format(seller=seller, sector=sector)
    print(f"  Researching {seller} (sell-side) via web search...")

    raw = _with_retry(
        lambda: _run_with_web_search(client, prompt, max_tokens=6000, max_iterations=3)
    )

    try:
        profile = _extract_json(raw)
    except ValueError as e:
        debug_path = Path(__file__).parent.parent / ".tmp" / "debug_step1_sell.txt"
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_text(raw, encoding="utf-8")
        raise ValueError(f"Failed to parse Step 1 (sell) JSON. Raw saved to {debug_path}.\n{e}")

    profile = validate_profile(profile)
    save(profile)
    return profile


# ---------------------------------------------------------------------------
# Standalone entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    seller = sys.argv[1] if len(sys.argv) > 1 else "Attensi"
    sector = sys.argv[2] if len(sys.argv) > 2 else "Corporate EdTech SaaS"
    print(f"\n[Step 1 - Sell Side] Seller Profile: {seller} / {sector}")
    profile = run(seller, sector)
    print(f"\nStrategic summary: {profile.get('strategic_summary','')}")
    print(f"\nDerived acquirer criteria:")
    for c in profile["scoring_criteria"]:
        print(f"  {c['id']}: {c['name']} — {c['justification']}")
    print("Done.\n")
