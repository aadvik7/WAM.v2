"""Outbound messages. Everything goes out through Chatwoot so each conversation stays in one inbox.

Inside WhatsApp's 24-hour window WAM sends free text; outside it, a Meta-approved template.
Without Chatwoot configured (development), messages are only written to message_log ("dry_run").
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from wam import clock
from wam.chatwoot import ChatwootClient, ChatwootError, source_id_for
from wam.config import get_settings
from wam.models import Business, Contact, MessageLog, Staff
from wam.settings_defaults import get_setting
from wam.templates import get_template

log = logging.getLogger(__name__)

WINDOW = dt.timedelta(hours=24) - dt.timedelta(minutes=5)


@dataclass
class Outgoing:
    text: str
    template_key: str | None = None
    template_values: dict[str, Any] = field(default_factory=dict)


def window_open(last_inbound_at: dt.datetime | None) -> bool:
    return last_inbound_at is not None and clock.now() - last_inbound_at < WINDOW


def reachable(contact: Contact) -> Contact | None:
    """The contact whose phone we message: the contact itself or its guardian (e.g. a parent)."""
    if contact.phone:
        return contact
    if contact.guardian is not None and contact.guardian.phone:
        return contact.guardian
    return None


def chatwoot_for(business: Business) -> ChatwootClient | None:
    settings = get_settings()
    if not settings.chatwoot_enabled or not business.chatwoot_account_id:
        return None
    return ChatwootClient(
        settings.chatwoot_base_url,
        business.chatwoot_account_id,
        business.chatwoot_api_token or settings.chatwoot_api_token,
        business.chatwoot_bot_token or settings.chatwoot_bot_token or None,
    )


def _template_params(business: Business, template_key: str, values: dict[str, Any]) -> dict[str, Any]:
    tpl = get_template(template_key)
    language = str(get_setting(business.settings, "template_language") or tpl.language)
    positional = tpl.positional({k: str(v) for k, v in values.items()})
    if get_settings().chatwoot_template_format == "enhanced":
        processed: dict[str, Any] = {"body": positional}
    else:
        processed = positional
    return {"name": tpl.name, "category": tpl.category, "language": language, "processed_params": processed}


async def _ensure_conversation(client: ChatwootClient, business: Business, who: Contact | Staff) -> int:
    assert business.chatwoot_inbox_id is not None, "business has no Chatwoot inbox"
    inbox_id = business.chatwoot_inbox_id
    phone = who.phone or ""
    if who.chatwoot_contact_id is None:
        found = await client.search_contact(phone)
        if found is None:
            found = await client.create_contact(inbox_id=inbox_id, name=who.name, phone=phone)
        who.chatwoot_contact_id = int(found["id"])
        who.chatwoot_source_id = source_id_for(found, inbox_id)
    if not who.chatwoot_source_id:
        digits = "".join(ch for ch in phone if ch.isdigit())
        ci = await client.create_contact_inbox(who.chatwoot_contact_id, inbox_id, digits)
        who.chatwoot_source_id = str(ci.get("source_id") or digits)
    # Reuse the latest conversation in this inbox, else start one.
    conversations = [
        c
        for c in await client.contact_conversations(who.chatwoot_contact_id)
        if c.get("inbox_id") == inbox_id
    ]
    if conversations:
        conversations.sort(key=lambda c: c.get("id", 0), reverse=True)
        open_ones = [c for c in conversations if c.get("status") != "resolved"]
        who.chatwoot_conversation_id = int((open_ones or conversations)[0]["id"])
    else:
        conv = await client.create_conversation(
            inbox_id=inbox_id, contact_id=who.chatwoot_contact_id, source_id=who.chatwoot_source_id
        )
        who.chatwoot_conversation_id = int(conv["id"])
    return who.chatwoot_conversation_id


async def _deliver(
    business: Business, who: Contact | Staff, content: str, template_params: dict[str, Any] | None
) -> tuple[str, int | None, int | None, str | None]:
    """Returns (status, conversation_id, message_id, error)."""
    client = chatwoot_for(business)
    if client is None:
        return "dry_run", who.chatwoot_conversation_id, None, None
    try:
        conv_id = who.chatwoot_conversation_id or await _ensure_conversation(client, business, who)
        try:
            msg = await client.send_message(conv_id, content, template_params=template_params)
        except ChatwootError as exc:
            if "404" not in str(exc):
                raise
            who.chatwoot_conversation_id = None  # conversation was deleted; start a fresh one
            conv_id = await _ensure_conversation(client, business, who)
            msg = await client.send_message(conv_id, content, template_params=template_params)
        return "ok", conv_id, (int(msg["id"]) if msg.get("id") else None), None
    except (ChatwootError, KeyError, ValueError, AssertionError) as exc:
        log.warning("send failed for business=%s: %s", business.id, exc)
        return "failed", who.chatwoot_conversation_id, None, str(exc)[:1000]


async def send_to_contact(
    session: AsyncSession,
    business: Business,
    contact: Contact,
    out: Outgoing,
    *,
    handled_by: str = "system",
    proactive: bool = True,
) -> MessageLog | None:
    """Send to a patient/customer (or their guardian). Returns the log row, or None if skipped."""
    target = reachable(contact)
    if target is None:
        return await _log_skip(session, business, contact_id=contact.id, reason="no phone number", out=out)
    if proactive and (target.opted_out or contact.opted_out):
        return await _log_skip(session, business, contact_id=contact.id, reason="opted out", out=out)
    if window_open(target.last_inbound_at):
        content, tparams, tname = out.text, None, None
    elif out.template_key is None:
        return await _log_skip(
            session, business, contact_id=contact.id, reason="outside 24h window and no template", out=out
        )
    else:
        tpl = get_template(out.template_key)
        content = tpl.render({k: str(v) for k, v in out.template_values.items()})
        tparams = _template_params(business, out.template_key, out.template_values)
        tname = tpl.name
    status, conv_id, msg_id, error = await _deliver(business, target, content, tparams)
    row = MessageLog(
        business_id=business.id,
        contact_id=contact.id,
        direction="out",
        phone=target.phone,
        content=content,
        template_name=tname,
        audience="patient",
        handled_by=handled_by,
        status=status,
        error=error,
        chatwoot_conversation_id=conv_id,
        chatwoot_message_id=msg_id,
    )
    session.add(row)
    await session.flush()
    return row


async def send_to_staff(
    session: AsyncSession,
    business: Business,
    staff: Staff,
    out: Outgoing,
    *,
    handled_by: str = "system",
) -> MessageLog | None:
    if window_open(staff.last_inbound_at):
        content, tparams, tname = out.text, None, None
    else:
        key = out.template_key or "staff_alert"
        values = out.template_values or {"business": business.name, "summary": out.text.split("\n")[0][:200]}
        tpl = get_template(key)
        values = {**{"business": business.name}, **values}
        content = tpl.render({k: str(v) for k, v in values.items()})
        tparams = _template_params(business, key, values)
        tname = tpl.name
    status, conv_id, msg_id, error = await _deliver(business, staff, content, tparams)
    row = MessageLog(
        business_id=business.id,
        staff_id=staff.id,
        direction="out",
        phone=staff.phone,
        content=content,
        template_name=tname,
        audience="staff",
        handled_by=handled_by,
        status=status,
        error=error,
        chatwoot_conversation_id=conv_id,
        chatwoot_message_id=msg_id,
    )
    session.add(row)
    await session.flush()
    return row


async def _log_skip(
    session: AsyncSession, business: Business, *, contact_id: int | None, reason: str, out: Outgoing
) -> None:
    session.add(
        MessageLog(
            business_id=business.id,
            contact_id=contact_id,
            direction="out",
            content=out.text,
            template_name=out.template_key,
            audience="patient",
            handled_by="system",
            status="skipped",
            error=reason,
        )
    )
    await session.flush()
    return None


async def private_note(business: Business, conversation_id: int | None, text: str) -> None:
    """Internal note visible only to staff in the Chatwoot inbox."""
    client = chatwoot_for(business)
    if client is None or conversation_id is None:
        return
    try:
        await client.send_message(conversation_id, text, private=True)
    except ChatwootError as exc:
        log.warning("private note failed: %s", exc)


async def handoff(
    business: Business,
    conversation_id: int | None,
    reason: str,
    *,
    urgent: bool = False,
    labels: list[str] | None = None,
) -> None:
    """Hand the chat to staff: note + open status (+ urgent priority and labels)."""
    client = chatwoot_for(business)
    if client is None or conversation_id is None:
        return
    try:
        await client.send_message(conversation_id, f"WAM handed this chat to staff: {reason}", private=True)
        await client.toggle_status(conversation_id, "open")
        if urgent:
            await client.set_priority(conversation_id, "urgent")
        if labels:
            await client.add_labels(conversation_id, labels)
    except ChatwootError as exc:
        log.warning("handoff failed: %s", exc)
