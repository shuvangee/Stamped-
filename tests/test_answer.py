"""Coordinator orchestration with fake sub-agents (no network)."""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stamped import answer as A, llm  # noqa: E402
from stamped.models import JobModel, JobsResponse, SponsorshipResponse, VerdictModel  # noqa: E402


def V(company, tier, rank):
    return VerdictModel(company=company, tier=tier, rank=rank, detail=f"detail {company}")


def run(text, q, ask_s, ask_j):
    with mock.patch.object(llm, "extract_query", return_value=q), mock.patch.object(llm, "summarize", return_value=None):
        return asyncio.run(A.answer(text, ask_s, ask_j))


class OrchestrationTests(unittest.TestCase):
    def test_named_companies_ranked_with_jobs_attached(self):
        async def s(req):
            return SponsorshipResponse(verdicts=[V("Low Co", "🟠 Limited", 2), V("Big Co", "✅ Strong sponsor", 4)])

        async def j(req):
            self.assertEqual(req.companies, ["Low Co", "Big Co"])
            return JobsResponse(jobs=[JobModel(title="SWE", company="Big Co", url="http://x/1", location="LA")], source="muse")

        out = run("q", llm.Query(companies=["Low Co", "Big Co"], role="Software Engineer"), s, j)
        self.assertLess(out.index("Big Co"), out.index("Low Co"))      # ranked
        self.assertIn("[SWE](http://x/1)", out)                         # job attached to Big Co
        self.assertIn("No open listings found", out)                    # Low Co has none

    def test_jobs_agent_down_still_answers_sponsorship(self):
        async def s(req):
            return SponsorshipResponse(verdicts=[V("Big Co", "✅ Strong sponsor", 4)])

        async def j(req):
            raise ConnectionError("boom")

        out = run("q", llm.Query(companies=["Big Co"], role="SWE"), s, j)
        self.assertIn("Strong sponsor", out)
        self.assertIn("Jobs agent unreachable", out)

    def test_sponsorship_agent_down_is_reported(self):
        async def s(req):
            return None

        async def j(req):
            return JobsResponse(jobs=[], source="muse")

        out = run("q", llm.Query(companies=["Big Co"], role="SWE"), s, j)
        self.assertIn("Sponsorship check unavailable", out)

    def test_jobs_source_error_field_degrades(self):
        async def s(req):
            return SponsorshipResponse(verdicts=[V("Big Co", "✅ Strong sponsor", 4)])

        async def j(req):
            return JobsResponse(error="muse unavailable (timeout)")

        out = run("q", llm.Query(companies=["Big Co"], role="SWE"), s, j)
        self.assertIn("Strong sponsor", out)
        self.assertIn("muse unavailable", out)

    def test_discovery_mode_jobs_first_then_sponsorship_on_employers(self):
        seen = {}

        async def j(req):
            self.assertEqual(req.companies, [])
            return JobsResponse(jobs=[
                JobModel(title="SWE I", company="Unknown LLC", url="http://u"),
                JobModel(title="SWE II", company="Big Co", url="http://b"),
                JobModel(title="SWE III", company="Big Co", url="http://b2"),
            ], source="muse")

        async def s(req):
            seen["companies"] = req.companies
            return SponsorshipResponse(verdicts=[V("Unknown LLC", "⚪ No data", 0), V("Big Co", "✅ Strong sponsor", 4)])

        out = run("q", llm.Query(companies=[], role="Software Engineer", location="Los Angeles, CA"), s, j)
        self.assertEqual(seen["companies"], ["Unknown LLC", "Big Co"])   # employers came from the jobs result
        self.assertIn("Roles ranked by H-1B sponsorship history", out)
        self.assertIn("Open roles (2)", out)
        self.assertIn("1 other employer hiring for this role had no H-1B data: Unknown LLC", out)

    def test_discovery_no_jobs(self):
        async def j(req):
            return JobsResponse(jobs=[], source="muse")

        async def s(req):
            raise AssertionError("should not be called")

        out = run("q", llm.Query(companies=[], role="Chef"), s, j)
        self.assertIn("no open **Chef** listings", out)

    def test_empty_and_no_intent(self):
        self.assertEqual(asyncio.run(A.answer("  ", None, None)), A.GREETING)
        out = run("hi", llm.Query(companies=[], role=""), None, None)
        self.assertIn("couldn't find a company or role", out)


if __name__ == "__main__":
    unittest.main()
