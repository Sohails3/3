"""
Companies House API — UK company enrichment utility.

Looks up UK companies by name and attempts to retrieve:
  - Company profile (number, status, SIC codes, incorporation date)
  - Revenue / turnover, gross profit, and profit before tax from the
    latest filed iXBRL accounts document.

Requires COMPANIES_HOUSE_API_KEY in .env (free key at
https://developer.company-information.service.gov.uk/).

Returns None gracefully if the key is missing, the company is not
found, or the accounts document cannot be parsed.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

BASE_URL  = "https://api.company-information.service.gov.uk"
DOC_BASE  = "https://document-api.company-information.service.gov.uk"
TIMEOUT   = 8

# iXBRL concept names that hold revenue / profit figures
_REVENUE_CONCEPTS = [
    "core:Turnover",
    "uk-bus:TurnoverRevenue",
    "bus:TurnoverRevenue",
    "uk-bus:Turnover",
    "core:Revenue",
]
_GROSS_PROFIT_CONCEPTS = [
    "core:GrossProfit",
    "uk-bus:GrossProfit",
]
_PROFIT_CONCEPTS = [
    "core:ProfitLossBeforeTax",
    "uk-bus:ProfitLossBeforeTax",
    "core:ProfitBeforeTax",
    "uk-gaap:ProfitLossBeforeTax",
]
_EBITDA_CONCEPTS = [
    "core:OperatingProfit",
    "uk-bus:OperatingProfit",
]


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _session(api_key: str) -> requests.Session:
    s = requests.Session()
    s.auth = (api_key, "")
    s.headers.update({"Accept": "application/json"})
    return s


def _search_company(session: requests.Session, name: str) -> Optional[str]:
    """Return the company_number of the best name-match, or None."""
    try:
        r = session.get(f"{BASE_URL}/search/companies",
                        params={"q": name, "items_per_page": 5},
                        timeout=TIMEOUT)
        r.raise_for_status()
    except Exception:
        return None

    items = r.json().get("items", [])
    if not items:
        return None

    name_lower = name.lower().strip()
    # Prefer an exact (case-insensitive) match; fall back to first result
    for item in items:
        if item.get("title", "").lower().strip() == name_lower:
            return item["company_number"]
    return items[0]["company_number"]


def _company_profile(session: requests.Session, number: str) -> Optional[Dict]:
    try:
        r = session.get(f"{BASE_URL}/company/{number}", timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _latest_accounts_doc_url(session: requests.Session, number: str) -> Optional[str]:
    """
    Walk filing-history → document_metadata → document download URL.
    Returns a URL to the iXBRL accounts document, or None.
    """
    try:
        r = session.get(
            f"{BASE_URL}/company/{number}/filing-history",
            params={"category": "accounts", "items_per_page": 5},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        items = r.json().get("items", [])
    except Exception:
        return None

    if not items:
        return None

    # Most recent accounts filing
    filing = items[0]
    meta_url = (filing.get("links") or {}).get("document_metadata")
    if not meta_url:
        return None

    # Fetch document metadata to get the actual download link
    try:
        r2 = session.get(meta_url, timeout=TIMEOUT)
        r2.raise_for_status()
        meta = r2.json()
    except Exception:
        return None

    resources = meta.get("resources") or {}
    # Prefer iXBRL/XHTML; avoid PDF
    preferred = ["application/xhtml+xml", "text/html"]
    for mime in preferred:
        if mime in resources:
            return meta.get("links", {}).get("document")

    return None


def _parse_ixbrl_figures(html: str) -> Dict[str, Optional[float]]:
    """
    Extract key financial figures from an iXBRL HTML document.
    Values in the filing are in GBP (pence or pounds depending on scale).
    Returns dict with keys: revenue, gross_profit, ebitda, profit_before_tax.
    All values are in £ millions, rounded to 1 d.p., or None.
    """
    results: Dict[str, Optional[float]] = {
        "revenue": None,
        "gross_profit": None,
        "ebitda": None,
        "profit_before_tax": None,
    }

    def _find_concept(concepts: List[str]) -> Optional[float]:
        for concept in concepts:
            # Match ix:nonFraction or ix:nonNumeric with the concept name
            pattern = (
                r'<ix:nonFraction[^>]*'
                r'name\s*=\s*["\']' + re.escape(concept) + r'["\']'
                r'[^>]*>'
                r'\s*([\d,\-\.]+)\s*'
                r'</ix:nonFraction>'
            )
            matches = re.findall(pattern, html, re.IGNORECASE | re.DOTALL)
            if matches:
                # Take the largest absolute value (usually the consolidated figure)
                try:
                    vals = [float(m.replace(",", "")) for m in matches]
                    return max(vals, key=abs)
                except ValueError:
                    continue
        return None

    # Also check for scale attribute — some filings report in thousands or pence
    def _apply_scale(raw: Optional[float], html_local: str, concept: str) -> Optional[float]:
        if raw is None:
            return None
        # Look for scale / decimals attribute near this concept
        pattern = (
            r'<ix:nonFraction[^>]*'
            r'name\s*=\s*["\']' + re.escape(concept) + r'["\']'
            r'[^>]*(?:scale|decimals)\s*=\s*["\']([^"\']*)["\']'
        )
        m = re.search(pattern, html_local, re.IGNORECASE)
        if m:
            try:
                scale_exp = int(m.group(1))
                # scale=3 means thousands; scale=6 means millions; scale=-6 means pence?
                # In iXBRL, `decimals="-3"` means the number is in thousands.
                # We want millions, so adjust accordingly.
                if scale_exp >= 6:
                    return round(raw / 1_000_000, 1)  # already given in millions or above
                elif scale_exp >= 3:
                    return round(raw / 1_000, 1)       # thousands → millions
                elif scale_exp <= -6:
                    return round(raw / 1_000_000, 1)   # pence/units given as full
            except ValueError:
                pass
        # Heuristic: if the raw value is very large, assume it's in pence or units
        if abs(raw) > 1_000_000:
            return round(raw / 1_000_000, 1)
        elif abs(raw) > 1_000:
            return round(raw / 1_000, 1)
        return round(raw, 1)

    rev_raw = _find_concept(_REVENUE_CONCEPTS)
    results["revenue"] = _apply_scale(rev_raw, html, _REVENUE_CONCEPTS[0])

    gp_raw = _find_concept(_GROSS_PROFIT_CONCEPTS)
    results["gross_profit"] = _apply_scale(gp_raw, html, _GROSS_PROFIT_CONCEPTS[0])

    ebitda_raw = _find_concept(_EBITDA_CONCEPTS)
    results["ebitda"] = _apply_scale(ebitda_raw, html, _EBITDA_CONCEPTS[0])

    pbt_raw = _find_concept(_PROFIT_CONCEPTS)
    results["profit_before_tax"] = _apply_scale(pbt_raw, html, _PROFIT_CONCEPTS[0])

    return results


def _fetch_ixbrl(session: requests.Session, doc_url: str) -> Optional[str]:
    """Download the iXBRL document content as a string."""
    try:
        r = session.get(
            doc_url,
            headers={"Accept": "application/xhtml+xml, text/html"},
            timeout=15,
        )
        r.raise_for_status()
        return r.text
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def lookup(company_name: str, api_key: Optional[str] = None) -> Optional[Dict]:
    """
    Look up a UK company by name and return enrichment data.

    Returns a dict with:
        company_number, status, sic_codes, incorporated,
        registered_address, accounts_made_up_to,
        revenue_gbp_m, gross_profit_gbp_m, ebitda_gbp_m, profit_before_tax_gbp_m

    Returns None if no API key, company not found, or any error occurs.
    All financial values are in £ millions (may be None if unavailable).
    """
    key = api_key or os.environ.get("COMPANIES_HOUSE_API_KEY", "")
    if not key:
        return None

    session = _session(key)

    company_number = _search_company(session, company_name)
    if not company_number:
        return None

    profile = _company_profile(session, company_number)
    if not profile:
        return None

    # Basic profile fields
    addr = profile.get("registered_office_address") or {}
    result: Dict[str, Any] = {
        "company_number": company_number,
        "status": profile.get("company_status", "unknown"),
        "sic_codes": profile.get("sic_codes", []),
        "incorporated": profile.get("date_of_creation"),
        "registered_address": ", ".join(filter(None, [
            addr.get("address_line_1"),
            addr.get("locality"),
            addr.get("postal_code"),
        ])),
        "accounts_made_up_to": (
            (profile.get("accounts") or {})
            .get("last_accounts", {})
            .get("made_up_to")
        ),
        "revenue_gbp_m": None,
        "gross_profit_gbp_m": None,
        "ebitda_gbp_m": None,
        "profit_before_tax_gbp_m": None,
        "source": "Companies House API (live)",
    }

    # Attempt to get financial figures from iXBRL accounts
    doc_url = _latest_accounts_doc_url(session, company_number)
    if doc_url:
        html = _fetch_ixbrl(session, doc_url)
        if html:
            figures = _parse_ixbrl_figures(html)
            result["revenue_gbp_m"]           = figures.get("revenue")
            result["gross_profit_gbp_m"]      = figures.get("gross_profit")
            result["ebitda_gbp_m"]            = figures.get("ebitda")
            result["profit_before_tax_gbp_m"] = figures.get("profit_before_tax")

    return result


def enrich_targets(targets: List[Dict], api_key: Optional[str] = None) -> List[Dict]:
    """
    Attempt Companies House enrichment for each target in-place.
    Only UK-domiciled companies are looked up (country contains 'UK' or 'United Kingdom').
    Non-UK companies get a ch_data key of None.
    """
    key = api_key or os.environ.get("COMPANIES_HOUSE_API_KEY", "")
    for t in targets:
        country = str(t.get("country", "")).lower()
        is_uk   = any(x in country for x in ("uk", "united kingdom", "england", "scotland", "wales"))
        if is_uk and key:
            ch = lookup(t.get("name", ""), api_key=key)
            t["ch_data"] = ch
        else:
            t["ch_data"] = None
    return targets


# ──────────────────────────────────────────────────────────────────────────────
# Standalone test
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    name = sys.argv[1] if len(sys.argv) > 1 else "Babylon Health"
    print(f"\nLooking up: {name}")
    data = lookup(name)
    if data:
        import json
        print(json.dumps(data, indent=2, default=str))
    else:
        print("Not found or no API key set (add COMPANIES_HOUSE_API_KEY to .env)")
