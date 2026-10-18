"""Coordinator logic: text in, markdown out. Talks to the other agents only through the
`ask_sponsorship` / `ask_jobs` callables it is given, so it runs the same over real uAgent
messaging (agent.py) or direct local calls (test_local.py).
"""
import asyncio
import logging
import re
from typing import Awaitable, Callable

from . import jobs as jobs_mod
from . import llm, sponsorship
from .data import H1BData, norm_company, _role_tokens
from .models import JobsRequest, JobsResponse, SponsorshipRequest, SponsorshipResponse

log = logging.getLogger("stamped.answer")

AskSponsorship = Callable[[SponsorshipRequest], Awaitable[SponsorshipResponse]]
AskJobs = Callable[[JobsRequest], Awaitable[JobsResponse]]

DISCLAIMER = ("_Past USCIS filings show history, not a promise: a company that sponsored before may not "
              "sponsor you, and one with no record might. Always confirm with the employer._")
GREETING = ("Hi, I'm **Stamped**. Tell me which companies and what role you're targeting "
            "(e.g. *\"Does Google or Stripe sponsor H-1B for software engineers?\"*), or ask me to find "
            "roles (*\"software engineer jobs in Los Angeles at companies that sponsor\"*) and I'll check "
            "H-1B sponsorship history before you spend time applying.")
MAX_COMPANIES = 8
JOBS_PER_COMPANY = 3


# ---------- fallback parsing when Gemini is unavailable ----------
_ALIASES = {"swe": "software engineer", "sde": "software engineer", "ds": "data scientist",
            "mle": "machine learning engineer", "ml": "machine learning"}


def _fallback_query(text: str, data: H1BData) -> llm.Query:
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
    roles = sorted({f.role for f in data.filings if _role_tokens(f.role) and _role_tokens(f.role) <= have},
                   key=lambda r: -len(_role_tokens(r)))
    return llm.Query(companies=sorted(employers), role=roles[0] if roles else "")


# ---------- calling the other agents safely ----------
async def _call(fn, req, what: str):
    """Returns (response | None, error message | None). Never raises."""
    try:
        resp = await fn(req)
    except Exception as e:
        log.warning("%s call failed: %s", what, e)
        return None, f"{what} agent unreachable"
    if resp is None:
        return None, f"{what} agent did not respond"
    if resp.error:
        return None, resp.error
    return resp, None


# ---------- formatting ----------
def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _job_line(j) -> str:
    title = f"[{j.title}]({j.url})" if j.url else j.title
    bits = [b for b in (j.location, f"posted {j.posted}" if j.posted else "") if b]
    return f"- {title}" + (f" ({', '.join(bits)})" if bits else "")


def _group_jobs(jobs) -> dict[str, list]:
    out: dict[str, list] = {}
    for j in jobs:
        out.setdefault(norm_company(j.company), []).append(j)
    return out


