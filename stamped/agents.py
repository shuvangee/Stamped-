"""The three Stamped agents.

  stamped               coordinator: the only agent ASI:One talks to (Agent Chat Protocol + mailbox)
  stamped-sponsorship   H-1B history lookups
  stamped-jobs          open-role search

They run together in one Bureau (agent.py) and message each other with typed uAgents models.
"""
import asyncio
import logging
from datetime import datetime, timezone
from uuid import uuid4

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    StartSessionContent,
    TextContent,
    chat_protocol_spec,
)

from . import jobs, sponsorship
from .answer import GREETING, answer
from .models import JobsRequest, JobsResponse, SponsorshipRequest, SponsorshipResponse

SUB_TIMEOUT = 25      # seconds to wait for a sub-agent reply
TOTAL_TIMEOUT = 75    # whole-request budget
log = logging.getLogger("stamped.agents")


def make_sponsorship_agent(seed: str) -> Agent:
    agent = Agent(name="stamped-sponsorship", seed=f"{seed}-sponsorship", description="H-1B sponsorship history lookups")

    @agent.on_message(SponsorshipRequest, replies=SponsorshipResponse)
    async def handle(ctx: Context, sender: str, msg: SponsorshipRequest):
        ctx.logger.info(f"sponsorship request: {msg.companies} role={msg.role!r}")
        resp = await asyncio.to_thread(sponsorship.check, msg.companies, msg.role)
        await ctx.send(sender, resp)

    return agent


def make_jobs_agent(seed: str) -> Agent:
    agent = Agent(name="stamped-jobs", seed=f"{seed}-jobs", description="Open-role search")

    @agent.on_message(JobsRequest, replies=JobsResponse)
    async def handle(ctx: Context, sender: str, msg: JobsRequest):
        ctx.logger.info(f"jobs request: role={msg.role!r} location={msg.location!r} companies={msg.companies}")
        resp = await asyncio.to_thread(jobs.find_jobs, msg.role, msg.location, msg.companies, msg.limit)
        await ctx.send(sender, resp)

    return agent


def _reply(text: str, end: bool = True) -> ChatMessage:
    content = [TextContent(text=text)]
    if end:
        content.append(EndSessionContent())
    return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(), content=content)


def make_coordinator(seed: str, sponsorship_addr: str, jobs_addr: str, mailbox: bool = True) -> Agent:
    agent = Agent(
        name="stamped",
        seed=seed,
        port=8001,
        mailbox=mailbox,
        publish_agent_details=True,
        description="Tells international students which companies sponsor H-1B visas, and finds open roles.",
    )
    chat = Protocol(spec=chat_protocol_spec)

    def asker(ctx: Context, addr: str, resp_type):
        async def ask(req):
            last = "no response"
            for attempt in range(2):  # one retry on timeout / delivery failure
                resp, status = await ctx.send_and_receive(addr, req, response_type=resp_type, timeout=SUB_TIMEOUT)
                if isinstance(resp, resp_type):
                    return resp
                last = str(status)
                ctx.logger.warning(f"{resp_type.__name__} attempt {attempt + 1} failed: {last}")
            raise RuntimeError(last)
        return ask

    @chat.on_message(ChatMessage)
    async def handle_chat(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))
        text = msg.text().strip()
        if not text:
            if any(isinstance(c, StartSessionContent) for c in msg.content):
                await ctx.send(sender, _reply(GREETING, end=False))
            return
        try:
            reply = await asyncio.wait_for(
                answer(text, asker(ctx, sponsorship_addr, SponsorshipResponse), asker(ctx, jobs_addr, JobsResponse)),
                timeout=TOTAL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            reply = "Sorry, that took too long. Try one or two companies at a time."
        except Exception:
            ctx.logger.exception("answer failed")
            reply = "Sorry, something went wrong while checking that. Please try again in a moment."
        await ctx.send(sender, _reply(reply))

    @chat.on_message(ChatAcknowledgement)
    async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        ctx.logger.debug(f"ack from {sender} for {msg.acknowledged_msg_id}")

    agent.include(chat, publish_manifest=True)
    return agent


def build_all(seed: str, mailbox: bool = True) -> tuple[Agent, Agent, Agent]:
    sp, jb = make_sponsorship_agent(seed), make_jobs_agent(seed)
    return make_coordinator(seed, sp.address, jb.address, mailbox=mailbox), sp, jb
