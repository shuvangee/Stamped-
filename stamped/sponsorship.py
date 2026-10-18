"""Sponsorship lookup (the sponsorship agent's tool). Pure functions; no uAgents needed."""
import logging

from .data import H1BData, load_data
from .models import SponsorshipResponse, VerdictModel

log = logging.getLogger("stamped.sponsorship")
_DATA: H1BData | None = None


def get_data() -> H1BData:
    global _DATA
    if _DATA is None:
        _DATA = load_data()
    return _DATA


def verdict(data: H1BData, company: str, role: str) -> VerdictModel:
    matched, rows = data.find_employer(company)
    if not rows:
        return VerdictModel(company=company, tier="⚪ No data", rank=0,
                            detail="Not found in the dataset. This doesn't mean they don't sponsor; check the name "
                                   "or the company's careers page.")

    role_rows = data.filter_role(rows, role) if role else []
    scoped = bool(role_rows)
    use = role_rows if scoped else rows
    if scoped or not role:
        note = ""
    elif not data.has_roles:
        note = " (source data is company-level, not split by role)"
    else:
        note = f" (no filings under “{role}”; showing all roles)"

    latest = data.latest_year
    recent_years = range(latest - 2, latest + 1)
    recent = [f for f in use if f.year in recent_years]
    recent_total = sum(f.approvals for f in recent)
    active_years = len({f.year for f in recent if f.approvals > 0})
    years_in_window = len({f.year for f in data.filings if f.year in recent_years})
    total = sum(f.approvals for f in use)
    denials = sum(f.denials for f in use)
    by_year: dict[int, int] = {}
    for f in use:
        by_year[f.year] = by_year.get(f.year, 0) + f.approvals
    history = ", ".join(f"{y}: {n}" for y, n in sorted(by_year.items()))
    rate = f", approval rate {total / (total + denials):.0%}" if data.has_denials and total + denials else ""

    if recent_total >= 50 and (active_years >= min(2, years_in_window) or recent_total >= 500):
        tier, rank = "✅ Strong sponsor", 4
    elif recent_total >= 10:
        tier, rank = "🟡 Likely sponsor", 3
    elif recent_total >= 1:
        tier, rank = "🟠 Limited / occasional", 2
    elif total > 0:
        tier, rank = "🔴 No recent filings", 1
    else:
        tier, rank = "⚪ No data", 0

    detail = (f"{recent_total} approval{'s' if recent_total != 1 else ''} in {latest - 2}–{latest}, "
              f"{total} total{rate}. By year: {history}.{note}")
    return VerdictModel(company=company, matched=matched or "", tier=tier, rank=rank, detail=detail)


def check(companies: list[str], role: str = "") -> SponsorshipResponse:
    """Never raises: failures come back in .error so callers can degrade gracefully."""
    try:
        data = get_data()
    except Exception as e:
        log.exception("data load failed")
        return SponsorshipResponse(error=f"H-1B dataset unavailable ({e})")
    seen, out = set(), []
    for c in companies:
        c = (c or "").strip()
        if c and c.lower() not in seen:
            seen.add(c.lower())
            out.append(verdict(data, c, role))
    return SponsorshipResponse(verdicts=out, placeholder=data.is_placeholder)
