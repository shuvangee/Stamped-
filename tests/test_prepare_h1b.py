"""Parser tests. Fixtures are SYNTHETIC (made up here, never shipped as data)."""
import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "prepare_h1b.py"
sys.path.insert(0, str(ROOT))


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True)


def rows(path):
    lines = [l for l in Path(path).read_text().splitlines() if not l.startswith("#")]
    return list(csv.DictReader(lines))


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())

    def test_uscis_utf16_tsv(self):
        f = self.d / "hub.csv"  # real exports are reported as UTF-16 tab-delimited despite .csv
        f.write_text(
            "Fiscal Year\tEmployer (Petitioner) Name\tInitial Approval\tInitial Denial\tContinuing Approval\tContinuing Denial\n"
            "2023\tFAKE CO INC\t10\t1\t\"1,200\"\t2\n"
            "2023\tFake  Co Inc\t5\t0\t0\t0\n"
            "2024\tOTHER LLC\t0\t3\t0\t0\n", encoding="utf-16")
        out = self.d / "out.csv"
        r = run(f, "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        got = rows(out)
        self.assertEqual(got, [{"employer": "FAKE CO INC", "role": "All roles", "year": "2023",
                                "approvals": "1215", "denials": "3"}])  # OTHER dropped: 0 approvals
        self.assertIn("SOURCE: USCIS", out.read_text())

    def test_dol_filters_and_fiscal_year(self):
        f = self.d / "lca.csv"
        f.write_text(
            "CASE_STATUS,VISA_CLASS,EMPLOYER_NAME,SOC_TITLE,JOB_TITLE,TOTAL_WORKER_POSITIONS,DECISION_DATE\n"
            "Certified,H-1B,Fake Co,Software Developers,SWE II,3,2024-10-02\n"   # Oct -> FY2025
            "Certified,H-1B,Fake Co,Software Developers,SWE I,1,2024-09-30\n"    # FY2024
            "Denied,H-1B,Fake Co,Software Developers,SWE,2,2024-10-05\n"
            "Withdrawn,H-1B,Fake Co,Software Developers,SWE,9,2024-10-05\n"      # ignored
            "Certified,E-3,Fake Co,Software Developers,SWE,7,2024-10-05\n")      # not H-1B
        out = self.d / "out.csv"
        self.assertEqual(run(f, "-o", out).returncode, 0)
        got = {(r["year"], r["approvals"], r["denials"]) for r in rows(out)}
        self.assertEqual(got, {("2025", "3", "2"), ("2024", "1", "0")})
        self.assertIn("not a USCIS approval", out.read_text())

    def test_missing_file_is_clear_error_and_writes_nothing(self):
        out = self.d / "out.csv"
        r = run(self.d / "nope.csv", "-o", out)
        self.assertEqual(r.returncode, 2)
        self.assertIn("never download", r.stderr)
        self.assertFalse(out.exists())

    def test_unrecognised_headers(self):
        f = self.d / "x.csv"
        f.write_text("a,b\n1,2\n")
        r = run(f, "-o", self.d / "o.csv")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("recognise", r.stderr + r.stdout)

    def test_output_loads_in_agent_and_company_level_note(self):
        f = self.d / "hub.csv"
        f.write_text("Fiscal Year,Employer (Petitioner) Name,Initial Approval,Continuing Approval\n"
                     "2024,FAKE CO INC,300,900\n2023,FAKE CO INC,200,800\n")
        out = self.d / "out.csv"
        self.assertEqual(run(f, "-o", out).returncode, 0)
        from stamped.data import load_data
        from stamped.answer import _verdict
        data = load_data(out)
        self.assertFalse(data.is_placeholder)
        self.assertFalse(data.has_roles)
        v = _verdict(data, "Fake Co", "Software Engineer")
        self.assertIn("Strong", v.tier)
        self.assertIn("company-level", v.detail)


if __name__ == "__main__":
    unittest.main()
