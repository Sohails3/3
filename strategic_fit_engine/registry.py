"""
Companies House registry evidence from the arbitrex Postgres database (Neon).

The arbitrex pipeline (separate project: Documents/Projects/Strategic Fit Engine/tools)
loads UK software companies, their owners (PSCs), ownership-change deals and
filed accounts. This module reads that database to give the engine evidence
the model cannot invent:

  buyer_block()            buy-side Step 1: the buyer's UK acquisitions and what the
                           targets looked like the year before they were bought
  target_candidates_block()  buy-side Step 2: real, independent UK companies sized
                           like the buyer's past targets
  acquirer_candidates_block()  sell-side Step 2: UK companies with a track record of
                           buying businesses like the seller
  annotate()               after Step 2: match each surfaced UK company to the
                           register, attach filed figures and flag group ownership

Configuration: ARBITREX_DATABASE_URL in .env (the Neon connection string).
Every public function is a safe no-op when it is unset or the database fails:
it returns "" / [] / the input unchanged, so the engine behaves as before.
"""
from __future__ import annotations

import os
import re
import statistics
import time
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

SLICE_SICS = ["62011", "62012", "62020", "62090", "58290", "63110"]
SIC_LABELS = {
    "62011": "video game development", "62012": "business & domestic software",
    "62020": "IT consultancy", "62090": "other IT services", "58290": "software publishing",
    "63110": "data processing & hosting",
}
SOFTWARE_HINTS = ("software", "saas", "tech", "it ", "it/", "digital", "data", "ai", "cloud",
                  "cyber", "platform", "fintech", "edtech", "healthtech", "proptech", "insurtech",
                  "regtech", "legaltech", "martech", "analytics", "app", "internet", "computing")
UK_HINTS = ("uk", "united kingdom", "britain", "england", "scotland", "wales", "northern ireland",
            "europe", "emea", "global", "worldwide", "any", "london")
_LEGAL = re.compile(r"\b(the|limited|ltd|plc|llp|holdings?|group|uk|u\.k\.|co|company|inc|gmbh|"
                    r"international|topco|bidco|midco)\b\.?", re.I)


_DOWN_UNTIL = 0.0   # circuit breaker: after a failure, skip the registry for a few minutes


def _url() -> str:
    return os.environ.get("ARBITREX_DATABASE_URL", "").strip()


def is_enabled() -> bool:
    return bool(_url()) and time.time() >= _DOWN_UNTIL


def _connect():
    import psycopg  # imported lazily so the engine runs without the driver installed
    conn = psycopg.connect(_url(), connect_timeout=8, keepalives=1, keepalives_idle=30,
                           keepalives_interval=10, keepalives_count=3)
    with conn.cursor() as cur:
        cur.execute("set statement_timeout = '25s'")
    return conn


def _query(sql: str, params=None) -> List[tuple]:
    """Run a read query; return [] on any failure (logged, never raised)."""
    if not is_enabled():
        return []
    try:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params or {})
            return cur.fetchall()
    except Exception as e:  # noqa: BLE001
        global _DOWN_UNTIL
        print(f"  [registry] query skipped: {type(e).__name__}: {str(e).splitlines()[0][:160]}")
        import psycopg
        if isinstance(e, psycopg.OperationalError):   # connection-level: back off, don't retry per call
            _DOWN_UNTIL = time.time() + 300
            print("  [registry] database unreachable; Companies House evidence off for 5 minutes")
        return []


def core_name(name: str) -> str:
    """'The Access Group Ltd' -> 'access'. Used for matching company names loosely."""
    s = _LEGAL.sub(" ", (name or "").lower())
    s = re.sub(r"[^a-z0-9& ]", " ", s)
    return " ".join(s.split())


def _covers_uk(geography: str) -> bool:
    g = f" {(geography or '').lower()} "
    return any(h in g for h in UK_HINTS)


