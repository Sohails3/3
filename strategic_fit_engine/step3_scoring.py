"""
Step 3 — Strategic Fit Scoring

Scores each target company against:
- 4 buyer/seller-specific criteria derived from Step 1 (C1-C4)
- 4 universal criteria (C5-C8), which differ by mode:

  BUY-SIDE (default):
    C5: Technology & IP
    C6: Market Position
    C7: Team & Talent
    C8: Legal & Regulatory

  SELL-SIDE:
    C5: Financial Capacity & Deal Track Record
    C6: Strategic Urgency
    C7: Integration Quality
    C8: Premium Likelihood

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

BUY_ADDITIONAL_CRITERIA = [
    {
        "id": "C5",
        "name": "Technology & IP",
        "description": (
            "Strength and defensibility of proprietary technology, patents, and IP. "
            "Considers tech stack compatibility with the acquirer's systems, "
            "scalability of the architecture, security posture, and level of technical debt. "
            "Score 1 = commodity tech with high debt; 5 = highly defensible proprietary IP, "
            "clean architecture, low integration friction."
        ),
        "justification": (
            "For SaaS acquisitions, technology quality and IP defensibility are the primary "
            "drivers of premium valuation and post-merger value retention. Incompatible or "
            "debt-laden tech stacks significantly increase integration cost and timeline."
        ),
        "source": "universal",
    },
    {
        "id": "C6",
        "name": "Market Position",
        "description": (
            "Strength of the target's position in its addressable market. "
            "Considers TAM/SAM size and growth trajectory, competitive moat "
            "(network effects, switching costs, data advantages), customer concentration risk "
            "(a single client >30% of revenue is a red flag), NPS, and churn/retention metrics. "
            "Score 1 = weak position with high churn; 5 = dominant niche player with strong moat."
        ),
        "justification": (
            "Market position determines the durability of revenue post-acquisition and the "
            "strategic value of the customer base. High churn or customer concentration "
            "materially increases execution risk and reduces acquirer confidence in synergy forecasts."
        ),
        "source": "universal",
    },
    {
        "id": "C7",
        "name": "Team & Talent",
        "description": (
            "Quality and retention risk of the founding and engineering team post-acquisition. "
            "Considers key-person dependency (value tied to one or two individuals), "
            "cultural fit with the acquirer, and likely attrition post-close — "
            "especially critical in acqui-hire scenarios. "
            "Score 1 = extreme key-person risk, poor cultural fit; 5 = deep bench, strong alignment."
        ),
        "justification": (
            "Team quality is consistently cited as a top reason acquisitions fail to deliver "
            "expected value. In SaaS, where product and customer relationships are people-driven, "
            "post-close attrition of key talent can destroy acquired value within 12–24 months."
        ),
        "source": "universal",
    },
    {
        "id": "C8",
        "name": "Legal & Regulatory",
        "description": (
            "Assessment of legal and regulatory risk. Considers GDPR and data privacy compliance "
            "(critical for EU healthcare data), antitrust/competition law risk, open-source "
            "licensing obligations, pending litigation or regulatory investigations, "
            "and national security review risk. "
            "Score 1 = significant unresolved legal/regulatory exposure; 5 = clean, fully compliant."
        ),
        "justification": (
            "EU healthcare targets face heightened regulatory scrutiny — GDPR, medical device "
            "regulations, and national security review frameworks (UK NSI Act, German AWG) can "
            "delay or block deals. Unresolved compliance gaps become acquirer liability at close."
        ),
        "source": "universal",
    },
]

# Keep legacy name for any external references
ADDITIONAL_CRITERIA = BUY_ADDITIONAL_CRITERIA

SELL_ADDITIONAL_CRITERIA = [
    {
        "id": "C5",
        "name": "Financial Capacity & Deal Track Record",
        "description": (
            "Can this acquirer fund the deal, and have they successfully closed comparable transactions? "
            "Considers cash/FCF position or fund dry powder for PE, market cap relative to deal size, "
            "number of acquisitions closed in the last 3 years, and integration execution track record. "
            "Score 1 = limited capacity or no deal history; 5 = well-capitalised with multiple relevant closed deals."
        ),
        "justification": (
            "A strategically motivated acquirer with no capacity to close is worthless to the seller. "
            "Deal track record signals that the acquirer can execute an LOI, conduct DD, and close "
            "without extended delay — reducing execution risk for the seller."
        ),
        "source": "sell_universal",
    },
    {
        "id": "C6",
        "name": "Strategic Urgency",
        "description": (
            "How urgently does this acquirer need the seller's capability? "
            "Considers whether a direct competitor just acquired something similar (forcing a response), "
            "whether the acquirer has a stated roadmap gap this seller fills, "
            "and whether their core business is under competitive pressure requiring inorganic acceleration. "
            "Score 1 = no urgency, capability available internally; 5 = existential urgency, must acquire to stay competitive."
        ),
        "justification": (
            "Urgency is the primary driver of premium pricing in M&A. An acquirer under competitive "
            "pressure will pay 20-40% above fair value to close fast. Sellers should prioritise "
            "acquirers with genuine urgency over those with passive interest."
        ),
        "source": "sell_universal",
    },
    {
        "id": "C7",
        "name": "Integration Quality",
        "description": (
            "Does this acquirer have a strong track record of retaining acquired teams and realising synergies? "
            "Considers employee retention post-close from past deals, cultural compatibility with the seller, "
            "integration playbook maturity (dedicated integration team, earnout structures), "
            "and whether acquired founders typically stay on. "
            "Score 1 = serial team-destroyers, high post-close attrition; 5 = proven retention and integration excellence."
        ),
        "justification": (
            "For sellers where team retention matters (acqui-hire premium, IP tied to founders), "
            "a poor integration track record destroys earnout value. Sellers should weight acquirers "
            "who will preserve the business they are paying a premium for."
        ),
        "source": "sell_universal",
    },
    {
        "id": "C8",
        "name": "Premium Likelihood",
        "description": (
            "How likely is this acquirer to pay above fair value (a strategic premium)? "
            "Considers competitive tension signals (are other bidders circling), "
            "the degree to which this seller is a must-have vs. nice-to-have, "
            "whether the acquirer has paid premiums on recent deals, "
            "and whether the seller is their only viable path to this capability. "
            "Score 1 = disciplined buyer, will not overpay; 5 = high likelihood of 25-40% premium above ARR floor."
        ),
        "justification": (
            "The sell-side mandate is to maximise exit valuation. Premium likelihood identifies "
            "which acquirers should be approached last (after building competitive tension) to "
            "extract maximum value. A high-premium acquirer approached too early anchors at a lower price."
        ),
        "source": "sell_universal",
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


def _with_retry(fn, retries: int = 5):
    last_exc = None
    for attempt in range(retries):
        try:
            return fn()
        except anthropic.RateLimitError as e:
            last_exc = e
            wait = 15 * (2 ** attempt)
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
# Prompt builder
# ---------------------------------------------------------------------------

def build_scoring_prompt(buyer: str, criteria: List[Dict], targets: List[Dict],
                         buyer_profile: Optional[Dict] = None) -> str:
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

    is_sell = buyer_profile.get("mode") == "sell" if buyer_profile else False
    if is_sell:
        role_line = f"You are a senior M&A sell-side analyst at GP Bullhound. Score each potential acquirer for {buyer} (the seller). Higher scores = better acquirer candidate."
        scale_line = "SCALE: 1=Poor acquirer candidate, 2=Below average, 3=Average, 4=Strong candidate, 5=Ideal acquirer"
    else:
        role_line = f"You are a senior M&A analyst. Score each company as a potential acquisition target for {buyer}."
        scale_line = "SCALE: 1=Poor fit, 2=Below average, 3=Average, 4=Good fit, 5=Excellent fit"

    return f"""{role_line}

