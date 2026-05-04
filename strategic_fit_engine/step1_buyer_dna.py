"""
Step 1 — Buyer Strategy & Competitive Threat Lens

Uses web search to research the buyer in real time:
- Current financials (cash, FCF, revenue — most recent quarter)
- Last 5 acquisitions with deal sizes and rationale
- Stated strategic priorities and product gaps
- Competitor M&A activity in the target sector

Derives 4 buyer-specific scoring criteria from this research.
Works for any buyer in any sector — no manual uploads required.

Outputs: data/buyer_profile.json
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

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

DATA_DIR = Path(__file__).parent / "data"
MODEL    = "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Web search loop
# ---------------------------------------------------------------------------

def _run_with_web_search(client: anthropic.Anthropic, prompt: str,
                          max_tokens: int = 6000, max_iterations: int = 8) -> str:
    """
    Agentic loop that handles web_search_20250305 tool calls.
    Stops at end_turn or after max_iterations search rounds.
    """
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
                    # Web search results are injected automatically by the API;
                    # we just need to acknowledge each tool_use block.
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "",
                    })
            if tool_results:
                messages.append({"role": "user", "content": tool_results})
            continue

        # max_tokens hit or unexpected stop — return whatever text exists
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
    raise ValueError(
        f"JSON parse failed.\nRaw (first 800 chars):\n{raw[:800]}"
    )


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


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

COMBINED_STRATEGY_PROMPT = """You are a senior M&A analyst. Do ONE focused web search for "{buyer} acquisitions strategy financials 2024 2025" to get current data, then return the JSON below. Do not search more than 3 times total.

Produce a buy-side intelligence brief for {buyer} targeting {sector}. Use web search results for financials and recent acquisitions; use your training knowledge for everything else. Return ONLY raw JSON — absolutely no markdown fences, no ```json, no preamble, no trailing text. Start your response with {{ and end with }}.

Be concise — max 2 sentences per string field, max 5 items per array. Derive C1+C2 from competitor threats, C3+C4 from market signals.

JSON schema (fill every field):
{{
  "buyer": "{buyer}",
  "analysis_approach": "web_search_live",
  "strategic_summary": "2-3 sentences on M&A thesis",
  "target_brief": "3-4 sentences: type of company, capabilities, size/stage, geography",
  "dry_powder": "cash position, FCF, deal size range min/sweet spot/max, cash vs stock",
  "acqui_hire_posture": "1-2 sentences",
  "buyer_acquisitions": [{{"name":"","year":0,"deal_size_usd_bn":null,"rationale":""}}],
  "acquisition_pattern_summary": "2-3 sentences",
  "competitors_mapped": [{{"competitor":"","acquisitions":[{{"name":"","year":0,"deal_size_usd_bn":null,"capability_gained":"","threat_to_buyer":""}}]}}],
  "market_signals": [{{"trend":"","description":"","capability_made_urgent":"","timing":""}}],
  "strategic_gaps": [""],
  "competitive_urgency_summary": "2-3 sentences",
  "strategic_priorities": [""],
  "current_product_gaps": [""],
  "acquisitions": [],
  "scoring_criteria": [
    {{"id":"C1","name":"3-6 words","description":"what this measures 1-5","justification":"cites specific competitor move","source":"competitive_threat"}},
    {{"id":"C2","name":"3-6 words","description":"what this measures 1-5","justification":"cites specific competitor move","source":"competitive_threat"}},
    {{"id":"C3","name":"3-6 words","description":"what this measures 1-5","justification":"cites specific market signal","source":"market_signal"}},
    {{"id":"C4","name":"3-6 words","description":"what this measures 1-5","justification":"cites specific market signal","source":"market_signal"}}
  ]
}}
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
                "buyer_acquisitions"]:
        if key not in profile:
            profile[key] = []
    for key in ["acquisition_pattern_summary", "competitive_urgency_summary",
                "acqui_hire_posture", "dry_powder", "strategic_summary", "target_brief"]:
        if key not in profile:
            profile[key] = "Not available"
    return profile


def save(profile: Dict, path: Optional[Path] = None) -> None:
    if path is None:
        path = DATA_DIR / "buyer_profile.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
    print(f"  [Saved] {path}")


def run(buyer: str, sector: str) -> Dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=api_key)

    prompt = COMBINED_STRATEGY_PROMPT.format(buyer=buyer, sector=sector)
    print(f"  Researching {buyer} via web search (financials, acquisitions, competitors)...")

    raw = _with_retry(
        lambda: _run_with_web_search(client, prompt, max_tokens=6000, max_iterations=3)
    )

    try:
        profile = _extract_json(raw)
    except ValueError as e:
        debug_path = Path(__file__).parent.parent / ".tmp" / "debug_step1.txt"
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_text(raw, encoding="utf-8")
        raise ValueError(f"Failed to parse Step 1 JSON. Raw saved to {debug_path}.\n{e}")

    profile = validate_profile(profile)
    save(profile)
    return profile


# ---------------------------------------------------------------------------
# Standalone entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    buyer  = sys.argv[1] if len(sys.argv) > 1 else "Salesforce"
    sector = sys.argv[2] if len(sys.argv) > 2 else "European Healthcare Vertical SaaS"
    print(f"\n[Step 1] Buyer Research via Web Search: {buyer} / {sector}")
    profile = run(buyer, sector)
    print(f"\nCompetitors mapped: {len(profile.get('competitors_mapped', []))}")
    print(f"Strategic gaps identified: {len(profile.get('strategic_gaps', []))}")
    print(f"\nDerived criteria:")
    for c in profile["scoring_criteria"]:
        print(f"  {c['id']}: {c['name']} — {c['justification']}")
    print("Done.\n")
