#!/usr/bin/env python3
"""Convert a manually downloaded H-1B file into Stamped's format.

Output columns: employer, role, year, approvals, denials  (written to data/h1b_real.csv)

Accepted inputs (auto-detected from the headers; CSV, TSV, UTF-8/UTF-16, or .xlsx):

  1. USCIS H-1B Employer Data Hub export. Company-level only: the hub has NO job title,
     so role is written as "All roles". approvals = Initial + Continuing Approval.
  2. DOL OFLC LCA disclosure file (has JOB_TITLE / SOC_TITLE). Only VISA_CLASS=H-1B rows.
     approvals = worker positions on CERTIFIED LCAs. An LCA certification is a *precursor*
     to a petition, not a USCIS approval, so the output header says so.

Nothing is downloaded and nothing is invented. Usage:

  python scripts/prepare_h1b.py data/raw/uscis_hub.csv
  python scripts/prepare_h1b.py data/raw/LCA_Disclosure_Data_FY2025_Q3.xlsx --min-approvals 5
  python scripts/prepare_h1b.py a.csv b.csv -o data/h1b_real.csv   # same source type only
"""
import argparse
import csv
import io
import re
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "data" / "h1b_real.csv"
ALL_ROLES = "All roles"


def _key(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (h or "").lower())


def _find(headers: dict[str, str], *candidates: str) -> str | None:
    """headers maps normalised -> original. Exact match first, then substring."""
    for c in candidates:
        if c in headers:
            return headers[c]
    for c in candidates:
        for k, orig in headers.items():
            if c in k:
                return orig
    return None