SCORING CRITERIA:
{criteria_block}

{scale_line}

COMPANIES:
{companies_block}

MANDATORY INSTRUCTIONS — read carefully before responding:
- You MUST provide a score (integer 1–5) for EVERY criterion for EVERY company. No blank scores,
  no omissions, no null values. If genuinely uncertain, default to 3 (average).
- Criteria IDs to score: {criterion_ids} — all of them, for every company.
- Rationale: EXACTLY 1 sentence per criterion, MAX 25 words. MUST cite a specific, observable
  feature of this company — a metric, product characteristic, user count, funding fact, or
  competitive position. NEVER write generic statements. Use this format in the rationale field:
  "Score (X/5) — Reason: [specific evidence from the company's product/users/funding/positioning]"
  Examples of GOOD rationale:
    "Score (4/5) — Reason: In-browser Python/JS IDE with real-time output; 2M+ registered users signals proven execution depth."
    "Score (2/5) — Reason: Static video curriculum with no adaptive branching; no evidence of personalisation engine."
    "Score (3/5) — Reason: €8M ARR estimated from ~120 headcount at Series A; limited public financial disclosure."
  Examples of BAD rationale (do not write these):
    "Good technology with strong team." — too generic
    "Fits well with buyer strategy." — not observable
- strategic_fit_summary: 2 sentences, written for a Managing Director audience.
- deal_breaker_risks: max 2 concrete items citing specific observable risks, or [] if none.
- product_profile: 2-3 sentences covering product, target market, growth, and geography.
- buyer_relevance: 1-2 sentences on why this company specifically matters to {buyer}'s strategy.
- ASCII only — no non-Latin characters anywhere in the output.