def _is_software(sector: str, industry: str = "") -> bool:
    s = f" {(sector or '').lower()} {(industry or '').lower()} "
    return any(h in s for h in SOFTWARE_HINTS)


def _money(x) -> str:
    if x is None:
        return "n/a"
    x = float(x)
    if abs(x) >= 1e6:
        return f"£{x / 1e6:.1f}m"
    if abs(x) >= 1e3:
        return f"£{x / 1e3:.0f}k"
    return f"£{x:.0f}"


def _sic_text(sics) -> str:
    return ", ".join(f"{s} {SIC_LABELS.get(s, '')}".strip() for s in (sics or [])[:2]) or "n/a"


# ---------------------------------------------------------------------------
# Buy side, Step 1: the buyer's UK acquisitions
# ---------------------------------------------------------------------------

_ACQ_SQL = """
with buyer_cos as (
  -- companies named like the buyer, plus companies the buyer-named entity controls
  select company_number from companies where name ~* %(rx)s
  union
  select p.company_number from pscs p
  where p.kind like 'corporate%%' and p.ceased_on is null and p.name ~* %(rx)s
)
select d.acquirer_name, d.deal_date, d.confidence, t.company_number, t.name, t.sic_codes,
       f.period_end, f.revenue, f.operating_profit, f.net_assets, f.employees
from deals d
join companies t on t.company_number = d.target_number
left join lateral (
  select * from financials f where f.company_number = d.target_number
    and f.period_end < d.deal_date and f.period_end >= d.deal_date - interval '24 months'
  order by f.period_end desc limit 1) f on true
where d.deal_type = 'acquisition'
  and (d.acquirer_number in (select company_number from buyer_cos) or d.acquirer_name ~* %(rx)s)
order by d.deal_date desc
limit 40
"""


_GENERIC = re.compile(r"\b(software|systems?|technolog(y|ies)|solutions|services|digital|"
                      r"global|europe|capital|partners)\b")


def _name_variants(name: str) -> List[str]:
    """Full core name first, then without generic words ('iris software' -> 'iris')."""
    core = core_name(name)
    out = [core] if len(core) >= 3 else []
    short = " ".join(_GENERIC.sub(" ", core).split())
    # a single short word ("iris") matches unrelated firms, so only fall back to distinctive names
    if short != core and (len(short) >= 7 or " " in short):
        out.append(short)
    return out


def buyer_acquisitions(buyer: str) -> List[Dict]:
    rows = []
    for core in _name_variants(buyer):
        rx = r"^(the )?" + re.escape(core) + r"\M"   # \M = end of word in Postgres regex
        rows = _query(_ACQ_SQL, {"rx": rx})
        if rows:
            break
    return [dict(acquirer=r[0], deal_date=r[1], confidence=float(r[2]), number=r[3], name=r[4],
                 sics=r[5], period_end=r[6], revenue=r[7], operating_profit=r[8],
                 net_assets=r[9], employees=r[10]) for r in rows]


def _size_band(acqs: List[Dict]) -> Dict:
    def med(key):
        vals = [float(a[key]) for a in acqs if a.get(key) not in (None, 0)]
        return statistics.median(vals) if vals else None
    return {"employees": med("employees"), "net_assets": med("net_assets"), "revenue": med("revenue"),
            "n_with_financials": sum(1 for a in acqs if a.get("period_end"))}


def to_json(acqs: List[Dict]) -> List[Dict]:
    """JSON-safe copy (dates as ISO strings, Decimals as floats) for buyer_profile.json."""
    out = []
    for a in acqs:
        row = {}
        for k, v in a.items():
            if isinstance(v, date):
                v = v.isoformat()
            elif v is not None and k in ("revenue", "operating_profit", "net_assets"):
                v = float(v)
            row[k] = v
        out.append(row)
    return out


