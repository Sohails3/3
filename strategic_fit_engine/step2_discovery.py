"""
Step 2 — Target Company Discovery

Uses Claude with web search to find 8-10 European healthcare vertical SaaS
companies that are Series A through pre-IPO stage.

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

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

DATA_DIR = Path(__file__).parent / "data"
MODEL = "claude-sonnet-4-6"

REQUIRED_FIELDS = [
    "name", "country", "founded", "funding_stage", "total_raised_usd_m",
    "arr_usd_m", "employees", "product_description", "key_customers",
    "key_investors", "recent_news", "website",
]

LIST_FIELDS = {"key_customers", "key_investors"}


# ---------------------------------------------------------------------------
# Shared utilities (copied pattern — no inter-module dependencies)
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
# Prompt
# ---------------------------------------------------------------------------

DISCOVERY_PROMPT = """You are a senior investment analyst. Your task is to identify 8-10 companies
that are strong potential M&A targets for a strategic buyer in the {sector} space within {geography}.

TARGET CRITERIA:
- Sector: {sector}. Include any company whose primary business operates in this space.
- Geography: {geography}. Prioritise companies headquartered in the specified regions.
- Stage: Private companies — from early growth through pre-IPO. Exclude pre-revenue startups.
  If the sector is consumer/retail/apparel, include companies of any funding stage with meaningful revenue.
- Founded: 2010 or later preferred (exceptions acceptable for established players)

For each company, extract the following fields using web search. If a field is not publicly available,
use EXACTLY the string "Not publicly available" — do NOT estimate or invent figures.

REQUIRED FIELDS PER COMPANY:
- name: Company name
- country: Country of headquarters (UK, Germany, France, etc.)
- founded: Year founded (integer) or "Not publicly available"
- funding_stage: Most recent round (e.g. "Series B", "Series C", "Growth Equity", "Late Stage")
- total_raised_usd_m: Total funding raised in USD millions (number) or "Not publicly available"
- arr_usd_m: Annual Recurring Revenue in USD millions (number or range string) or "Not publicly available"
- employees: Approximate employee count (integer) or "Not publicly available"
- product_description: 1-2 sentences describing the core product and who it serves
- key_customers: List of 2-4 notable customers or customer types (array of strings)
- key_investors: List of 2-4 notable investors (array of strings)
- recent_news: One notable news item from the last 12 months (1 sentence) or "Not publicly available"
- website: Company website URL

IMPORTANT: Find REAL companies with verifiable web presence. Do not fabricate companies.
Aim for 8-10 companies. If you find fewer than 8, still return what you found — do not pad with fictional entries.

Return ONLY the following JSON (no markdown, no preamble):
{{
  "sector": "{sector}",
  "geography": "{geography}",
  "targets": [
    {{
      "name": "string",
      "country": "string",
      "founded": 2018,
      "funding_stage": "string",
      "total_raised_usd_m": 45.0,
      "arr_usd_m": "Not publicly available",
      "employees": 120,
      "product_description": "string",
      "key_customers": ["string"],
      "key_investors": ["string"],
      "recent_news": "string",
      "website": "string"
    }}
  ]
}}
"""


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def build_discovery_prompt(sector: str, geography: str) -> str:
    return DISCOVERY_PROMPT.format(sector=sector, geography=geography)


def normalize_targets(targets: List[Dict]) -> List[Dict]:
    """Ensure all required fields exist; replace None/missing with 'Not publicly available'."""
    normalized = []
    for t in targets:
        clean = {}
        for field in REQUIRED_FIELDS:
            val = t.get(field)
            if val is None or val == "" or val == []:
                if field in LIST_FIELDS:
                    clean[field] = ["Not publicly available"]
                else:
                    clean[field] = "Not publicly available"
            else:
                clean[field] = val
        normalized.append(clean)
    return normalized


def save(data: Dict, path: Optional[Path] = None) -> None:
    if path is None:
        path = DATA_DIR / "targets_raw.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  [Saved] {path}")


def run(sector: str, geography: str) -> Dict:
    """
    Entry point called by main.py.
    Returns targets_raw dict and writes data/targets_raw.json.
    """
    print(f"  Initialising Anthropic client...")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in environment / .env")
    client = anthropic.Anthropic(api_key=api_key)

    prompt = build_discovery_prompt(sector, geography)
    print(f"  Searching for {sector} targets in {geography} (may take 20-40s)...")

    raw = _with_retry(lambda: _call_claude(client, prompt, max_tokens=8096))

    print("  Parsing target company JSON...")
    try:
        data = _extract_json(raw)
    except ValueError as e:
        debug_path = Path(__file__).parent.parent / ".tmp" / "debug_step2.txt"
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_text(raw, encoding="utf-8")
        raise ValueError(f"Failed to parse Step 2 JSON. Raw saved to {debug_path}.\n{e}")

    targets = data.get("targets", [])
    if len(targets) < 6:
        print(f"  [WARNING] Only {len(targets)} companies found (target: 8-10). Proceeding with available data.")
    else:
        print(f"  Found {len(targets)} companies.")

    data["targets"] = normalize_targets(targets)
    data["sector"] = sector
    data["geography"] = geography

    save(data)
    return data


# ---------------------------------------------------------------------------
# Standalone entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    sector = sys.argv[1] if len(sys.argv) > 1 else "European Healthcare Vertical SaaS"
    geography = sys.argv[2] if len(sys.argv) > 2 else "UK/Germany/France/Nordics/Netherlands"

    print(f"\n[Step 2] Target Discovery: {sector} / {geography}")
    data = run(sector, geography)
    print(f"\nCompanies discovered:")
    for t in data["targets"]:
        print(f"  - {t['name']} ({t['country']}) — {t['funding_stage']}")
    print("Done.\n")