Return ONLY raw JSON, no markdown fences:
{{
  "targets": [
    {{
      "name": "string",
      "country": "string",
      "product_profile": "string",
      "buyer_relevance": "string",
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

def _ascii_clean(v) -> str:
    """Strip non-ASCII characters from a string."""
    if not isinstance(v, str):
        return str(v)
    return "".join(c for c in v if ord(c) < 256 and (c.isprintable() or c in ("\n", "\t"))).strip()


def recalculate_totals(targets: List[Dict], criterion_ids: List[str]) -> List[Dict]:
    for t in targets:
        scores = t.get("scores", {})
        if not isinstance(scores, dict):
            scores = {}
        total = 0
        for cid in criterion_ids:
            entry = scores.get(cid)
            if entry is None:
                # Score genuinely missing — fill with 3 (neutral; not 1 which unfairly penalises)
                scores[cid] = {"score": 3, "rationale": "Score not returned by model; defaulted to 3."}
                total += 3
                continue
            try:
                if isinstance(entry, dict):
                    raw = entry.get("score")
                    if raw is None:
                        entry["score"] = 3
                        entry.setdefault("rationale", "Score not returned; defaulted to 3.")
                        total += 3
                        continue
                else:
                    raw = entry
                score_val = max(1, min(5, int(raw)))
                if isinstance(entry, dict):
                    entry["score"] = score_val
                    if "rationale" in entry:
                        entry["rationale"] = _ascii_clean(entry["rationale"])
                else:
                    scores[cid] = {"score": score_val, "rationale": ""}
                total += score_val
            except (ValueError, TypeError):
                scores[cid] = {"score": 3, "rationale": "Score parse error; defaulted to 3."}
                total += 3
        t["scores"] = scores
        t["total_score"] = total
        t["max_score"] = len(criterion_ids) * 5

        # Sanitise free-text fields
        for field in ("strategic_fit_summary", "product_profile", "buyer_relevance",
                      "salesforce_relevance", "country", "name"):
            if field in t and isinstance(t[field], str):
                t[field] = _ascii_clean(t[field])

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


def score_batch(client, buyer: str, criteria: List[Dict], batch: List[Dict], batch_label: str,
                buyer_profile: Optional[Dict] = None) -> List[Dict]:
    prompt = build_scoring_prompt(buyer, criteria, batch, buyer_profile=buyer_profile)
    raw = _with_retry(lambda p=prompt: _call_claude(client, p, max_tokens=6000))

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
    # Brief pause to let rate-limit tokens replenish after web-search-heavy Step 2
    print("  [Step 3] Waiting 10s for rate limit headroom...")
    time.sleep(10)

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
    mode = buyer_profile.get("mode", "buy")
    universal = SELL_ADDITIONAL_CRITERIA if mode == "sell" else BUY_ADDITIONAL_CRITERIA
    all_criteria = buyer_criteria + universal
    criterion_ids = [c["id"] for c in all_criteria]
    all_targets = targets_raw.get("targets", [])
    n = len(all_targets)

    print(f"  Criteria: {[c['id'] + ': ' + c['name'] for c in all_criteria]}")
    print(f"  Scoring {n} companies (8 criteria, batches of 5)...")

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
            batch_results = score_batch(client, buyer, all_criteria, batch, f"batch{batch_num}", buyer_profile=buyer_profile)
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
        "buyer":    buyer,
        "mode":     mode,
        "sector":   targets_raw.get("sector", ""),
        "geography": targets_raw.get("geography", ""),
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
    print("\n[Step 3] Strategic Fit Scoring (8 criteria)")
    result = run()
    print(f"\nRanked targets:")
    for t in result["targets"]:
        print(f"  #{t['rank']}: {t['name']} — {t['total_score']}/{t['max_score']}")
    print("Done.\n")
