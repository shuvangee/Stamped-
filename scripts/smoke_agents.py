"""End-to-end check of the 3-agent setup without ASI:One.

A throwaway 'tester' agent plays ASI:One: it sends a ChatMessage to the coordinator and prints the
reply. Coordinator -> sponsorship/jobs messaging is the real uAgents path. Usage:

    python scripts/smoke_agents.py ["question"]
"""
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("AGENT_SEED", "smoke-test-seed-not-a-secret")

from uagents import Agent, Bureau, Context, Protocol  # noqa: E402
from uagents_core.contrib.protocols.chat import ChatMessage, TextContent, chat_protocol_spec  # noqa: E402

from stamped.agents import build_all  # noqa: E402

QUESTION = " ".join(sys.argv[1:]) or "Does Google or Stripe sponsor H-1B for software engineers?"
coordinator, sp, jb = build_all(os.environ["AGENT_SEED"], mailbox=False)
tester = Agent(name="tester", seed="smoke-tester-seed")
proto = Protocol(spec=chat_protocol_spec)
result = {}


@tester.on_event("startup")
async def go(ctx: Context):
    await ctx.send(coordinator.address, ChatMessage(content=[TextContent(text=QUESTION)]))


@proto.on_message(ChatMessage)
async def got(ctx: Context, sender: str, msg: ChatMessage):
    result["text"] = msg.text()
    print("\n===== REPLY =====\n" + msg.text() + "\n=================\n", flush=True)
    os._exit(0)


@proto.on_message(__import__("uagents_core.contrib.protocols.chat", fromlist=["x"]).ChatAcknowledgement)
async def ack(ctx: Context, sender: str, msg):
    pass


tester.include(proto)
threading.Timer(90, lambda: (print("TIMEOUT: no reply in 90s"), os._exit(1))).start()
bureau = Bureau(port=8765, log_level="WARNING")
for a in (coordinator, sp, jb, tester):
    bureau.add(a)
bureau.run()
