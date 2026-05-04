# SKILL: M&A Acquisition Target Screening
**Trigger:** Use this skill whenever the task involves finding, screening, scoring, or ranking potential acquisition targets for a strategic buyer.

---

## Overview

This skill instructs Claude to run a buyer-first M&A target screening workflow. It derives scoring criteria from the buyer's own acquisition history and strategy before touching any targets — producing buyer-specific outputs rather than generic lists.

**Inputs required:**
- `BUYER` — the strategic acquirer (e.g. "Duolingo")
- `SECTOR` — the target sector (e.g. "EdTech and digital learning SaaS")
- `GEOGRAPHY` — target region (e.g. "Europe — UK, Germany, France, Nordics")

---

## Step 1 — Buyer DNA Analysis

Before identifying any targets, research the buyer thoroughly.

### What to extract:
1. **Acquisition history** — last 5–7 acquisitions including:
   - Company name, year, deal size (if public)
   - What capability or product gap each acquisition filled
   - Whether it was an acqui-hire, tuck-in, or transformative deal
2. **Strategic priorities** — from earnings calls, investor days, CEO interviews (2023–2026)
3. **Product gaps** — what is the buyer missing that they cannot build organically in time?
4. **Acquisition pattern** — do they buy for talent, technology, customers, or revenue?
5. **Dry powder** — approximate cash on balance sheet and deal size range they operate in

### Output:
Derive exactly **4 buyer-specific scoring criteria (C1–C4)**. Each criterion must be:
- Directly traceable to something in the buyer's acquisition history or stated strategy
- Named clearly (e.g. "Mobile-First Engagement Architecture")
- Justified in one sentence explaining why it matters to THIS buyer specifically

Save as `buyer_profile.json`.

---

## Step 2 — Target Company Discovery

Use web search to find **8–12 companies** matching the buyer brief.

### Search strategy:
- Use multiple search queries combining sector keywords + geography + funding stage
- Prioritise companies that are **Series A through pre-IPO** (not listed, not pre-revenue)
- Search sources: Crunchbase, TechCrunch, Sifted, EU-Startups, LinkedIn, company websites
- Cross-reference with recent news (2024–2026) to confirm companies still exist and are active

### For each company, extract:
| Field | Notes |
|-------|-------|
| Company name | Exact legal/trading name |
| Country | HQ location |
| Founded | Year |
| Funding stage | Pre-seed / Seed / Series A / B / C / Growth / Bootstrapped |
| Total raised | In USD or EUR — from public filings or Crunchbase |
| Estimated ARR | If publicly available — flag as estimate if not confirmed |
| Employee count | From LinkedIn — note it is approximate |
| Core product | 1–2 sentence description |
| Key customers | Named clients if public |
| Notable investors | VC firms or strategics |
| Recent news | Last 12 months — funding rounds, pivots, leadership changes, layoffs |
| Acquisition readiness signals | Any signals the company may be open to a deal |

### Data accuracy rules:
- If a data point is **not publicly available**, mark it `"Not publicly available"` — never estimate or hallucinate figures
- If a funding figure is from an old round, note the date and flag it as potentially outdated
- Always note the source of each data point (Crunchbase, LinkedIn, press release, etc.)
- Cross-reference at least two sources for any figure used in scoring

Save as `targets_raw.json`.

---

## Step 3 — Strategic Fit Scoring

Score each company against **8 criteria**:

### Criteria structure:
- **C1–C4**: Buyer-specific (derived in Step 1 — unique to this buyer)
- **C5**: Technology & IP quality and defensibility
- **C6**: Market position and competitive moat
- **C7**: Team & talent quality and retention risk
- **C8**: Legal & regulatory risk (GDPR, antitrust, national security review)

### Scoring rules:
- Score each criterion **1–5** (1 = poor fit, 5 = excellent fit)
- Total score out of **40**
- Write **one sentence of rationale** per score
- Write a **2–3 sentence strategic fit summary** per company
- Flag any **deal-breaker risks** explicitly (e.g. IP entanglement, open-source licensing, customer concentration)
- Python must recalculate all totals arithmetically — never trust model-generated totals

### Score interpretation:
| Score | Tier |
|-------|------|
| 30–40 | Primary recommendation |
| 22–29 | Mid tier — monitor |
| Below 22 | Lower tier — deprioritise |

Rank all companies descending by total score. Save as `targets_scored.json`.

---

## Step 4 — Output Generation

Generate a clean HTML report containing:

1. **Executive Summary** — targets screened, top 3, geography, date
2. **Buyer Profile** — acquisition history table, strategic gaps, derived rubric
3. **Market Overview** — 3–4 sentences on sector, why attractive for this buyer now
4. **Scored Target Table** — all companies ranked, scores per criterion, colour-coded (green/amber/grey)
5. **Top 3 Recommendations** — one card per company with full score breakdown and key risks
6. **Strip Profile** — side-by-side operational comparison of top 3 (employees, raised, stage, country)
7. **Impact Analysis** — time saved vs manual process, specific banker hours saved
8. **Workflow Diagram** — ASCII or visual showing the 4 steps
9. **Data Sources Disclaimer** — clearly state what is AI-synthesised vs verified

