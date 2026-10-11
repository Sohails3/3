"""
Industry taxonomy — the top-level scope for a screen.

The user picks an INDUSTRY from this fixed list and types a free-text SUB-SECTOR
inside it (e.g. Industry = "Real Estate & Property", Sub-sector = "PropTech
lettings software"). The industry is not cosmetic: `context_block()` is injected
into every Claude prompt in steps 1 and 2 so the model reasons with that
industry's own valuation metrics, buyer archetypes and diligence concerns
instead of defaulting to generic SaaS logic.

Single source of truth: `app.py` builds the dropdown from INDUSTRIES, and the
step modules build their prompt context from the same dict — so the UI and the
pipeline can never drift apart.
"""

from typing import Dict, List

# Default / opt-out value. Selecting this injects no industry context, which
# reproduces the engine's original behaviour exactly.
ANY = "All Industries (Cross-Sector)"

# label -> {examples: [sub-sector examples], metrics, buyers, diligence}
INDUSTRIES: Dict[str, Dict] = {
    "Technology & Software": {
        "examples": ["Vertical SaaS for healthcare", "FinTech payments infrastructure", "DevOps tooling"],
        "metrics": "ARR and ARR growth, net revenue retention, gross margin, Rule of 40, CAC payback, "
                   "logo churn, ARR multiples (EV/ARR) rather than EBITDA multiples for growth assets",
        "buyers": "strategic platform consolidators, larger software vendors filling product gaps, "
                  "software-focused private equity running buy-and-build",
        "diligence": "code and architecture quality, technical debt, concentration in the top 10 customers, "
                     "contracted vs. usage revenue, open-source licence exposure, data-protection posture",
    },
    "Financial Services": {
        "examples": ["SME lending", "Wealth management platforms", "Payments acquiring"],
        "metrics": "AUM or loan book size, net interest margin, fee income mix, cost/income ratio, "
                   "capital adequacy, book value and P/B multiples alongside earnings multiples",
        "buyers": "banks and diversified financial groups, PE with financial-services teams, "
                  "consolidators of fragmented advice/brokerage books",
        "diligence": "regulatory permissions and change-of-control approval, capital requirements, "
                     "credit quality and provisioning, conduct/mis-selling history, AML and KYC controls",
    },
    "Insurance": {
        "examples": ["MGA specialty lines", "Insurance broking", "Claims automation software"],
        "metrics": "gross written premium, combined ratio, loss ratio, retention rate, float, "
                   "EBITDA multiples for brokers/MGAs vs. book-value multiples for carriers",
        "buyers": "broker consolidators, carriers seeking distribution, PE-backed platform rollups",
        "diligence": "reserve adequacy, reinsurance programme, binder and capacity agreements, "
                     "regulatory approvals, claims leakage, renewal-book stickiness",
    },
    "Healthcare & Life Sciences": {
        "examples": ["Clinical workflow software", "Diagnostics labs", "Outpatient care groups"],
        "metrics": "payer/reimbursement mix, patient or contract volumes, EBITDA margin and EBITDA multiples, "
                   "for services: bed/site utilisation; for tools: recurring consumables revenue",
        "buyers": "healthcare strategics and provider groups, medtech/pharma acquirers, "
                  "healthcare-specialist PE, payors moving into care delivery",
        "diligence": "clinical governance and CQC/equivalent ratings, reimbursement and coding risk, "
                     "regulatory clearance (CE/FDA/MHRA), clinical evidence, patient-data handling",
    },
    "Pharmaceuticals & Biotech": {
        "examples": ["Clinical-stage oncology", "CDMO manufacturing", "Generic and specialty pharma"],
        "metrics": "pipeline stage and probability of success, patent runway, peak-sales potential, "
                   "risk-adjusted NPV rather than near-term earnings, milestone/royalty structures",
        "buyers": "large-cap pharma filling pipeline gaps, specialty pharma, "
                  "biotech-focused funds and royalty investors",
        "diligence": "IP strength and patent cliffs, trial data integrity, regulatory pathway, "
                     "GMP compliance, manufacturing scale-up risk, earn-out/CVR structuring",
    },
    "Real Estate & Property": {
        "examples": ["PropTech lettings software", "Build-to-rent operators", "Facilities management"],
        "metrics": "NAV and NAV discount, yield and cap rate, rental income and WAULT, occupancy, "
                   "loan-to-value, development margin, cost per sq ft",
        "buyers": "REITs and property groups, infrastructure and real-asset funds, "
                  "PropTech strategics, facilities-management consolidators",
        "diligence": "asset valuations and independent survey, tenant covenant strength, lease structure, "
                     "planning consents, ground-rent and service-charge exposure, EPC/energy compliance",
    },
    "Construction & Built Environment": {
        "examples": ["Modular construction", "M&E contracting", "Construction project software"],
        "metrics": "order book and pipeline coverage, contract margin, work-in-progress, "
                   "cash conversion, EBITDA multiples (typically low for pure contracting)",
        "buyers": "tier-1 contractors, building-products groups, infrastructure funds, trade consolidators",
        "diligence": "fixed-price contract risk, retentions and claims, health-and-safety record, "
                     "bonding capacity, subcontractor dependency, defect and warranty liabilities",
    },
    "Industrials & Manufacturing": {
        "examples": ["Precision components", "Industrial automation", "Packaging machinery"],
        "metrics": "EBITDA margin and EBITDA multiples, capacity utilisation, order backlog, "
                   "working-capital intensity, capex requirements, aftermarket/service revenue share",
        "buyers": "strategic manufacturers seeking capacity or technology, industrial PE, "
                  "vertically integrating customers or suppliers",
        "diligence": "asset condition and capex backlog, customer concentration, input-cost pass-through, "
                     "environmental liabilities and site contamination, supply-chain resilience",
    },
    "Energy & Utilities": {
        "examples": ["Solar development", "Grid services software", "District heating"],
        "metrics": "generation capacity (MW), load factor, PPA coverage and tenor, regulated asset base, "
                   "levelised cost of energy, long-dated DCF rather than short-run multiples",
        "buyers": "utilities, infrastructure and energy-transition funds, oil-and-gas majors diversifying, "
                  "independent power producers",
        "diligence": "subsidy and regulatory regime durability, offtake contract quality, grid connection, "
                     "permitting, decommissioning liabilities, commodity-price exposure",
    },
    "Mining, Metals & Materials": {
        "examples": ["Battery materials", "Specialty chemicals", "Aggregates"],
        "metrics": "reserves and resource life, all-in sustaining cost, grade, production volumes, "
                   "commodity-price sensitivity, NPV of mine plan",
        "buyers": "diversified miners and materials groups, downstream industrial offtakers, "
                  "resource-focused funds and sovereign buyers",
        "diligence": "resource statement verification (JORC/NI 43-101), permitting and licence tenure, "
                     "environmental and rehabilitation provisions, community and ESG risk",
    },
    "Consumer Goods & Retail": {
        "examples": ["DTC personal care", "Specialty grocery", "Retail media software"],
        "metrics": "like-for-like sales growth, gross margin, contribution margin after marketing, "
                   "repeat-purchase rate and LTV/CAC, inventory turns, EBITDA multiples",
        "buyers": "consumer strategics and brand houses, retail groups, consumer-focused PE, "
                  "marketplace and platform acquirers",
        "diligence": "brand strength and customer concentration, channel mix and retailer relationships, "
                     "returns and discounting, inventory ageing, supplier and freight exposure",
    },
    "Food, Beverage & Agriculture": {
        "examples": ["Plant-based foods", "AgTech precision farming", "Contract food manufacturing"],
        "metrics": "volume growth and price/mix, gross margin, capacity utilisation, "
                   "commodity input exposure, private-label vs. branded mix, EBITDA multiples",
        "buyers": "food and beverage strategics, private-label manufacturers, agri-conglomerates, "
                  "consumer PE running buy-and-build",
        "diligence": "food-safety certification and audit history, retailer listings and contract terms, "
                     "commodity hedging, shelf-life and wastage, traceability and origin claims",
    },
    "Media & Entertainment": {
        "examples": ["Sports rights", "Digital publishing", "Games studios"],
        "metrics": "subscribers/audience and churn, ARPU, content amortisation, IP library value, "
                   "advertising yield, EBITDA multiples with content spend normalised",
        "buyers": "media groups and streaming platforms, games publishers, IP aggregators, "
                  "content-focused PE and rights investors",
        "diligence": "rights ownership and licence terms, talent and creator dependency, content pipeline, "
                     "residual/royalty obligations, platform-algorithm dependency",
    },
    "Telecommunications": {
        "examples": ["Fibre altnets", "MVNO operators", "Network management software"],
        "metrics": "homes passed and connected, take-up rate, ARPU, churn, EBITDA and OpFCF, "
                   "infrastructure multiples on long-dated cash flows, capex per premise",
        "buyers": "incumbent telcos, infrastructure funds, tower and fibre consolidators, "
                  "cable and satellite operators",
        "diligence": "spectrum and licence conditions, network build cost and coverage obligations, "
                     "wholesale agreements, regulatory pricing intervention, overbuild risk",
    },
    "Transport & Logistics": {
        "examples": ["Last-mile delivery", "Freight forwarding", "Fleet telematics software"],
        "metrics": "revenue per shipment, load factor and utilisation, on-time performance, "
                   "network density, asset-light vs. asset-heavy mix, EBITDA/EBIT multiples",
        "buyers": "global freight and logistics groups, e-commerce players integrating fulfilment, "
                  "infrastructure and PE consolidators",
        "diligence": "customer contract tenor and pricing mechanisms, fuel and driver-cost exposure, "
                     "fleet age and lease obligations, depot leases, cross-border customs capability",
    },
    "Travel, Hospitality & Leisure": {
        "examples": ["Boutique hotel groups", "Travel booking platforms", "Fitness operators"],
        "metrics": "RevPAR and occupancy, ADR, membership and churn for subscription models, "
                   "booking value and take rate, site-level EBITDA and rent-adjusted multiples",
        "buyers": "hotel and leisure operators, OTA and travel platforms, real-estate-backed investors, "
                  "leisure-focused PE",
        "diligence": "lease vs. freehold estate, seasonality and demand volatility, refurbishment capex, "
                     "franchise/brand agreements, licensing and safety compliance",
    },
    "Business & Professional Services": {
        "examples": ["Regulatory consulting", "Testing and certification", "Managed IT services"],
        "metrics": "recurring vs. project revenue mix, utilisation and billable rates, revenue per fee-earner, "
                   "client retention, EBITDA margin, EBITDA multiples with owner add-backs scrutinised",
        "buyers": "professional-services consolidators, strategics acquiring capability or accreditation, "
                  "PE running platform-and-bolt-on strategies",
        "diligence": "key-person and founder dependency, client concentration, contract renewal profile, "
                     "accreditations and licences, staff attrition and non-competes",
    },
    "Education & Training": {
        "examples": ["Corporate learning platforms", "Vocational training providers", "K-12 EdTech"],
        "metrics": "enrolments and student retention, revenue per learner, completion rates, "
                   "recurring institutional contracts, ARR for platforms, EBITDA multiples for providers",
        "buyers": "education groups and publishers, EdTech platforms consolidating content, "
                  "education-focused PE, corporate-training strategics",
        "diligence": "accreditation and inspection ratings, government funding dependency, "
                     "safeguarding compliance, curriculum/content IP, seasonality of enrolment",
    },
    "Aerospace & Defence": {
        "examples": ["Defence electronics", "MRO services", "Space and satellite systems"],
        "metrics": "programme backlog and book-to-bill, contract margin, sole-source positions, "
                   "aftermarket share, EBITDA multiples with programme longevity as a premium driver",
        "buyers": "prime contractors and tier-1 suppliers, defence-focused PE, "
                  "national champions with sovereign-capability mandates",
        "diligence": "export controls (ITAR/EAR), security clearances, foreign-ownership and national-security "
                     "screening, programme cancellation risk, long-term fixed-price contract exposure",
    },
    "Automotive & Mobility": {
        "examples": ["EV charging networks", "Vehicle software", "Aftermarket parts distribution"],
        "metrics": "units and content per vehicle, platform win rates, aftermarket revenue share, "
                   "utilisation for mobility assets, EBITDA multiples with electrification exposure weighted",
        "buyers": "OEMs and tier-1 suppliers, energy companies entering charging, "
                  "mobility platforms, automotive-focused PE",
        "diligence": "OEM platform dependency and nomination risk, ICE-to-EV transition exposure, "
                     "tooling and capex commitments, warranty and recall liabilities",
    },
    "Public Sector & Government Services": {
        "examples": ["GovTech case management", "Defence and civil outsourcing", "Local authority services"],
        "metrics": "framework positions and contract backlog, contract margin, re-compete win rate, "
                   "revenue visibility over 3-5 years, EBITDA multiples discounted for political risk",
        "buyers": "government-services strategics, IT outsourcers, PE with public-sector track record",
        "diligence": "procurement framework eligibility, re-compete and termination-for-convenience risk, "
                     "security clearance, transparency/FOI exposure, SLA penalty regimes",
    },
}

