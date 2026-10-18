"""Stamped: runs the coordinator + sponsorship + jobs agents together.

    python agent.py

Only the coordinator ("stamped") is reachable from ASI:One (Agentverse mailbox).
"""
import os

from dotenv import load_dotenv

load_dotenv()

from uagents import Bureau  # noqa: E402

from stamped.agents import build_all  # noqa: E402

seed = os.environ.get("AGENT_SEED")
if not seed:
    raise SystemExit("AGENT_SEED is not set. Copy .env.example to .env and fill it in.")

coordinator, sponsorship_agent, jobs_agent = build_all(seed)

if __name__ == "__main__":
    print("\n".join([
        f"stamped              {coordinator.address}",
        f"stamped-sponsorship  {sponsorship_agent.address}",
        f"stamped-jobs         {jobs_agent.address}",
    ]))
    bureau = Bureau(port=8001, log_level="INFO")
    for a in (coordinator, sponsorship_agent, jobs_agent):
        bureau.add(a)
    bureau.run()