Also generate a `report.pptx` using python-pptx with the same sections.

---

## Data Quality Standards

### Always do:
- Use web search for **every company** — do not rely solely on training data for specific metrics
- State the **date of each data point** where possible
- Flag any figure from training data with: `(AI-synthesised — verify independently)`
- Flag any verified live data with: `✓ verified [source]`
- For UK companies: cross-reference Companies House for incorporation data
- For German companies: cross-reference Handelsregister
- For funding data: cross-reference Crunchbase AND press releases

### Never do:
- Invent ARR, revenue, or employee figures — mark as unavailable
- Present AI-synthesised metrics without a disclaimer
- Use a funding figure without stating the date of the round
- Claim a company is "acquisition ready" without citing a specific signal

---

## Acquisition Readiness Signals to Look For

When researching targets, flag any of the following as positive readiness signals:

- **Funding signals**: Down-round, extended runway warnings, bridge financing, long gap since last raise (24+ months)
- **Leadership signals**: Founder departure, CEO replacement, CFO hire (often precedes a sale process), board composition changes
- **Operational signals**: Headcount reduction (layoffs), pivot in product direction, loss of major customer
- **Strategic signals**: Founder quoted discussing exit, company hired investment bank, secondary share sales by founders
- **Market signals**: Competitor just acquired, acquirer recently lost a bid on a comparable company

---

## File Structure

```
strategic_fit_engine/
├── main.py                  # Orchestrates all 4 steps
├── step1_buyer_dna.py       # Buyer research and rubric derivation
├── step2_discovery.py       # Target company discovery
├── step3_scoring.py         # Strategic fit scoring
├── step4_output.py          # HTML report generation
├── step5_pptx.py            # PowerPoint deck generation
├── .env                     # ANTHROPIC_API_KEY (never commit)
├── data/
│   ├── buyer_profile.json   # Step 1 output
│   ├── targets_raw.json     # Step 2 output
│   └── targets_scored.json  # Step 3 output
└── output/
    ├── report.html          # Final HTML report
    └── report.pptx          # Final PPTX deck
```

---

## API Usage

```python
import anthropic
import os
from dotenv import load_dotenv

load_dotenv()
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# Always use web search for Steps 1 and 2
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=4000,
    tools=[{"type": "web_search_20250305", "name": "web_search"}],
    messages=[{"role": "user", "content": prompt}]
)
```

**Model**: Always use `claude-sonnet-4-6`
**Web search**: Enable for Steps 1 and 2. Optional for Step 3.
**Max tokens**: 4000 for Steps 1–2, 8000 for Step 4 (report generation)

---

## Configurable Inputs

At the top of `main.py`, set these three variables:

```python
BUYER = "Duolingo"
SECTOR = "EdTech and digital learning SaaS"
GEOGRAPHY = "Europe — UK, Germany, France, Nordics, Netherlands"
```

Changing these three variables reruns the entire workflow for a new mandate.

---

## Quality Checks Before Output

Before generating the final report, verify:

- [ ] All 8–12 companies confirmed to exist via web search
- [ ] No ARR or revenue figures presented without a source or disclaimer
- [ ] Scoring totals recalculated in Python (not model arithmetic)
- [ ] Top 3 recommendations have distinct strategic rationale (not just highest scores)
- [ ] Deal-breaker risks flagged for every company
- [ ] Data sources disclaimer included in report
- [ ] Report runs without errors when opened in browser

---

## Common Failure Modes to Avoid

| Failure | Fix |
|---------|-----|
| Model hallucinates ARR figures | Mark all financial metrics as `Not publicly available` unless sourced |
| Generic scoring criteria applied to all buyers | Derive C1–C4 from buyer's actual acquisition history |
| Stale company data (pre-2024) | Always web search each company individually — do not rely on training data |
| Model arithmetic errors in totals | Always recalculate scores in Python |
| Companies that no longer exist | Verify each company is still active before including |
| All companies scored similarly | Ensure rubric discriminates — spread of scores should range from ~18 to ~35 |

---

## Comparison vs Manual IB Process

| Stage | Manual (Investment Bank) | This Workflow |
|-------|--------------------------|---------------|
| Mandate definition | 2–4 weeks | ~2 minutes |
| Longlist generation | 30–80 companies, 2–3 days | 10–12 companies, ~3 minutes |
| Financial screening | Live PitchBook / CapIQ | AI-synthesised — verify independently |
| Shortlisting | Senior banker judgment | C1–C8 rubric scoring |
| Off-market companies | Major advantage via network | Not covered — AI only knows public footprint |
| Speed (phases 1–3) | 3–6 months | ~5–8 minutes |

**Important**: This workflow augments bankers — it does not replace relationship-driven off-market sourcing, sellability assessment, or negotiation.