def buyer_block(buyer: str, acqs: Optional[List[Dict]] = None) -> str:
    """Prompt block listing the buyer's UK acquisitions found in Companies House data."""
    acqs = buyer_acquisitions(buyer) if acqs is None else acqs
    if not acqs:
        return ""
    band = _size_band(acqs)
    lines = []
    for a in acqs[:15]:
        fin = (f"pre-deal accounts to {a['period_end']}: revenue {_money(a['revenue'])}, "
               f"net assets {_money(a['net_assets'])}, employees {a['employees'] or 'n/a'}"
               if a["period_end"] else "no pre-deal accounts on file")
        lines.append(f"  - {a['deal_date']:%Y-%m}: {a['name'].title()} ({a['number']}, "
                     f"{_sic_text(a['sics'])}) bought by {a['acquirer']} — {fin}")
    med_emp = f"{band['employees']:.0f}" if band["employees"] else "n/a"
    return (
        f"COMPANIES HOUSE EVIDENCE — {len(acqs)} UK acquisitions by {buyer} or its subsidiaries, "
        f"detected from ownership (PSC) filings. These are registry facts, not estimates; use them "
        f"in buyer_acquisitions, acquisition_pattern_summary, target_brief and dry_powder, and "
        f"prefer them over memory for UK deals. Buying entities were matched by name, so ignore "
        f"any that are clearly not part of {buyer}:\n" + "\n".join(lines) +
        f"\n  Typical UK target the year before purchase: median employees {med_emp}, median net "
        f"assets {_money(band['net_assets'])}"
        + (f", median revenue {_money(band['revenue'])}" if band["revenue"] else "") + ".\n\n"
    )


# ---------------------------------------------------------------------------
# Buy side, Step 2: candidate targets
# ---------------------------------------------------------------------------

_CAND_SQL = """
with latest as (
  select distinct on (company_number) company_number, period_end, revenue, net_assets, employees
  from financials where period_end >= current_date - interval '30 months'
  order by company_number, period_end desc
)
select c.company_number, c.name, c.sic_codes, c.incorporated_on, c.postcode,
       l.period_end, l.revenue, l.net_assets, l.employees
from companies c
join latest l on l.company_number = c.company_number
where c.status = 'Active' and c.sic_codes && %(sics)s
  and l.employees between %(emp_lo)s and %(emp_hi)s
  and c.incorporated_on <= current_date - interval '3 years'
  and not exists (   -- independent: no company holds a majority today
    select 1 from pscs p where p.company_number = c.company_number and p.ceased_on is null
      and p.kind like 'corporate%%'
      and exists (select 1 from unnest(p.natures_of_control) n
                  where n ~ '(ownership-of-shares|voting-rights)-(50-to-75|75-to-100)'))
  and not exists (select 1 from deals d where d.target_number = c.company_number
                  and d.deal_type in ('acquisition','intra_group','mbo'))
order by abs(ln(greatest(l.employees,1)::numeric / %(emp_mid)s)), l.revenue desc nulls last
limit %(limit)s
"""


def target_candidates(buyer_profile: Dict, sector: str, geography: str, industry: str = "",
                      limit: int = 30) -> List[Dict]:
    if not (is_enabled() and _covers_uk(geography)):
        return []
    acqs = (buyer_profile or {}).get("registry_acquisitions") or []
    sics = sorted({s for a in acqs for s in (a.get("sics") or []) if s in SLICE_SICS})
    if not sics:
        if not _is_software(sector, industry):
            return []   # the database only covers UK software / IT companies
        sics = SLICE_SICS
    emp_mid = None
    emps = [a["employees"] for a in acqs if a.get("employees")]
    if len(emps) >= 2:
        emp_mid = statistics.median(emps)
    emp_mid = max(emp_mid or 40, 5)
    rows = _query(_CAND_SQL, {"sics": sics, "emp_lo": max(5, int(emp_mid / 3)),
                              "emp_hi": int(emp_mid * 3) + 10, "emp_mid": emp_mid, "limit": limit})
    return [dict(number=r[0], name=r[1], sics=r[2], incorporated=r[3], postcode=r[4],
                 period_end=r[5], revenue=r[6], net_assets=r[7], employees=r[8]) for r in rows]


