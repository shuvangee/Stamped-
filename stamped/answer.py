"""build_answer(): message text in, markdown reply out. No uAgents imports, so it's testable alone."""
import logging
import re
from dataclasses import dataclass

from . import llm
from .data import H1BData, Filing, load_data, norm_company, _role_tokens

log = logging.getLogger("stamped.answer")
_DATA: H1BData | None = None

DISCLAIMER = ("_Past USCIS filings show history, not a promise: a company that sponsored before may not "
              "sponsor you, and one with no record might. Always confirm with the employer._")
GREETING = ("Hi, I'm **Stamped**. Tell me which companies and what role you're targeting "
            "(e.g. *\"Does Google or Stripe sponsor H-1B for software engineers?\"*) and I'll check "
            "their H-1B sponsorship history before you spend time applying.")


def get_data() -> H1BData:
    global _DATA
    if _DATA is None:
        _DATA = load_data()
    return _DATA


@dataclass
class Verdict:
    company: str            # as the user wrote it
    matched: str | None     # employer name in the data
    tier: str               # emoji + label
    rank: int               # higher = better, for sorting
    detail: str


def _verdict(data: H1BData, company: str, role: str) -> Verdict:
    matched, rows = data.find_employer(company)
    if not rows:
        return Verdict(company, None, "⚪ No data", 0,
                       "Not found in the dataset. This doesn't mean they don't sponsor; check the name or the "
                       "company's careers page.")

    role_rows = data.filter_role(rows, role) if role else []
    scoped = bool(role_rows)
    use = role_rows if scoped else rows
    note = "" if scoped or not role else f" (no filings under “{role}”; showing all roles)"

    latest = data.latest_year
    recent_years = range(latest - 2, latest + 1)
    recent = [f for f in use if f.year in recent_years]
    recent_total = sum(f.approvals for f in recent)
    active_years = len({f.year for f in recent if f.approvals > 0})
    total = sum(f.approvals for f in use)
    denials = sum(f.denials for f in use)
    by_year = {}
    for f in use:
        by_year[f.year] = by_year.get(f.year, 0) + f.approvals
    history = ", ".join(f"{y}: {n}" for y, n in sorted(by_year.items()))
    rate = f", approval rate {total / (total + denials):.0%}" if data.has_denials and total + denials else ""

    years_in_window = len({f.year for f in data.filings if f.year in recent_years})
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

    detail = (f"{recent_total} approval{'s' if recent_total != 1 else ''} in {latest - 2}–{latest}, {total} total{rate}. "
              f"By year: {history}.{note}")
    return Verdict(company, matched, tier, rank, detail)


_ALIASES = {"swe": "software engineer", "sde": "software engineer", "ds": "data scientist",
            "mle": "machine learning engineer", "ml": "machine learning"}


def _fallback_query(text: str, data: H1BData) -> llm.Query:
    """Used when Gemini is unavailable: match known employers/roles by substring."""
    low = f" {norm_company(text)} "
    employers = {f.employer for f in data.filings if f" {norm_company(f.employer)} " in low}
    # also match a unique, distinctive first word ("amazon" -> "AMAZON.COM SERVICES LLC")
    firsts: dict[str, set[str]] = {}
    for f in data.filings:
        w = norm_company(f.employer).split()[:1]
        if w and len(w[0]) >= 5:
            firsts.setdefault(w[0], set()).add(f.employer)
    for w, names in firsts.items():
        if len(names) == 1 and f" {w} " in low:
            employers |= names
    # strip company names so e.g. "Demo Analytics" doesn't look like a role
    rest = text.lower()
    for e in employers:
        rest = re.sub(re.escape(norm_company(e)), " ", rest)
    words = [_ALIASES.get(w, w) for w in re.findall(r"[a-z0-9]+", rest)]
    have = {w[:5] for w in " ".join(words).split()}
    roles = sorted({f.role for f in data.filings if _role_tokens(f.role) <= have and _role_tokens(f.role)},
                   key=lambda r: -len(_role_tokens(r)))
    return llm.Query(companies=sorted(employers), role=roles[0] if roles else "")


def build_answer(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return GREETING
    try:
        data = get_data()
    except Exception as e:
        log.exception("data load failed")
        return f"Sorry, my H-1B dataset isn't available right now ({e}). Please try again shortly."

    q = llm.extract_query(text)
    degraded = q is None
    if degraded:
        q = _fallback_query(text, data)
    companies = list(dict.fromkeys(c.strip() for c in q.companies if c.strip()))
    if not companies:
        return ("I couldn't find a company name in that. Try something like: "
                "*\"Does Stripe sponsor H-1B for data scientists?\"*")

    verdicts = sorted((_verdict(data, c, q.role) for c in companies), key=lambda v: -v.rank)

    out = []
    if data.is_placeholder:
        out.append("⚠️ **Demo mode: placeholder data.** The numbers below are sample figures for development, not real filings.")
    out.append(f"### H-1B sponsorship check" + (f" — {q.role}" if q.role else ""))
    for v in verdicts:
        name = v.matched or v.company
        out.append(f"**{name}**: {v.tier}\n{v.detail}")

    facts = "\n".join(f"{v.matched or v.company}: {v.tier}. {v.detail}" for v in verdicts)
    summary = None if degraded else llm.summarize(text, facts)
    if summary:
        out.append(f"**Takeaway:** {summary}")
    if degraded:
        out.append("_(AI parsing was unavailable, so I matched names directly; results may miss companies.)_")
    out.append(DISCLAIMER)
    return "\n\n".join(out)
