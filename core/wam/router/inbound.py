"""Inbound message pipeline: record (deduplicated), then route to staff commands or the patient flow."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from wam import clock
from wam.db import session_scope
from wam.messaging import handoff
from wam.models import Business, Contact, MessageLog, Staff
from wam.phone import normalize_phone
from wam.router.patient import handle_patient_message
from wam.staff.commands import handle_staff_message

log = logging.getLogger(__name__)


@dataclass
class Inbound:
    business_id: int
    phone: str
    text: str
    name: str | None = None
    conversation_id: int | None = None
    conversation_status: str | None = None
    conversation_assigned: bool = False
    chatwoot_contact_id: int | None = None
    chatwoot_message_id: int | None = None
    source_id: str | None = None
    has_attachments: bool = False

    def meta(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "conversation_status": self.conversation_status,
            "conversation_assigned": self.conversation_assigned,
            "chatwoot_contact_id": self.chatwoot_contact_id,
            "source_id": self.source_id,
            "has_attachments": self.has_attachments,
        }


async def record_inbound(session: AsyncSession, inbound: Inbound) -> int | None:
    """Store the inbound message. Returns the log id, or None if Chatwoot already delivered it."""
    stmt = (
        insert(MessageLog)
        .values(
            business_id=inbound.business_id,
            direction="in",
            phone=inbound.phone,
            content=inbound.text,
            audience="patient",
            status="received",
            chatwoot_conversation_id=inbound.conversation_id,
            chatwoot_message_id=inbound.chatwoot_message_id,
        )
        .on_conflict_do_nothing(
            index_elements=["business_id", "chatwoot_message_id"],
            index_where=text("direction = 'in' AND chatwoot_message_id IS NOT NULL"),
        )
        .returning(MessageLog.id)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _lock_sender(session: AsyncSession, business_id: int, phone: str) -> None:
    # Serialise processing per sender so two quick messages don't race each other.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:b, hashtext(:p))"), {"b": business_id, "p": phone}
    )


async def process_inbound(session: AsyncSession, log_id: int, meta: dict[str, Any] | None = None) -> str:
    """Handle one recorded inbound message. Returns who handled it (ai/rule/staff/none/skipped)."""
    meta = meta or {}
    row = await session.get(MessageLog, log_id)
    if row is None or row.status != "received" or not row.phone:
        return "skipped"
    await _lock_sender(session, row.business_id, row.phone)
    await session.refresh(row)
    if row.status != "received":
        return "skipped"
    business = await session.get(Business, row.business_id)
    if business is None or not business.is_active:
        row.status = "processed"
        row.handled_by = "none"
        return "none"
    now = clock.now()
    text_in = row.content or ""

    staff = (
        await session.execute(
            select(Staff).where(
                Staff.business_id == business.id, Staff.phone == row.phone, Staff.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()
    if staff is not None:
        staff.last_inbound_at = now
        if row.chatwoot_conversation_id:
            staff.chatwoot_conversation_id = row.chatwoot_conversation_id
        if meta.get("chatwoot_contact_id"):
            staff.chatwoot_contact_id = meta["chatwoot_contact_id"]
        if meta.get("source_id"):
            staff.chatwoot_source_id = meta["source_id"]
        row.staff_id = staff.id
        row.audience = "staff"
        if meta.get("has_attachments") and not text_in.strip():
            handled = "none"
        else:
            handled = await handle_staff_message(session, business, staff, text_in)
        row.handled_by = handled
        row.status = "processed"
        return handled

    contact = (
        await session.execute(
            select(Contact).where(
                Contact.business_id == business.id, Contact.phone == row.phone, Contact.guardian_id.is_(None)
            )
        )
    ).scalar_one_or_none()
    if contact is None:
        contact = Contact(business_id=business.id, phone=row.phone, name=(meta.get("name") or None))
        session.add(contact)
        await session.flush()
        await session.refresh(contact, ["guardian"])
    elif meta.get("name") and not contact.name:
        contact.name = meta["name"]
    contact.last_inbound_at = now
    if row.chatwoot_conversation_id:
        contact.chatwoot_conversation_id = row.chatwoot_conversation_id
    if meta.get("chatwoot_contact_id"):
        contact.chatwoot_contact_id = meta["chatwoot_contact_id"]
    if meta.get("source_id"):
        contact.chatwoot_source_id = meta["source_id"]
    row.contact_id = contact.id

    if meta.get("has_attachments") and not text_in.strip():
        from wam.messaging import Outgoing, send_to_contact

        await send_to_contact(
            session,
            business,
            contact,
            Outgoing(
                text="I can only read typed messages for now. Please type your question, or a team member will reply here soon."
            ),
            handled_by="staff",
            proactive=False,
        )
        contact.needs_staff = True
        await handoff(business, row.chatwoot_conversation_id, "patient sent a voice note / attachment")
        row.handled_by = "staff"
        row.status = "processed"
        return "staff"

    outcome = await handle_patient_message(
        session,
        business,
        contact,
        text_in,
        conversation_id=row.chatwoot_conversation_id,
        conversation_status=meta.get("conversation_status"),
        conversation_assigned=bool(meta.get("conversation_assigned")),
        inbound_log_id=row.id,
    )
    row.handled_by = outcome.handled_by
    row.status = "processed"
    return outcome.handled_by


async def process_inbound_safely(log_id: int, meta: dict[str, Any] | None = None) -> str:
    """Own transaction; on failure mark the message failed and hand the chat to staff."""
    try:
        async with session_scope() as session:
            return await process_inbound(session, log_id, meta)
    except Exception as exc:
        log.exception("processing inbound message %s failed", log_id)
        async with session_scope() as session:
            row = await session.get(MessageLog, log_id)
            if row is not None:
                row.status = "failed"
                row.error = f"{type(exc).__name__}: {exc}"[:1000]
                business = await session.get(Business, row.business_id)
                if business is not None:
                    await handoff(
                        business, row.chatwoot_conversation_id, "WAM hit an error; please reply by hand"
                    )
        from wam.monitoring import alert

        await alert(f"WAM failed to process inbound message {log_id}: {type(exc).__name__}")
        return "failed"


def normalise_sender(phone: str | None) -> str | None:
    return normalize_phone(phone)
