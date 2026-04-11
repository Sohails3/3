"""
Step 1 — Buyer DNA Analysis

Researches the strategic buyer using Claude with web search.
Extracts acquisition history, strategic priorities, product gaps,
and derives 4 buyer-specific scoring criteria.

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
MODEL = "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def _extract_json(raw: str) -> Any:
    """Strip markdown fences if present, then parse JSON.
    Also handles Claude outputting reasoning text before/after the JSON block."""
    text = raw.strip()

    # 1. Try markdown fences first
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 2. Try parsing the whole text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 3. Find the outermost { ... } block (handles reasoning text before/after JSON)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(
        f"JSON parse failed — could not extract JSON from response.\n"
        f"Raw (first 800 chars):\n{raw[:800]}"
    )


def _call_claude(client: anthropic.Anthropic, prompt: str, max_tokens: int = 8096) -> str:
    """Single-turn Claude call using built-in knowledge (no web search required)."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return "\n".join(
        block.text for block in response.content if hasattr(block, "text")
    )


def _with_retry(fn, retries: int = 3):
    """Exponential backoff wrapper for Anthropic API calls."""
    for attempt in range(retries):
        try:
            return fn()
        except anthropic.RateLimitError:
            wait = 5 * (2 ** attempt)
            print(f"  [Rate limit] Waiting {wait}s before retry {attempt + 1}/{retries}...")
            time.sleep(wait)
        except anthropic.APIStatusError as e:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            print(f"  [API error {e.status_code}] Retrying in {wait}s...")
            time.sleep(wait)
    raise RuntimeError("Max retries exceeded")


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

BUYER_DNA_PROMPT = """You are a senior M&A research analyst. Your task is to research {buyer}'s acquisition history
and strategic positioning, then derive exactly 4 buyer-specific scoring criteria for evaluating
{sector} acquisition targets.

RESEARCH TASKS:
1. Find {buyer}'s last 5-7 acquisitions — company name, year, approximate deal size (if publicly known),
   and what specific capability or product gap each acquisition filled
2. Identify {buyer}'s stated strategic priorities from 2024–2026 (earnings calls, investor day, CEO interviews)
3. Identify {buyer}'s current product gaps specifically in {sector}
4. Characterise {buyer}'s acquisition pattern: do they primarily buy for talent, technology, customers, or revenue?

CRITERIA DERIVATION:
Derive EXACTLY 4 scoring criteria that are SPECIFIC to {buyer}'s documented history and gaps in {sector}.
Each criterion must:
- Be directly traceable to something in {buyer}'s acquisition history or stated strategy
- Have a short name (3-6 words)
- Have a 1-sentence description of what it measures on a 1-5 scale
- Have a 1-sentence justification explaining why it matters to THIS specific buyer

Do NOT use generic M&A criteria like "revenue growth" or "EBITDA margin" unless directly tied to {buyer}'s stated priorities.

Return ONLY the following JSON (no markdown fences, no preamble, no trailing text):
{{
  "buyer": "{buyer}",
  "acquisitions": [
    {{
      "name": "string",
      "year": 2023,
      "deal_size_usd_bn": 1.9,
      "capability_gap_filled": "string — specific capability this acquisition provided"
    }}
  ],
  "strategic_priorities": [
    "string — one priority per item, 2024-2026 stated priorities only"
  ],
  "current_product_gaps": [
    "string — specific gap in {sector} not yet addressed by {buyer}'s portfolio"
  ],
  "acquisition_pattern_summary": "string — 2-3 sentences characterising {buyer}'s M&A approach",
  "scoring_criteria": [
    {{
      "id": "C1",
      "name": "string — 3-6 word criterion name",
      "description": "string — 1 sentence describing what this measures on a 1-5 scale",
      "justification": "string — 1 sentence citing specific {buyer} history or stated strategy"
    }},
    {{
      "id": "C2",
      "name": "string",
      "description": "string",
      "justification": "string"
    }},
    {{
      "id": "C3",
      "name": "string",
      "description": "string",
      "justification": "string"
    }},
    {{
      "id": "C4",
      "name": "string",
      "description": "string",
      "justification": "string"
    }}
  ]
}}

The "scoring_criteria" array must contain EXACTLY 4 items with ids C1, C2, C3, C4 in order.
deal_size_usd_bn should be a number or null if not publicly disclosed.
"""


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def build_research_prompt(buyer: str, sector: str) -> str:
    return BUYER_DNA_PROMPT.format(buyer=buyer, sector=sector)


def validate_buyer_profile(profile: Dict) -> Dict:
    """Ensure the profile has exactly 4 criteria with ids C1-C4."""
    criteria = profile.get("scoring_criteria", [])

    # Enforce exactly 4
    if len(criteria) != 4:
        raise ValueError(
            f"Expected 4 scoring_criteria, got {len(criteria)}. "
            "Re-run Step 1 or check the prompt."
        )

    # Normalise ids
    expected_ids = ["C1", "C2", "C3", "C4"]
    for i, criterion in enumerate(criteria):
        criterion["id"] = expected_ids[i]
        for field in ["name", "description", "justification"]:
            if not criterion.get(field):
                criterion[field] = "Not available"

    # Ensure required top-level keys exist
    for key in ["acquisitions", "strategic_priorities", "current_product_gaps", "acquisition_pattern_summary"]:
        if key not in profile:
            profile[key] = [] if key != "acquisition_pattern_summary" else "Not available"

    return profile


def save(profile: Dict, path: Optional[Path] = None) -> None:
    if path is None:
        path = DATA_DIR / "buyer_profile.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
    print(f"  [Saved] {path}")


def run(buyer: str, sector: str) -> Dict:
    """
    Entry point called by main.py.
    Returns the buyer_profile dict and writes data/buyer_profile.json.
    """
    print(f"  Initialising Anthropic client...")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in environment / .env")
    client = anthropic.Anthropic(api_key=api_key)

    prompt = build_research_prompt(buyer, sector)
    print(f"  Researching {buyer} using Claude's knowledge base (may take 20-40s)...")

    raw = _with_retry(lambda: _call_claude(client, prompt, max_tokens=8096))

    print("  Parsing buyer profile JSON...")
    try:
        profile = _extract_json(raw)
    except ValueError as e:
        debug_path = Path(__file__).parent.parent / ".tmp" / "debug_step1.txt"
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_text(raw, encoding="utf-8")
        raise ValueError(f"Failed to parse Step 1 JSON. Raw saved to {debug_path}.\n{e}")

    profile = validate_buyer_profile(profile)
    save(profile)
    return profile


# ---------------------------------------------------------------------------
# Standalone entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    buyer = sys.argv[1] if len(sys.argv) > 1 else "Salesforce"
    sector = sys.argv[2] if len(sys.argv) > 2 else "European Healthcare Vertical SaaS"

    print(f"\n[Step 1] Buyer DNA Analysis: {buyer} / {sector}")
    profile = run(buyer, sector)
    print(f"\nDerived criteria:")
    for c in profile["scoring_criteria"]:
        print(f"  {c['id']}: {c['name']} — {c['justification']}")
    print(f"\nAcquisitions found: {len(profile['acquisitions'])}")
    print("Done.\n")
