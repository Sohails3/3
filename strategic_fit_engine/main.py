"""
Strategic Fit Engine — Main Orchestrator

Supports two modes:
  buy  — advise a buyer: find and score acquisition targets
  sell — advise a seller: find and score potential acquirers

Runs 4 steps sequentially; each step writes JSON to disk so
individual steps can be re-run independently.

Usage:
    python strategic_fit_engine/main.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# ★ CONFIGURATION — change these variables to re-run for a different analysis
# ---------------------------------------------------------------------------
COMPANY   = "Salesforce"          # buyer name (buy mode) or seller name (sell mode)
SECTOR    = "European Healthcare Vertical SaaS"
GEOGRAPHY = "UK/Germany/France/Nordics/Netherlands"
MODE      = "buy"                 # "buy" or "sell"
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"


def _banner(text: str) -> None:
    width = 62
    print(f"\n{'═' * width}")
    print(f"  {text}")
    print(f"{'═' * width}")


def _step_header(step: int, total: int, label: str) -> None:
    print(f"\n{'─' * 62}")
    print(f"  Step {step}/{total} — {label}")
    print(f"{'─' * 62}")


def _check_api_key() -> None:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key or key.startswith("your_"):
        print("\n[ERROR] ANTHROPIC_API_KEY is not set.")
        print("  Add it to your .env file: ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)
    print(f"  API key found: {key[:12]}{'*' * 8}")


def main(company: str = COMPANY, sector: str = SECTOR,
         geography: str = GEOGRAPHY, mode: str = MODE) -> None:
    mode_label = "Sell-Side (Exit Strategy)" if mode == "sell" else "Buy-Side (Target Screening)"
    _banner(f"Strategic Fit Engine  ·  {mode_label}  ·  {company}")
    print(f"  Sector: {sector}")
    print(f"  Geography: {geography}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    _check_api_key()

    start_total = time.time()

    # ── Step 1 ─────────────────────────────────────────────────────────────
    if mode == "sell":
        _step_header(1, 4, "Seller Profile & Acquirer Criteria")
        t0 = time.time()
        from strategic_fit_engine import step1_seller_dna
        buyer_profile = step1_seller_dna.run(company, sector)
    else:
        _step_header(1, 4, "Buyer DNA Analysis")
        t0 = time.time()
        from strategic_fit_engine import step1_buyer_dna
        buyer_profile = step1_buyer_dna.run(company, sector)

    elapsed = time.time() - t0
    criteria_names = [c["name"] for c in buyer_profile.get("scoring_criteria", [])]
    print(f"\n  ✓ Done in {elapsed:.0f}s")
    print(f"    Scoring criteria derived: {criteria_names}")

    # ── Step 2 ─────────────────────────────────────────────────────────────
    if mode == "sell":
        _step_header(2, 4, "Potential Acquirer Discovery")
        t0 = time.time()
        from strategic_fit_engine import step2_acquirer_discovery
        targets_raw = step2_acquirer_discovery.run(sector, geography, buyer_profile=buyer_profile)
    else:
        _step_header(2, 4, "Target Company Discovery")
        t0 = time.time()
        from strategic_fit_engine import step2_discovery
        targets_raw = step2_discovery.run(sector, geography, buyer_profile=buyer_profile)

    elapsed = time.time() - t0
    n_targets = len(targets_raw.get("targets", []))
    label2 = "Acquirers" if mode == "sell" else "Companies"
    print(f"\n  ✓ Done in {elapsed:.0f}s")
    print(f"    {label2} discovered: {n_targets}")
    for t in targets_raw.get("targets", [])[:5]:
        print(f"      • {t['name']} ({t['country']}) — {t['funding_stage']}")
    if n_targets > 5:
        print(f"      ... and {n_targets - 5} more")

    # ── Step 3: Scoring (unchanged for both modes) ─────────────────────────
    label3 = "Acquirer Fit Scoring" if mode == "sell" else "Strategic Fit Scoring"
    _step_header(3, 4, label3)
    t0 = time.time()

    from strategic_fit_engine import step3_scoring
    targets_scored = step3_scoring.run(buyer_profile, targets_raw)
    targets_scored["sector"] = sector
    targets_scored["geography"] = geography
    targets_scored["mode"] = mode

    scored_path = DATA_DIR / "targets_scored.json"
    with open(scored_path, "w", encoding="utf-8") as f:
        json.dump(targets_scored, f, indent=2, ensure_ascii=False)

    elapsed = time.time() - t0
    ranked = targets_scored.get("targets", [])
    print(f"\n  ✓ Done in {elapsed:.0f}s")
    for t in ranked:
        print(f"      #{t['rank']}: {t['name']} — {t['total_score']}/{t['max_score']}")

    # ── Step 4: HTML Report ────────────────────────────────────────────────
    _step_header(4, 4, "Report Generation")
    t0 = time.time()

    from strategic_fit_engine import step4_output
    report_path = step4_output.run(buyer_profile, targets_scored)

    elapsed = time.time() - t0
    print(f"\n  ✓ Done in {elapsed:.0f}s")

    # ── Summary ────────────────────────────────────────────────────────────
    total_elapsed = time.time() - start_total
    top3 = [t for t in ranked if t.get("rank", 99) <= 3]

    _banner("Complete")
    print(f"  Total time: {total_elapsed:.0f}s")
    top_label = "Top 3 Acquirers" if mode == "sell" else "Top 3 Recommendations"
    print(f"\n  {top_label}:")
    for t in top3:
        print(f"    #{t['rank']}: {t['name']} ({t.get('country','')}) — Score: {t['total_score']}/{t.get('max_score',40)}")

    print(f"\n  Output files:")
    print(f"    {DATA_DIR / 'buyer_profile.json'}")
    print(f"    {DATA_DIR / 'targets_raw.json'}")
    print(f"    {DATA_DIR / 'targets_scored.json'}")
    print(f"    {report_path}")
    print(f"\n  Open {report_path} in a browser to view the report.")
    print()


if __name__ == "__main__":
    main()
