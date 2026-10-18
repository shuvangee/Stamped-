"""Messages exchanged between the Stamped agents (uAgents models)."""
from uagents import Model


class VerdictModel(Model):
    company: str          # as the user wrote it
    matched: str = ""     # employer name found in the data ("" if none)
    tier: str             # emoji + label, e.g. "✅ Strong sponsor"
    rank: int             # higher = better; 0 = no data
    detail: str


class SponsorshipRequest(Model):
    companies: list[str]
    role: str = ""


class SponsorshipResponse(Model):
    verdicts: list[VerdictModel] = []
    placeholder: bool = False   # True when answering from the placeholder sample file
    error: str = ""


class JobModel(Model):
    title: str
    company: str
    location: str = ""
    url: str = ""
    posted: str = ""


class JobsRequest(Model):
    role: str
    location: str = ""
    companies: list[str] = []   # optional: only these employers
    limit: int = 10


class JobsResponse(Model):
    jobs: list[JobModel] = []
    source: str = ""
    error: str = ""