def _num(v) -> int:
    if v is None:
        return 0
    s = str(v).replace(",", "").strip()
    if s in ("", "-", "NA", "N/A"):
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def _clean_employer(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip().upper()


def read_rows(path: Path):
    """Yield dict rows from CSV/TSV (sniffing encoding + delimiter) or xlsx."""
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        try:
            import openpyxl
        except ImportError:
            sys.exit("Reading .xlsx needs openpyxl:  pip install openpyxl  (or export the sheet to CSV).")
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        it = wb.active.iter_rows(values_only=True)
        header = [str(h) if h is not None else "" for h in next(it)]
        for r in it:
            yield dict(zip(header, r))
        return

    raw = path.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = raw.decode("utf-16")
    else:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252")
    first = text.splitlines()[0] if text else ""
    delim = "\t" if first.count("\t") > first.count(",") else ","
    yield from csv.DictReader(io.StringIO(text), delimiter=delim)


def detect(headers: list[str]) -> str:
    keys = {_key(h) for h in headers}
    if any("initialapproval" in k for k in keys) or any("continuingapproval" in k for k in keys):
        return "uscis"
    if any(k in keys for k in ("casestatus", "visaclass", "totalworkerpositions")) and any(
        "jobtitle" in k or "soctitle" in k for k in keys
    ):
        return "dol"
    return "unknown"


def _fiscal_year(d) -> int | None:
    if isinstance(d, (datetime, date)):
        dt = d
    else:
        s = str(d or "").strip()[:10]
        dt = None
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                pass
        if dt is None:
            return None
    return dt.year + 1 if dt.month >= 10 else dt.year


def aggregate_uscis(rows, headers) -> dict:
    h = {_key(x): x for x in headers}
    c_emp = _find(h, "employerpetitionername", "employername", "employer", "petitionername")
    c_year = _find(h, "fiscalyear", "year")
    c_ia, c_id = _find(h, "initialapproval"), _find(h, "initialdenial")
    c_ca, c_cd = _find(h, "continuingapproval"), _find(h, "continuingdenial")
    missing = [n for n, c in (("employer", c_emp), ("fiscal year", c_year), ("initial approval", c_ia)) if not c]
    if missing:
        sys.exit(f"USCIS file is missing expected column(s): {', '.join(missing)}. Headers seen: {headers}")
    out: dict = defaultdict(lambda: [0, 0])
    for r in rows:
        emp = _clean_employer(r.get(c_emp))
        year = _num(r.get(c_year))
        if not emp or not year:
            continue
        a = _num(r.get(c_ia)) + _num(r.get(c_ca)) if c_ca else _num(r.get(c_ia))
        d = (_num(r.get(c_id)) if c_id else 0) + (_num(r.get(c_cd)) if c_cd else 0)
        out[(emp, ALL_ROLES, year)][0] += a
        out[(emp, ALL_ROLES, year)][1] += d
    return out


def aggregate_dol(rows, headers, year_override=None) -> dict:
    h = {_key(x): x for x in headers}
    c_emp = _find(h, "employername", "employer")
    c_role = _find(h, "soctitle") or _find(h, "jobtitle")
    c_status = _find(h, "casestatus")
    c_visa = _find(h, "visaclass")
    c_n = _find(h, "totalworkerpositions")
    c_date = _find(h, "decisiondate", "receiveddate", "begindate")
    if not (c_emp and c_role and c_status):
        sys.exit(f"DOL file is missing expected column(s). Headers seen: {headers}")
    if not year_override and not c_date:
        sys.exit("No date column found to derive fiscal year; pass --year.")
    out: dict = defaultdict(lambda: [0, 0])
    for r in rows:
        if c_visa and str(r.get(c_visa) or "").strip().upper() != "H-1B":
            continue
        status = str(r.get(c_status) or "").strip().lower()
        emp = _clean_employer(r.get(c_emp))
        role = re.sub(r"\s+", " ", str(r.get(c_role) or "")).strip().title()
        year = year_override or _fiscal_year(r.get(c_date))
        if not (emp and role and year):
            continue
        n = _num(r.get(c_n)) if c_n else 1
        n = n or 1
        if status == "certified":
            out[(emp, role, year)][0] += n
        elif status == "denied":
            out[(emp, role, year)][1] += n
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", type=Path, help="downloaded USCIS hub or DOL LCA file(s), same source type")
    ap.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--year", type=int, help="DOL only: force fiscal year instead of deriving it from dates")
    ap.add_argument("--min-approvals", type=int, default=1, help="drop (employer, role, year) rows below this (default 1)")
    args = ap.parse_args(argv)

    missing = [p for p in args.inputs if not p.is_file()]
    if missing:
        print(f"File not found: {', '.join(map(str, missing))}\n"
              "Download the file yourself (see README 'Data') and put it under data/raw/. "
              "I never download or fabricate data, so the placeholder h1b_sample.csv stays in use until then.",
              file=sys.stderr)
        return 2

    kind, merged = None, defaultdict(lambda: [0, 0])
    for p in args.inputs:
        rows = read_rows(p)
        first = next(rows, None)
        if first is None:
            sys.exit(f"{p} is empty.")
        headers = list(first.keys())
        k = detect(headers)
        if k == "unknown":
            sys.exit(f"Couldn't recognise {p.name}. Headers: {headers}\n"
                     "Expected a USCIS Employer Data Hub export or a DOL LCA disclosure file.")
        if kind and k != kind:
            sys.exit("Don't mix USCIS and DOL files in one output: their numbers mean different things.")
        kind = k
        import itertools
        stream = itertools.chain([first], rows)
        agg = aggregate_uscis(stream, headers) if k == "uscis" else aggregate_dol(stream, headers, args.year)
        for key, (a, d) in agg.items():
            merged[key][0] += a
            merged[key][1] += d

    kept = sorted((k, v) for k, v in merged.items() if v[0] >= args.min_approvals)
    if not kept:
        sys.exit("No rows left after filtering; check the input file / --min-approvals.")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    src = {
        "uscis": "USCIS H-1B Employer Data Hub. approvals = initial + continuing approvals. "
                 "Company-level only (the hub has no job titles), so role = 'All roles'.",
        "dol": "DOL OFLC LCA disclosure data (H-1B). approvals = worker positions on CERTIFIED LCAs, "
               "which is a precursor to a petition, not a USCIS approval.",
    }[kind]
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        fh.write(f"# SOURCE: {src}\n")
        fh.write(f"# Inputs: {', '.join(p.name for p in args.inputs)}. Generated by scripts/prepare_h1b.py.\n")
        w = csv.writer(fh)
        w.writerow(["employer", "role", "year", "approvals", "denials"])
        for (emp, role, year), (a, d) in kept:
            w.writerow([emp, role, year, a, d])
    yrs = sorted({k[2] for k, _ in kept})
    print(f"Wrote {len(kept):,} rows ({kind.upper()}, FY{yrs[0]}-FY{yrs[-1]}, "
          f"{len({k[0] for k, _ in kept}):,} employers) to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
