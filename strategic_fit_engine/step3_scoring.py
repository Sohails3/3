"""
Step 3 — Strategic Fit Scoring

Scores each target company against:
- 4 buyer-specific criteria derived from Step 1 (C1-C4)
- 3 universal M&A criteria always included (C5-C7):
    C5: Regional & Operational Fit
    C6: Revenue Synergy Potential
    C7: Ease of Acquisition

Companies scored in batches of 5 to stay within token limits.
total_score is always recalculated in Python (never trusted from model).

Outputs: data/targets_scored.json
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
# Fixed additional criteria — always appended to buyer-specific ones
# ---------------------------------------------------------------------------

ADDITIONAL_CRITERIA = [
    {
        "id": "C5",
        "name": "Regional & Operational Fit",
        "description": "Does the company operate in Salesforce's primary European markets? Is it cloud-native with API-first architecture compatible with Salesforce integration patterns?",
        "justification": "Salesforce is targeting UK, Germany, and France as primary Health Cloud expansion markets; operational compatibility reduces post-merger integration cost and timeline.",
    },
    {
        "id": "C6",
        "name": "Revenue Synergy Potential",
        "description": "What additional revenue could Salesforce generate? Score reflects both cross-sell potential to Salesforce's 150,000+ customer base and upsell of Salesforce products to this company's healthcare clients.",
        "justification": "Salesforce's primary acquisition value driver is revenue acceleration through its distribution network; high synergy targets justify premium valuations.",
    },
    {
        "id": "C7",
        "name": "Ease of Acquisition",
        "description": "How straightforward is the acquisition process? Considers ownership structure (PE vs. founder), likely regulatory hurdles, cultural fit, competitive bidding risk, and founder/board alignment.",
        "justification": "Salesforce has historically avoided contested bids and complex regulatory processes; lower friction acquisitions close faster and at lower all-in cost.",
    },
]


# ---------------------------------------------------------------------------
# Shared utilities
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
# Prompt builder
# ---------------------------------------------------------------------------

def build_scoring_prompt(buyer: str, criteria: List[Dict], targets: List[Dict]) -> str:
    criteria_block = "\n".join(
        f"[{c['id']}] {c['name']}: {c['description']}"
        for c in criteria
    )

    company_lines = []
    for i, t in enumerate(targets, 1):
        custs = t.get("key_customers", [])
        custs_str = ", ".join(custs) if isinstance(custs, list) else str(custs)
        line = (
            f"Company {i}: {t['name']} ({t.get('country', '')})\n"
            f"  Stage: {t.get('funding_stage', 'N/A')} | Raised: {t.get('total_raised_usd_m', 'N/A')}M | ARR: {t.get('arr_usd_m', 'N/A')}\n"
            f"  Employees: {t.get('employees', 'N/A')}\n"
            f"  Product: {t.get('product_description', 'N/A')}\n"
            f"  Customers: {custs_str}\n"
            f"  Recent news: {t.get('recent_news', 'N/A')}"
        )
        company_lines.append(line)

    companies_block = "\n\n".join(company_lines)
    criterion_ids = [c["id"] for c in criteria]
    scores_schema = {cid: {"score": "integer 1-5", "rationale": "max 20 words"} for cid in criterion_ids}

    return f"""You are a senior M&A analyst. Score each company as a potential acquisition target for {buyer}.

SCORING CRITERIA:
{criteria_block}

SCALE: 1=Poor fit, 2=Below average, 3=Average, 4=Good fit, 5=Excellent fit

COMPANIES:
{companies_block}

INSTRUCTIONS:
- Score each company 1-5 on EVERY criterion listed above
- Rationale: MAX 20 words per criterion — be specific, not generic
- strategic_fit_summary: 2 sentences max, written for a Managing Director
- deal_breaker_risks: max 2 short items, or empty list []
- product_profile: 2-3 sentences covering product range, target market, growth trajectory, and geographic footprint
- salesforce_relevance: 1-2 sentences on why this company specifically matters to Salesforce's strategy

Return ONLY raw JSON, no markdown fences:
{{
  "targets": [
    {{
      "name": "string",
      "country": "string",
      "product_profile": "string",
      "salesforce_relevance": "string",
      "scores": {json.dumps(scores_schema, indent=6)},
      "strategic_fit_summary": "string",
      "deal_breaker_risks": ["string"]
    }}
  ]
}}

