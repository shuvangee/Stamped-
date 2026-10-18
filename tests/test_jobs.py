import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stamped import jobs  # noqa: E402


class JobsTests(unittest.TestCase):
    def test_category_mapping(self):
        self.assertEqual(jobs.muse_category("Software Engineer"), "Software Engineering")
        self.assertEqual(jobs.muse_category("data scientist"), "Data Science")
        self.assertEqual(jobs.muse_category("Data Analyst"), "Data and Analytics")
        self.assertIsNone(jobs.muse_category("Pastry Chef"))

    def test_muse_parsing(self):
        page = {"page_count": 1, "results": [{
            "name": "Backend Engineer", "company": {"name": "Riot Games"},
            "locations": [{"name": "Los Angeles, CA"}], "refs": {"landing_page": "http://r"},
            "publication_date": "2026-09-04T18:30:47Z"}]}
        with mock.patch.object(jobs, "_get_json", return_value=page) as g:
            resp = jobs.find_jobs("Software Engineer", "Los Angeles, CA", ["RIOT GAMES INC"])
        url = g.call_args[0][0]
        self.assertIn("category=Software+Engineering", url)
        self.assertIn("company=Riot+Games", url)
        self.assertEqual((resp.jobs[0].company, resp.jobs[0].posted, resp.error), ("Riot Games", "2026-09-04", ""))

    def test_uncategorised_role_filters_by_title(self):
        page = {"page_count": 1, "results": [
            {"name": "Pastry Chef", "company": {"name": "A"}, "locations": [], "refs": {}},
            {"name": "Accountant", "company": {"name": "B"}, "locations": [], "refs": {}}]}
        with mock.patch.object(jobs, "_get_json", return_value=page):
            resp = jobs.find_jobs("Pastry Chef")
        self.assertEqual([j.title for j in resp.jobs], ["Pastry Chef"])

    def test_network_failure_returns_error_not_exception(self):
        with mock.patch.object(jobs, "_get_json", side_effect=RuntimeError("timeout")):
            resp = jobs.find_jobs("Software Engineer")
        self.assertEqual(resp.jobs, [])
        self.assertIn("timeout", resp.error)


if __name__ == "__main__":
    unittest.main()
