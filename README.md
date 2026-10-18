# Stamped

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

**An AI agent that tells international students which companies actually sponsor H-1B visas, before they spend weeks applying.**

Built solo at LA Hacks AI Hackathon 2026. Track: Applied Intelligence.

## The problem
<!-- 2-3 sentences: international students apply to hundreds of jobs, many at companies that never sponsor. Fill in with your own story. -->

## What it does
- Chat with Stamped in ASI:One: "Do Google or Stripe sponsor software engineers?"
- Gemini extracts the companies and role from your message
- The agent checks real H-1B filing history (U.S. Department of Labor disclosure data)
- Returns a verdict per company and a recommended application order

## Agent details
| Name | Address |
|---|---|
| stamped | `agent1q...` <!-- paste from logs --> |

## How it works
<!-- Architecture: ASI:One -> Stamped (Chat Protocol) -> Gemini intent extraction -> H-1B lookup tool -> Gemini summary -> ASI:One -->

## Run it
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in GEMINI_API_KEY and AGENT_SEED
python test_local.py   # try it without ASI:One
python agent.py
```
Open the inspector link from the logs, connect the mailbox, then find **stamped** in ASI:One.

## Data (real H-1B numbers)
Until you add a real file, Stamped uses `h1b_sample.csv`, which is **placeholder data** (replies say so).

1. Download yourself (the scripts never download anything):
   - **USCIS H-1B Employer Data Hub** export (company-level approvals/denials by fiscal year; no job titles), or
   - **DOL OFLC LCA disclosure** file (has job titles; counts certified LCAs, a step before petitions). `.xlsx` needs `pip install openpyxl`.
2. Put it under `data/raw/` (git-ignored), then run:
   ```bash
   python scripts/prepare_h1b.py data/raw/<your-file>
   ```
3. This writes `data/h1b_real.csv`, which the agent loads automatically in preference to the sample.
   Run `python -m unittest discover -s tests` to check the converter.

## Tech
Fetch.ai uAgents, Agentverse, ASI:One, Agent Chat Protocol, Google Gemini API, pandas.

## Sponsor challenges
- **Fetch.ai:** <!-- how you use Agentverse / Chat Protocol / ASI:One -->
- **Workday (Future of Work):** <!-- -->
- **Gemini:** <!-- -->

## Data note
Past H-1B filings don't guarantee future sponsorship. Data from public DOL LCA/H-1B disclosure files; `h1b_sample.csv` is placeholder data for development.

## Built during the hackathon
All code written at LA Hacks AI Hackathon, Oct 17-18, 2026.
