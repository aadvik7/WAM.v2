"""Entry points the shared router, AI agent, staff commands and worker call for the institute pack."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from wam.models import Business, Contact
from wam.packs.institute.commands import HELP_TEXT, PERMISSION, REWRITE_FORMS, execute_pending, handle, parse
from wam.packs.institute.doubts import close_open_doubts
from wam.packs.institute.replies import Reply, quick_reply
from wam.packs.institute.tools import TOOLS, run_tool

__all__ = [
    "HELP_TEXT",
    "PERMISSION",
    "REWRITE_FORMS",
    "TOOLS",
    "Reply",
    "execute_pending",
    "handle_staff",
    "on_conversation_resolved",
    "parse_staff",
    "quick_reply",
    "run_tool",
]


def parse_staff(text: str) -> Any:
    return parse(text)


async def handle_staff(ctx: Any, cmd: Any) -> bool:
    return await handle(ctx, cmd)


async def on_conversation_resolved(session: AsyncSession, business: Business, contact: Contact) -> None:
    await close_open_doubts(session, business.id, contact.id)