def target_candidates_block(buyer_profile: Dict, sector: str, geography: str,
                            industry: str = "") -> str:
    cands = target_candidates(buyer_profile, sector, geography, industry)
    if not cands:
        return ""
    lines = [f"  - {c['name'].title()} ({c['number']}; inc. {c['incorporated']:%Y}; "
             f"{_sic_text(c['sics'])}; {c['employees']} staff; net assets {_money(c['net_assets'])}"
             + (f"; revenue {_money(c['revenue'])}" if c["revenue"] else "")
             + f"; accounts to {c['period_end']})" for c in cands]
    return (
        "COMPANIES HOUSE CANDIDATES — real, active, independently owned UK companies (no corporate "
        "majority owner on the PSC register), sized like this buyer's past UK targets. Registry SIC "
        "codes are broad, so use web search to check what each one actually does. Include any that "
        "genuinely fit the buyer brief — they are exactly the non-obvious names bankers value — and "
        "ignore the rest. Use the registry figures (staff, net assets) rather than estimates:\n"
        + "\n".join(lines) + "\n\n"
    )


# ---------------------------------------------------------------------------
# Sell side, Step 2: acquirers with a UK track record
# ---------------------------------------------------------------------------

_SELLER_SQL = """
select company_number, name, sic_codes from companies
where status = 'Active' and lower(name) ~ %(rx)s
order by (lower(name) = %(exact)s) desc, incorporated_on limit 1
"""

_ACQUIRER_SQL = """
with buys as (
  select d.acquirer_number, d.acquirer_name, d.deal_date, t.name target,
         coalesce(par.name, d.acquirer_name) as grp
  from deals d
  join companies t on t.company_number = d.target_number
  left join lateral (   -- roll subsidiaries up to their controlling parent, one level
    select p.name from pscs p where p.company_number = d.acquirer_number and p.ceased_on is null
      and p.kind like 'corporate%%'
      and exists (select 1 from unnest(p.natures_of_control) n
                  where n ~ '(ownership-of-shares|voting-rights)-(50-to-75|75-to-100)')
    limit 1) par on true
  where d.deal_type = 'acquisition' and d.deal_date >= current_date - interval '6 years'
    and t.sic_codes && %(sics)s
)
select grp, count(*) n, max(deal_date) last_deal,
       (array_agg(target order by deal_date desc))[1:4] recent_targets,
       (array_agg(distinct acquirer_name))[1:3] buying_entities
from buys group by grp
order by count(*) desc, max(deal_date) desc
limit %(limit)s
"""


def acquirer_candidates(seller: str, sector: str, geography: str, industry: str = "",
                        limit: int = 20) -> List[Dict]:
    if not (is_enabled() and _covers_uk(geography)):
        return []
    sics = None
    core = core_name(seller)
    if len(core) >= 3:
        rows = _query(_SELLER_SQL, {"rx": r"^(the )?" + re.escape(core) + r"\M", "exact": seller.lower()})
        if rows:
            sics = [s for s in rows[0][2] if s in SLICE_SICS] or None
    if not sics:
        if not _is_software(sector, industry):
            return []
        sics = SLICE_SICS
    rows = _query(_ACQUIRER_SQL, {"sics": sics, "limit": limit})
    return [dict(group=r[0], deals=r[1], last_deal=r[2], recent_targets=r[3], entities=r[4])
            for r in rows]


def acquirer_candidates_block(seller: str, sector: str, geography: str, industry: str = "") -> str:
    acqs = acquirer_candidates(seller, sector, geography, industry)
    if not acqs:
        return ""
    lines = [f"  - {a['group']}: {a['deals']} UK acquisitions in 6 yrs, latest {a['last_deal']:%Y-%m} "
             f"(e.g. {', '.join(t.title() for t in a['recent_targets'][:3])})" for a in acqs]
    return (
        f"COMPANIES HOUSE EVIDENCE — UK groups that have actually bought companies like {seller} "
        f"in the last 6 years, detected from ownership (PSC) filings (counts are registry facts). "
        f"Serial buyers and PE-backed platforms here are strong acquirer candidates; include those "
        f"that fit, cite their real UK deals in relevant_ma, and still add strategic/international "
        f"buyers the registry cannot see:\n" + "\n".join(lines) + "\n\n"
    )


