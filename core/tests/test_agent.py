import copy
import json
from types import SimpleNamespace

import anthropic
import httpx
from sqlalchemy import select

from tests.conftest import Clinic
from tests.helpers import send
from wam.agent import agent as agent_module
from wam.agent.tools import TOOL_DEFINITIONS
from wam.db import session_scope
from wam.models import Appointment, Contact, MessageLog


def text(t):
    return SimpleNamespace(type="text", text=t)


def tool(name, args, id_="tu_1"):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=args)


def resp(content, stop):
    return SimpleNamespace(content=content, stop_reason=stop)


class ScriptedLLM:
    """Plays back a script; each step is a function(kwargs) -> response."""

    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = []
        self.messages = self

    async def create(self, **kwargs):
        self.calls.append({**kwargs, "messages": copy.deepcopy(kwargs["messages"])})
        step = self.steps.pop(0)
        return step(kwargs)


def last_tool_result(kwargs):
    msg = kwargs["messages"][-1]
    return json.loads(msg["content"][0]["content"])


async def test_agent_finds_slots_then_books(clinic):
    llm = ScriptedLLM(
        [
            lambda k: resp([tool("find_slots", {"part_of_day": "evening"})], "tool_use"),
            lambda k: resp(
                [
                    text(
                        "Free evening slots:\n"
                        + "\n".join(f"{o['option']}) {o['slot']}" for o in last_tool_result(k)["options"])
                    )
                ],
                "end_turn",
            ),
            lambda k: resp([tool("book_slot", {"option": 2}, "tu_2")], "tool_use"),
            lambda k: resp([text(last_tool_result(k)["confirmation"])], "end_turn"),
        ]
    )
    await send(clinic.business_id, Clinic.RAHUL_PHONE, "hi")  # consent notice + rule-based first reply
    agent_module.set_llm_client(llm)
    replies = await send(clinic.business_id, Clinic.RAHUL_PHONE, "any evening slot this week?")
    assert "5:00 PM" in replies[0]
    # system prompt, tools and context are sent
    first = llm.calls[-2]
    assert "Smile Dental" in first["system"] and "never" in first["system"].lower()
    assert first["tools"] == TOOL_DEFINITIONS
    assert "[Context" in first["messages"][-1]["content"][-2]["text"]
    replies = await send(clinic.business_id, Clinic.RAHUL_PHONE, "the second one please")
    assert replies[0].startswith("Booked:")
    async with session_scope() as s:
        appt = (await s.execute(select(Appointment))).scalar_one()
        assert appt.contact_id == clinic.rahul_id
        inbound = (
            (await s.execute(select(MessageLog).where(MessageLog.direction == "in").order_by(MessageLog.id)))
            .scalars()
            .all()
        )
        assert inbound[-1].handled_by == "ai"


async def test_agent_cannot_book_without_offer(clinic):
    llm = ScriptedLLM(
        [
            lambda k: resp([tool("book_slot", {"option": 1})], "tool_use"),
            lambda k: resp([text("error:" + last_tool_result(k)["error"])], "end_turn"),
        ]
    )
    agent_module.set_llm_client(llm)
    await send(clinic.business_id, Clinic.RAHUL_PHONE, "hello")
    agent_module.set_llm_client(llm)
    llm.steps = [
        lambda k: resp([tool("book_slot", {"option": 1})], "tool_use"),
        lambda k: resp([text("error:" + last_tool_result(k)["error"])], "end_turn"),
    ]
    async with session_scope() as s:
        from wam.models import ConversationState

        for st in (await s.execute(select(ConversationState))).scalars():
            await s.delete(st)
    replies = await send(clinic.business_id, Clinic.RAHUL_PHONE, "book me tomorrow 10am")
    assert replies[0] == "error:No slots are on offer. Call find_slots first."
    async with session_scope() as s:
        assert (await s.execute(select(Appointment))).first() is None


async def test_agent_handoff_opens_chat_for_staff(clinic):
    llm = ScriptedLLM(
        [
            lambda k: resp([tool("handoff_to_staff", {"reason": "medical question"})], "tool_use"),
            lambda k: resp([text("I'll ask the doctor's team to reply here.")], "end_turn"),
        ]
    )
    agent_module.set_llm_client(llm)
    async with session_scope() as s:
        rahul = await s.get(Contact, clinic.rahul_id)
        from wam import clock

        rahul.consent_notice_sent_at = clock.now()
    replies = await send(clinic.business_id, Clinic.RAHUL_PHONE, "which painkiller should I take?")
    assert replies == ["I'll ask the doctor's team to reply here."]
    async with session_scope() as s:
        assert (await s.get(Contact, clinic.rahul_id)).needs_staff is True


async def test_api_error_falls_back_to_rules(clinic):
    class Broken:
        messages = None

        def __init__(self):
            self.messages = self

        async def create(self, **kwargs):
            request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
            raise anthropic.APIConnectionError(request=request)

    agent_module.set_llm_client(Broken())
    await send(clinic.business_id, Clinic.RAHUL_PHONE, "hi")
    replies = await send(clinic.business_id, Clinic.RAHUL_PHONE, "what are your timings")
    assert "Our timings" in replies[0]


async def test_staff_free_text_is_rewritten_by_ai_then_parsed(clinic):
    llm = ScriptedLLM([lambda k: resp([text("today's list")], "end_turn")])
    agent_module.set_llm_client(llm)
    replies = await send(clinic.business_id, Clinic.DOCTOR_PHONE, "who all are coming in today?")
    assert "Today's list" in replies[0]