# Rendering order for the dropdown: opt-out first, then the taxonomy above.
ORDER: List[str] = [ANY] + list(INDUSTRIES.keys())


def is_any(industry: str) -> bool:
    """True when no meaningful industry scope was chosen."""
    return not industry or industry.strip() == ANY or industry.strip() not in INDUSTRIES


def normalize(industry: str) -> str:
    """Coerce arbitrary form input to a known label (defends against tampering)."""
    ind = (industry or "").strip()
    return ind if ind in INDUSTRIES else ANY


def sector_examples() -> Dict[str, List[str]]:
    """{industry label: [sub-sector examples]} — used to drive the UI placeholder."""
    return {k: v["examples"] for k, v in INDUSTRIES.items()}


def label(industry: str, sector: str = "") -> str:
    """Display label combining industry and sub-sector, e.g. 'Real Estate & Property · PropTech'."""
    ind, sec = (industry or "").strip(), (sector or "").strip()
    if is_any(ind):
        return sec
    return f"{ind} · {sec}" if sec else ind


def context_block(industry: str, sector: str = "") -> str:
    """
    Prompt-ready industry framing, prepended to every step 1 / step 2 prompt.

    Returns "" for the cross-sector default so the engine's original behaviour
    is preserved exactly when the user doesn't scope the screen.
    """
    if is_any(industry):
        return ""
    d = INDUSTRIES[industry.strip()]
    sub = f'"{sector.strip()}"' if sector and sector.strip() else "the stated sub-sector"
    return (
        f"INDUSTRY SCOPE — This screen is scoped to the {industry.strip()} industry; "
        f"{sub} is a sub-sector within it. Reason with this industry's own conventions, "
        f"not generic software or cross-sector defaults:\n"
        f"  - Value drivers and metrics that matter here: {d['metrics']}.\n"
        f"  - Buyer archetypes that are actually active here: {d['buyers']}.\n"
        f"  - Deal and diligence considerations to weight: {d['diligence']}.\n"
        f"Use these to shape the scoring criteria, the valuation framing, the company "
        f"types you surface, and the risks you flag. Where a metric above is standard "
        f"in this industry, prefer it over a generic ARR/EBITDA framing. Stay strictly "
        f"within {industry.strip()} and its adjacencies — do not drift into unrelated "
        f"industries.\n\n"
    )
