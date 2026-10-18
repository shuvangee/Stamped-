"""Try Stamped without ASI:One:  python test_local.py ["your question"]"""
import logging
import sys

from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from stamped.answer import build_answer  # noqa: E402

SAMPLES = [
    "Do Google or Stripe sponsor H-1B for software engineers?",
    "I'm an F-1 student looking for SWE roles. How are Amazon, Snap and Workday on sponsorship?",
    "Is Totally Unknown Startup a good bet for an H-1B?",
    "hello",
    "",
]

if __name__ == "__main__":
    for q in ([" ".join(sys.argv[1:])] if len(sys.argv) > 1 else SAMPLES):
        print(f"\n{'=' * 70}\nQ: {q!r}\n{'-' * 70}\n{build_answer(q)}")
