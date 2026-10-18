"""Jobs lookup (the jobs agent's tool).

Source: The Muse public API (https://www.themuse.com/api/public/jobs). Free, no key needed
(500 requests/hour unauthenticated). It has no free-text search, only category / location /
company filters, so roles are mapped to Muse categories. Coverage is partial: many big
employers aren't on it, and we say so rather than invent listings.

To plug in another source (Adzuna, USAJobs, ...) add a function with the SourceFn signature
to SOURCES and set JOBS_SOURCE=<name>.
"""
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from .data import norm_company
from .models import JobModel, JobsResponse

log = logging.getLogger("stamped.jobs")
SourceFn = Callable[[str, str, list[str], int], list[JobModel]]

_MUSE_URL = "https://www.themuse.com/api/public/jobs"
# keyword -> Muse category (first match wins)
_CATEGORY_RULES = [
    (r"machine learning|data scien|\bml\b|\bai\b", "Data Science"),
    (r"data analy|analytics|business intelligence|\bbi\b", "Data and Analytics"),
    (r"software|developer|engineer|swe|backend|frontend|front-end|back-end|full.?stack|devops|sre", "Software Engineering"),
    (r"product manag", "Product Management"),
    (r"design|ux|ui\b", "Design and UX"),
]


def muse_category(role: str) -> str | None:
    r = role.lower()
    return next((cat for pat, cat in _CATEGORY_RULES if re.search(pat, r)), None)


def _muse_company_name(name: str) -> str:
    return norm_company(name).title()  # "STRIPE INC" -> "Stripe"


def _get_json(url: str, retries: int = 1) -> dict:
    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "stamped-hackathon/0.1"})
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = e
    raise RuntimeError(f"{type(last).__name__}: {last}")


def muse_source(role: str, location: str, companies: list[str], limit: int) -> list[JobModel]:
    params: list[tuple[str, str]] = [("descending", "true")]
    cat = muse_category(role)
    if cat:
        params.append(("category", cat))
    if location:
        params.append(("location", location))
    params += [("company", _muse_company_name(c)) for c in companies if c.strip()]
    tokens = {w[:5] for w in re.findall(r"[a-z]+", role.lower())} - {"senio", "junio", "staff"}

    jobs: list[JobModel] = []
    for page in range(0, 3):  # up to 3 pages of 20
        data = _get_json(_MUSE_URL + "?" + urllib.parse.urlencode(params + [("page", str(page))]))
        for j in data.get("results", []):
            title = j.get("name", "")
            # no category match => filter by title words so "chef" doesn't return random jobs
            if not cat and tokens and not tokens & {w[:5] for w in re.findall(r"[a-z]+", title.lower())}:
                continue
            jobs.append(JobModel(
                title=title,
                company=(j.get("company") or {}).get("name", ""),
                location=", ".join(l.get("name", "") for l in j.get("locations", [])[:2]),
                url=(j.get("refs") or {}).get("landing_page", ""),
                posted=(j.get("publication_date") or "")[:10],
            ))
        if len(jobs) >= limit or page + 1 >= data.get("page_count", 0):
            break
    return jobs[:limit]


SOURCES: dict[str, SourceFn] = {"muse": muse_source}


def find_jobs(role: str, location: str = "", companies: list[str] | None = None, limit: int = 10) -> JobsResponse:
    """Never raises: failures come back in .error."""
    name = os.environ.get("JOBS_SOURCE", "muse")
    try:
        jobs = SOURCES[name](role, location, companies or [], max(1, min(limit, 30)))
        return JobsResponse(jobs=jobs, source=name)
    except Exception as e:
        log.warning("jobs source %s failed: %s", name, e)
        return JobsResponse(source=name, error=f"{name} unavailable ({e})")