Criteria IDs to include: {criterion_ids}
Return entries in the SAME ORDER as companies listed above.
"""


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def recalculate_totals(targets: List[Dict], criterion_ids: List[str]) -> List[Dict]:
    for t in targets:
        scores = t.get("scores", {})
        total = 0
        for cid in criterion_ids:
            entry = scores.get(cid, {})
            try:
                score_val = max(1, min(5, int(entry.get("score", 1))))
                entry["score"] = score_val
                total += score_val
            except (ValueError, TypeError):
                entry["score"] = 1
                total += 1
        t["total_score"] = total
        t["max_score"] = len(criterion_ids) * 5
    return targets


def rank_targets(targets: List[Dict]) -> List[Dict]:
    targets_sorted = sorted(targets, key=lambda x: x.get("total_score", 0), reverse=True)
    for i, t in enumerate(targets_sorted, 1):
        t["rank"] = i
    return targets_sorted


def merge_with_raw(scored_targets: List[Dict], raw_targets: List[Dict]) -> List[Dict]:
    raw_by_name = {t["name"].lower(): t for t in raw_targets}
    for scored in scored_targets:
        raw = raw_by_name.get(scored["name"].lower(), {})
        for field in ["funding_stage", "total_raised_usd_m", "arr_usd_m",
                      "employees", "product_description", "key_customers",
                      "key_investors", "founded", "recent_news", "website"]:
            if field not in scored and field in raw:
                scored[field] = raw[field]
    return scored_targets


def score_batch(client, buyer: str, criteria: List[Dict], batch: List[Dict], batch_label: str) -> List[Dict]:
    prompt = build_scoring_prompt(buyer, criteria, batch)
    raw = _with_retry(lambda p=prompt: _call_claude(client, p, max_tokens=8096))

    debug_path = Path(__file__).parent.parent / ".tmp" / f"debug_step3_{batch_label}.txt"
    debug_path.parent.mkdir(parents=True, exist_ok=True)
    debug_path.write_text(raw, encoding="utf-8")

    result = _extract_json(raw)
    return result.get("targets", [])


def save(data: Dict, path: Optional[Path] = None) -> None:
    if path is None:
        path = DATA_DIR / "targets_scored.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  [Saved] {path}")


def run(buyer_profile: Optional[Dict] = None, targets_raw: Optional[Dict] = None) -> Dict:
    if buyer_profile is None:
        bp_path = DATA_DIR / "buyer_profile.json"
        print(f"  Loading buyer profile from {bp_path}...")
        with open(bp_path, encoding="utf-8") as f:
            buyer_profile = json.load(f)

    if targets_raw is None:
        tr_path = DATA_DIR / "targets_raw.json"
        print(f"  Loading raw targets from {tr_path}...")
        with open(tr_path, encoding="utf-8") as f:
            targets_raw = json.load(f)

    buyer = buyer_profile.get("buyer", "Strategic Buyer")
    buyer_criteria = buyer_profile.get("scoring_criteria", [])
    all_criteria = buyer_criteria + ADDITIONAL_CRITERIA
    criterion_ids = [c["id"] for c in all_criteria]
    all_targets = targets_raw.get("targets", [])
    n = len(all_targets)

    print(f"  Criteria: {[c['id'] + ': ' + c['name'] for c in all_criteria]}")
    print(f"  Scoring {n} companies (7 criteria, batches of 5)...")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in environment / .env")
    client = anthropic.Anthropic(api_key=api_key)

    batch_size = 5
    scored = []
    for i in range(0, n, batch_size):
        batch = all_targets[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (n + batch_size - 1) // batch_size
        print(f"  Scoring batch {batch_num}/{total_batches} ({len(batch)} companies)...")
        try:
            batch_results = score_batch(client, buyer, all_criteria, batch, f"batch{batch_num}")
            scored.extend(batch_results)
        except ValueError as e:
            raise ValueError(f"Batch {batch_num} failed: {e}")

    if not all_targets:
        raise ValueError(
            "Step 2 found 0 companies. Try a broader sector description — e.g. "
            "'Women's activewear brands' rather than 'Women's Yoga Clothing', "
            "or widen the geography to 'UK/Europe/US'."
        )
    if not scored:
        raise ValueError("Step 3 returned no scored targets.")

    scored = recalculate_totals(scored, criterion_ids)
    scored = merge_with_raw(scored, all_targets)
    scored = rank_targets(scored)

    output = {
        "buyer": buyer,
        "scoring_criteria_used": criterion_ids,
        "criteria_detail": all_criteria,
        "targets": scored,
    }

    save(output)
    return output


# ---------------------------------------------------------------------------
# Standalone entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\n[Step 3] Strategic Fit Scoring (7 criteria)")
    result = run()
    print(f"\nRanked targets:")
    for t in result["targets"]:
        print(f"  #{t['rank']}: {t['name']} — {t['total_score']}/{t['max_score']}")
    print("Done.\n")