# ---------------------------------------------------------------------------
# After Step 2: annotate surfaced companies with registry facts
# ---------------------------------------------------------------------------

_MATCH_SQL = """
with wanted(core) as (select unnest(%(cores)s::text[]))
select w.core, c.company_number, c.name, c.status, c.incorporated_on, c.sic_codes,
       f.period_end, f.revenue, f.net_assets, f.employees,
       own.name as owner, own.notified_on as owned_since,
       (select count(*) from deals d where d.acquirer_number = c.company_number
          and d.deal_type = 'acquisition') as uk_acquisitions
from wanted w
join companies c on regexp_replace(regexp_replace(lower(c.name),
       '\\m(the|limited|ltd|plc|llp|holdings?|group|uk|co|company)\\M\\.?', ' ', 'g'),
       '[^a-z0-9& ]', ' ', 'g') ~ ('^\\s*' || w.core || '\\s*$')
left join lateral (select * from financials f where f.company_number = c.company_number
                   order by period_end desc limit 1) f on true
left join lateral (select p.name, p.notified_on from pscs p
                   where p.company_number = c.company_number and p.ceased_on is null
                     and p.kind like 'corporate%%'
                     and exists (select 1 from unnest(p.natures_of_control) n
                                 where n ~ '(ownership-of-shares|voting-rights)-(50-to-75|75-to-100)')
                   limit 1) own on true
where c.status = 'Active'
"""


def annotate(targets: List[Dict]) -> List[Dict]:
    """Attach t['companies_house'] to UK companies found in the registry. Returns targets."""
    if not is_enabled() or not targets:
        return targets
    uk = [t for t in targets if any(h in (t.get("country") or "").lower()
                                    for h in ("uk", "united kingdom", "england", "scotland", "wales",
                                              "britain", "northern ireland"))]
    cores = sorted({re.sub(r"\s+", r"\\s+", re.escape(core_name(t.get("name", ""))))
                    for t in uk if len(core_name(t.get("name", ""))) >= 3})
    if not cores:
        return targets
    rows = _query(_MATCH_SQL, {"cores": cores})
    by_core: Dict[str, List[tuple]] = {}
    for r in rows:
        by_core.setdefault(r[0], []).append(r)
    for t in uk:
        key = re.sub(r"\s+", r"\\s+", re.escape(core_name(t.get("name", ""))))
        hits = by_core.get(key) or []
        if not hits:
            continue
        # prefer the trading company with the most recent accounts
        r = sorted(hits, key=lambda h: (h[6] or date.min), reverse=True)[0]
        t["companies_house"] = {
            "company_number": r[1], "registered_name": r[2], "status": r[3],
            "incorporated": str(r[4]) if r[4] else None, "sic_codes": r[5],
            "accounts_period_end": str(r[6]) if r[6] else None,
            "revenue_gbp": float(r[7]) if r[7] is not None else None,
            "net_assets_gbp": float(r[8]) if r[8] is not None else None,
            "employees": r[9],
            "majority_owner": r[10], "owned_since": str(r[11]) if r[11] else None,
            "uk_acquisitions": int(r[12] or 0),
            "matches": len(hits),
        }
    return targets


def annotation_summary(targets: List[Dict]) -> Dict[str, int]:
    ch = [t["companies_house"] for t in targets if t.get("companies_house")]
    return {"matched": len(ch), "group_owned": sum(1 for c in ch if c.get("majority_owner")),
            "with_accounts": sum(1 for c in ch if c.get("accounts_period_end"))}
