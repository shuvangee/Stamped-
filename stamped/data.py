"""Load H-1B filing history from CSV and look up employers.

CSV columns: employer, role, year, approvals, denials (denials optional).
Aliases accepted: job_title -> role, filings -> approvals.
Lines starting with '#' are comments; a comment containing PLACEHOLDER marks
the file as placeholder data so answers can say so.
"""
import csv
import difflib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Real data (produced by scripts/prepare_h1b.py in M2) wins over the sample.
DEFAULT_PATHS = [ROOT / "data" / "h1b_real.csv", ROOT / "h1b_sample.csv"]

_SUFFIXES = {"inc", "llc", "corp", "corporation", "co", "ltd", "lp", "plc", "company", "incorporated", "limited"}
_ALIASES = {"job_title": "role", "filings": "approvals"}
_STOP = {"and", "of", "the", "a", "an", "for", "in", "at"}


def norm_company(name: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", " ", name.lower().replace("&", " and ")).split()
    words = [w for w in words if w not in _SUFFIXES]
    return " ".join(words)


def _role_tokens(role: str) -> set[str]:
    # 5-char prefixes so "engineer" ~ "engineering", "analyst" ~ "analytics"
    return {w[:5] for w in re.findall(r"[a-z0-9]+", role.lower()) if w not in _STOP}


@dataclass
class Filing:
    employer: str
    role: str
    year: int
    approvals: int
    denials: int


@dataclass
class H1BData:
    filings: list[Filing]
    source: str
    is_placeholder: bool
    by_company: dict[str, list[Filing]] = field(default_factory=dict)

    @property
    def has_denials(self) -> bool:
        return any(f.denials for f in self.filings)

    @property
    def latest_year(self) -> int:
        return max((f.year for f in self.filings), default=0)

    def find_employer(self, name: str) -> tuple[str | None, list[Filing]]:
        """Return (canonical employer name, its filings), or (None, [])."""
        key = norm_company(name)
        if not key:
            return None, []
        if key in self.by_company:
            rows = self.by_company[key]
            return rows[0].employer, rows
        # one name contains the other as whole words (e.g. "google" vs "google llc dba x")
        for k, rows in self.by_company.items():
            if f" {key} " in f" {k} " or f" {k} " in f" {key} ":
                return rows[0].employer, rows
        close = difflib.get_close_matches(key, list(self.by_company), n=1, cutoff=0.85)
        if close:
            rows = self.by_company[close[0]]
            return rows[0].employer, rows
        return None, []

    @staticmethod
    def filter_role(rows: list[Filing], role: str) -> list[Filing]:
        want = _role_tokens(role)
        if not want:
            return []
        return [f for f in rows if want <= _role_tokens(f.role)]


def load_data(path: str | os.PathLike | None = None) -> H1BData:
    candidates = [Path(path)] if path else (
        [Path(os.environ["H1B_DATA_PATH"])] if os.environ.get("H1B_DATA_PATH") else DEFAULT_PATHS
    )
    chosen = next((p for p in candidates if p.is_file()), None)
    if chosen is None:
        raise FileNotFoundError(f"No H-1B data file found (looked at: {', '.join(map(str, candidates))})")

    placeholder = False
    lines = []
    with open(chosen, newline="", encoding="utf-8-sig") as fh:
        for line in fh:
            if line.lstrip().startswith("#"):
                placeholder = placeholder or "PLACEHOLDER" in line.upper()
            elif line.strip():
                lines.append(line)

    filings: list[Filing] = []
    for row in csv.DictReader(lines):
        row = {_ALIASES.get(k.strip().lower(), k.strip().lower()): v for k, v in row.items() if k}
        try:
            filings.append(Filing(
                employer=row["employer"].strip(),
                role=row["role"].strip(),
                year=int(row["year"]),
                approvals=int(float(row["approvals"] or 0)),
                denials=int(float(row.get("denials") or 0)),
            ))
        except (KeyError, ValueError, AttributeError):
            continue  # skip malformed rows rather than crash the agent

    by_company: dict[str, list[Filing]] = {}
    for f in filings:
        by_company.setdefault(norm_company(f.employer), []).append(f)
    return H1BData(filings, str(chosen), placeholder, by_company)
