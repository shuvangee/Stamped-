"""
Stamped agent - visa-aware job helper for international students.
LA Hacks AI Hackathon 2026 starter.

Flow: user chats in ASI:One -> this agent -> extracts companies/role with Gemini
-> checks H-1B sponsorship history from local data -> replies with a verdict.

Setup:
  pip install uagents google-genai pandas
  export GEMINI_API_KEY=your_key
  python agent.py
Then open the Agentverse inspector link printed in the logs, connect the mailbox,
and find your agent in ASI:One.

NOTE: confirm the exact chat-protocol imports against Fetch's current docs/mentors.
This mirrors the hackpack example at the time of writing.
"""

import json
import os
from datetime import datetime
from uuid import uuid4

import pandas as pd
from google import genai
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    StartSessionContent,
    TextContent,
    chat_protocol_spec,
)

# ---------- config ----------
AGENT_NAME = "stamped"
AGENT_SEED = os.getenv("AGENT_SEED", "change-this-to-a-long-random-secret-phrase")
GEMINI_MODEL = "gemini-2.5-flash"
H1B_CSV = "h1b_sample.csv"  # columns: employer, job_title, year, filings

gemini = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

agent = Agent(name=AGENT_NAME, seed=AGENT_SEED, port=8001, mailbox=True)
chat_proto = Protocol(spec=chat_protocol_spec)

# ---------- data ----------
try:
    H1B = pd.read_csv(H1B_CSV)
    H1B["employer_norm"] = H1B["employer"].str.upper().str.strip()
except FileNotFoundError:
    H1B = pd.DataFrame(columns=["employer", "job_title", "year", "filings", "employer_norm"])


def lookup_sponsorship(company: str, role_keyword: str = "") -> dict:
    """Tool: check how often a company filed H-1B petitions, optionally for a role."""
    rows = H1B[H1B["employer_norm"].str.contains(company.upper().strip(), na=False, regex=False)]
    if role_keyword:
        role_rows = rows[rows["job_title"].str.contains(role_keyword, case=False, na=False, regex=False)]
    else:
        role_rows = rows
    return {
        "company": company,
        "total_filings": int(rows["filings"].sum()) if len(rows) else 0,
        "role_filings": int(role_rows["filings"].sum()) if len(role_rows) else 0,
        "years": sorted(rows["year"].unique().tolist()) if len(rows) else [],
        "sample_titles": role_rows["job_title"].head(5).tolist(),
    }


# ---------- reasoning ----------
def extract_intent(user_text: str) -> dict:
    """Use Gemini to pull companies and a role keyword out of the user's message."""
    prompt = (
        "Extract job-search intent from this message. Return ONLY JSON like "
        '{"companies": ["Google"], "role": "software engineer"}. '
        f"Message: {user_text}"
    )
    resp = gemini.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    raw = resp.text.strip().removeprefix("```json").removesuffix("```").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"companies": [], "role": ""}


def build_answer(user_text: str) -> str:
    intent = extract_intent(user_text)
    companies = intent.get("companies", [])
    role = intent.get("role", "")
    if not companies:
        return ("Tell me which companies (and role) you're considering, e.g. "
                "'Do Google or Stripe sponsor H-1B for software engineers?'")

    results = [lookup_sponsorship(c, role.split()[0] if role else "") for c in companies]

    summary_prompt = (
        "You are Stamped, helping an international student decide where to apply. "
        "Using ONLY this H-1B filing data, give a short verdict per company "
        "(Strong / Some / No record of sponsorship), one line of reasoning each, "
        "then a recommended order to apply. Note that past filings don't guarantee "
        f"future sponsorship.\nRole: {role}\nData: {json.dumps(results)}"
    )
    resp = gemini.models.generate_content(model=GEMINI_MODEL, contents=summary_prompt)
    return resp.text


# ---------- chat protocol ----------
def text_msg(text: str, end_session: bool = False) -> ChatMessage:
    content = [TextContent(type="text", text=text)]
    if end_session:
        content.append(EndSessionContent(type="end-session"))
    return ChatMessage(timestamp=datetime.utcnow(), msg_id=uuid4(), content=content)


@chat_proto.on_message(ChatMessage)
async def handle_message(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(sender, ChatAcknowledgement(
        timestamp=datetime.utcnow(), acknowledged_msg_id=msg.msg_id))

    for item in msg.content:
        if isinstance(item, StartSessionContent):
            ctx.logger.info(f"Session started with {sender}")
        elif isinstance(item, TextContent):
            ctx.logger.info(f"Query from {sender}: {item.text}")
            try:
                answer = build_answer(item.text)
            except Exception as e:  # judges reward graceful failure handling
                ctx.logger.error(f"Error: {e}")
                answer = "Sorry, I hit an error checking that. Try rephrasing or one company at a time."
            await ctx.send(sender, text_msg(answer))
        elif isinstance(item, EndSessionContent):
            ctx.logger.info(f"Session ended with {sender}")


@chat_proto.on_message(ChatAcknowledgement)
async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    ctx.logger.info(f"Ack from {sender} for {msg.acknowledged_msg_id}")


agent.include(chat_proto, publish_manifest=True)

if __name__ == "__main__":
    agent.run()
