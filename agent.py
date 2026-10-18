"""Stamped: H-1B sponsorship checker, reachable from ASI:One via the Agent Chat Protocol."""
import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv()

from uagents import Agent, Context, Protocol  # noqa: E402
from uagents_core.contrib.protocols.chat import (  # noqa: E402
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    StartSessionContent,
    TextContent,
    chat_protocol_spec,
)

from stamped.answer import GREETING, build_answer  # noqa: E402

seed = os.environ.get("AGENT_SEED")
if not seed:
    raise SystemExit("AGENT_SEED is not set. Copy .env.example to .env and fill it in.")

agent = Agent(
    name="stamped",
    seed=seed,
    port=8001,
    mailbox=True,
    publish_agent_details=True,
)
chat = Protocol(spec=chat_protocol_spec)


def _reply(text: str, end: bool = True) -> ChatMessage:
    content = [TextContent(text=text)]
    if end:
        content.append(EndSessionContent())
    return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(), content=content)


@chat.on_message(ChatMessage)
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(sender, ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))

    text = msg.text().strip()
    if not text:
        if any(isinstance(c, StartSessionContent) for c in msg.content):
            await ctx.send(sender, _reply(GREETING, end=False))
        return
    try:
        # build_answer makes blocking network calls (Gemini); keep the event loop free
        answer = await asyncio.to_thread(build_answer, text)
    except Exception:
        ctx.logger.exception("build_answer failed")
        answer = "Sorry, something went wrong while checking that. Please try again in a moment."
    await ctx.send(sender, _reply(answer))


@chat.on_message(ChatAcknowledgement)
async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    ctx.logger.debug(f"ack from {sender} for {msg.acknowledged_msg_id}")


agent.include(chat, publish_manifest=True)

if __name__ == "__main__":
    agent.run()