async def answer(text: str, ask_sponsorship: AskSponsorship, ask_jobs: AskJobs) -> str:
    text = (text or "").strip()
    if not text:
        return GREETING

    q = await asyncio.to_thread(llm.extract_query, text)
    degraded = q is None
    if degraded:
        try:
            q = _fallback_query(text, sponsorship.get_data())
        except Exception as e:
            log.warning("fallback parse failed: %s", e)
            return "Sorry, I couldn't process that right now. Please try again in a moment."
    companies = list(dict.fromkeys(c.strip() for c in q.companies if c.strip()))[:MAX_COMPANIES]
    role, location = q.role.strip(), q.location.strip()
    if not companies and not role:
        return ("I couldn't find a company or role in that. Try: *\"Does Stripe sponsor H-1B for data "
                "scientists?\"* or *\"software engineer jobs in Los Angeles at companies that sponsor\"*")

    notes: list[str] = []
    discovery = not companies
    if discovery:
        # jobs first, then check sponsorship of the employers that actually have openings
        jresp, jerr = await _call(ask_jobs, JobsRequest(role=role, location=location, limit=30), "Jobs")
        names = list(dict.fromkeys(j.company for j in (jresp.jobs if jresp else []) if j.company))[:MAX_COMPANIES * 2]
        if jerr:
            return f"I couldn't search for open roles right now ({jerr}). Tell me specific companies and I can still check their H-1B history."
        if not names:
            return f"I found no open **{role}** listings{' in ' + location if location else ''} right now. Try a broader location or name some companies."
        sresp, serr = await _call(ask_sponsorship, SponsorshipRequest(companies=names, role=role), "Sponsorship")
    else:
        (sresp, serr), (jresp, jerr) = await asyncio.gather(
            _call(ask_sponsorship, SponsorshipRequest(companies=companies, role=role), "Sponsorship"),
            _call(ask_jobs, JobsRequest(role=role, location=location, companies=companies, limit=15), "Jobs"),
        )

    if serr:
        notes.append(f"Sponsorship check unavailable ({serr}).")
    if jerr and not discovery:
        notes.append(f"Couldn't search open roles ({jerr}).")

    by_company = _group_jobs(jresp.jobs) if jresp else {}
    verdicts = sorted(sresp.verdicts, key=lambda v: -v.rank) if sresp else []
    if discovery:  # only worth showing employers we have data on, best first; mention the rest
        known = [v for v in verdicts if v.rank > 0]
        unknown = [v for v in verdicts if v.rank == 0]
        verdicts = known
    else:
        unknown = []

    out: list[str] = []
    if sresp and sresp.placeholder:
        out.append("⚠️ **Demo mode: placeholder data.** The numbers below are sample figures for development, not real filings.")
    title = "Roles ranked by H-1B sponsorship history" if discovery else "H-1B sponsorship check"
    out.append(f"### {title}" + (f" — {role}" if role else "") + (f", {location}" if location else ""))

    facts: list[str] = []
    used: set[str] = set()
    for v in verdicts:
        name = v.matched or v.company
        block = [f"**{name}**: {v.tier}", v.detail]
        mine = by_company.get(norm_company(v.matched or v.company), [])
        used.add(norm_company(v.matched or v.company))
        if mine:
            block.append(f"Open roles ({len(mine)}):\n" + "\n".join(_job_line(j) for j in mine[:JOBS_PER_COMPANY]))
        elif not discovery and jresp is not None:
            block.append("_No open listings found for this company on The Muse._")
        out.append("\n".join(block))
        facts.append(f"{name}: {v.tier}. {v.detail} Open roles found: {len(mine)}.")

    if discovery and unknown:
        names = ", ".join(sorted({v.company for v in unknown})[:8])
        out.append(f"_{_plural(len(unknown), 'other employer')} hiring for this role had no H-1B data: {names}._")
    if not discovery and jresp:
        extra = [j for k, js in by_company.items() if k not in used for j in js]
        if extra:
            out.append("**Other open roles matching your search:**\n" + "\n".join(_job_line(j) + f", {j.company}" for j in extra[:5]))
    if discovery and not verdicts and not serr:
        out.append("None of the employers hiring for this role appear in my H-1B data yet.")

    summary = None if (degraded or not facts) else await asyncio.to_thread(llm.summarize, text, "\n".join(facts))
    if summary:
        out.append(f"**Takeaway:** {summary}")
    if degraded:
        notes.append("AI parsing was unavailable, so I matched names directly; results may miss companies.")
    if notes:
        out.append("_" + " ".join(notes) + "_")
    out.append(DISCLAIMER)
    return "\n\n".join(out)


# ---------- local (single-process) wiring, used by test_local.py ----------
async def _local_sponsorship(req: SponsorshipRequest) -> SponsorshipResponse:
    return await asyncio.to_thread(sponsorship.check, req.companies, req.role)


async def _local_jobs(req: JobsRequest) -> JobsResponse:
    return await asyncio.to_thread(jobs_mod.find_jobs, req.role, req.location, req.companies, req.limit)


def build_answer(text: str) -> str:
    """Synchronous entry point that skips agent messaging (for local testing)."""
    return asyncio.run(answer(text, _local_sponsorship, _local_jobs))
