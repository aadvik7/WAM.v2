"""Announcements: "Send to NEET-A2: …" → preview → YES → sent to each person individually, with read counts.

Messages go out one by one through the worker (in small batches) as the Meta-approved
`wam_announcement` template when the 24-hour window is closed, free text when it is open.
Delivery and read status are read back from Chatwoot a few times after sending.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from wam import clock
from wam.chatwoot import ChatwootError
from wam.jobs.queue import kick_jobs, schedule_job
from wam.messaging import Outgoing, chatwoot_for, send_to_contact, send_to_staff
from wam.models import Broadcast, BroadcastRecipient, Business, Contact, Group, Staff
from wam.people import members_of, parents_of
from wam.templates import get_template

log = logging.getLogger(__name__)

AUDIENCES = ("everyone", "parents", "students")
MAX_MESSAGE = 700
SEND_BATCH = 40
STATUS_RANK = {"queued": 0, "sent": 1, "delivered": 2, "read": 3}
REFRESH_AFTER = (
    dt.timedelta(minutes=10),
    dt.timedelta(hours=1),
    dt.timedelta(hours=6),
    dt.timedelta(hours=24),
)


class BroadcastError(Exception):
    pass


def clean_message(message: str) -> str:
    text = re.sub(r"[ \t]+", " ", (message or "").strip())
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not text:
        raise BroadcastError("The message is empty.")
    if len(text) > MAX_MESSAGE:
        raise BroadcastError(f"Please keep announcements under {MAX_MESSAGE} characters.")
    return text


async def audience_targets(
    session: AsyncSession, group: Group, audience: str
) -> tuple[list[Contact], dict[str, int]]:
    """Each person individually: students (own numbers) and/or their parents, deduplicated."""
    if audience not in AUDIENCES:
        raise BroadcastError("Audience must be everyone, parents or students.")
    targets: dict[int, Contact] = {}
    counts = {"students": 0, "parents": 0, "unreachable": 0}
    for student in await members_of(session, group.id):
        reached = False
        if audience in ("everyone", "students") and student.phone:
            if student.id not in targets:
                targets[student.id] = student
                counts["students"] += 1
            reached = True
        if audience in ("everyone", "parents"):
            for parent in await parents_of(session, student):
                if not parent.phone:
                    continue
                reached = True
                if parent.id not in targets:
                    targets[parent.id] = parent
                    counts["parents"] += 1
        if not reached:
            counts["unreachable"] += 1
    return list(targets.values()), counts


def preview(group: Group, message: str) -> str:
    """Exactly what people outside the 24-hour window receive (the approved template)."""
    return get_template("announcement").render({"batch": group.name, "message": message.rstrip(".")})


async def create_broadcast(
    session: AsyncSession,
    business: Business,
    group: Group,
    message: str,
    audience: str = "everyone",
    *,
    staff: Staff | None = None,
    admin_user_id: int | None = None,
) -> Broadcast:
    text = clean_message(message)
    targets, counts = await audience_targets(session, group, audience)
    if not targets:
        raise BroadcastError(f"Nobody in {group.name} has a WhatsApp number for this audience yet.")
    broadcast = Broadcast(
        business_id=business.id,
        group_id=group.id,
        template_name=get_template("announcement").name,
        params={"batch": group.name, "counts": counts},
        message=text,
        audience=audience,
        status="draft",
        sender_staff_id=staff.id if staff else None,
        created_by_admin_id=admin_user_id,
        recipients_count=len(targets),
    )
    session.add(broadcast)
    await session.flush()
    for person in targets:
        session.add(
            BroadcastRecipient(
                broadcast_id=broadcast.id,
                contact_id=person.id,
                phone=person.phone,
                status="skipped" if person.opted_out else "queued",
                error="opted out" if person.opted_out else None,
            )
        )
    await session.flush()
    return broadcast


async def start(session: AsyncSession, business: Business, broadcast: Broadcast) -> None:
    if broadcast.status != "draft":
        raise BroadcastError("This announcement was already sent or cancelled.")
    broadcast.status = "sending"
    await schedule_job(
        session,
        business.id,
        "broadcast_send",
        clock.now(),
        {"broadcast_id": broadcast.id},
        dedupe_key=f"broadcast_send:{broadcast.id}:0",
    )
    await kick_jobs()


async def cancel(session: AsyncSession, broadcast: Broadcast) -> None:
    if broadcast.status not in ("draft", "sending"):
        raise BroadcastError("Only a draft or sending announcement can be cancelled.")
    broadcast.status = "cancelled"
    rows = (
        await session.execute(
            select(BroadcastRecipient).where(
                BroadcastRecipient.broadcast_id == broadcast.id, BroadcastRecipient.status == "queued"
            )
        )
    ).scalars()
    for row in rows:
        row.status = "skipped"
        row.error = "cancelled"


async def recount(session: AsyncSession, broadcast: Broadcast) -> dict[str, int]:
    counts = dict(
        (
            await session.execute(
                select(BroadcastRecipient.status, func.count(BroadcastRecipient.id))
                .where(BroadcastRecipient.broadcast_id == broadcast.id)
                .group_by(BroadcastRecipient.status)
            )
        ).all()
    )
    broadcast.sent_count = sum(counts.get(k, 0) for k in ("sent", "delivered", "read"))
    broadcast.delivered_count = counts.get("delivered", 0) + counts.get("read", 0)
    broadcast.read_count = counts.get("read", 0)
    broadcast.failed_count = counts.get("failed", 0)
    return counts


async def send_batch(
    session: AsyncSession, business: Business, broadcast: Broadcast, limit: int = SEND_BATCH
) -> bool:
    """Send up to `limit` queued messages. Returns True if more remain."""
    if broadcast.status != "sending":
        return False
    group = await session.get(Group, broadcast.group_id) if broadcast.group_id else None
    batch_name = group.name if group else str(broadcast.params.get("batch", "Batch"))
    rows = (
        (
            await session.execute(
                select(BroadcastRecipient)
                .where(BroadcastRecipient.broadcast_id == broadcast.id, BroadcastRecipient.status == "queued")
                .order_by(BroadcastRecipient.id)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    text = f"{batch_name} update: {broadcast.message}\n\nReply here if you have questions."
    for row in rows:
        out = Outgoing(
            text=text,
            template_key="announcement",
            template_values={"batch": batch_name, "message": broadcast.message.rstrip(".")},
        )
        sent = await send_to_contact(session, business, row.contact, out, handled_by="staff", proactive=True)
        if sent is None:
            row.status = "skipped"
            row.error = "not reachable (opted out or no number)"
        elif sent.status in ("ok", "dry_run"):
            row.status = "sent"
            row.chatwoot_conversation_id = sent.chatwoot_conversation_id
            row.chatwoot_message_id = sent.chatwoot_message_id
        else:
            row.status = "failed"
            row.error = sent.error
    await session.flush()
    await recount(session, broadcast)
    remaining = (
        await session.execute(
            select(func.count(BroadcastRecipient.id)).where(
                BroadcastRecipient.broadcast_id == broadcast.id, BroadcastRecipient.status == "queued"
            )
        )
    ).scalar_one()
    if remaining:
        return True
    broadcast.status = "sent"
    broadcast.sent_at = clock.now()
    for i, delay in enumerate(REFRESH_AFTER):
        await schedule_job(
            session,
            business.id,
            "broadcast_status",
            clock.now() + delay,
            {"broadcast_id": broadcast.id},
            dedupe_key=f"broadcast_status:{broadcast.id}:{i}",
        )
    if broadcast.sender_staff_id:
        staff = await session.get(Staff, broadcast.sender_staff_id)
        if staff is not None:
            note = f"Announcement to {batch_name} sent to {broadcast.sent_count} of {broadcast.recipients_count} people"
            if broadcast.failed_count:
                note += f" ({broadcast.failed_count} failed)"
            await send_to_staff(
                session, business, staff, Outgoing(text=note + ". Read counts are in WAM admin.")
            )
    return False


async def refresh_status(session: AsyncSession, business: Business, broadcast: Broadcast) -> int:
    """Read WhatsApp delivery/read status back from Chatwoot. Returns how many recipients changed."""
    client = chatwoot_for(business)
    if client is None:
        return 0
    rows = (
        (
            await session.execute(
                select(BroadcastRecipient).where(
                    BroadcastRecipient.broadcast_id == broadcast.id,
                    BroadcastRecipient.status.in_(("sent", "delivered")),
                    BroadcastRecipient.chatwoot_conversation_id.is_not(None),
                    BroadcastRecipient.chatwoot_message_id.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    by_conversation: dict[int, list[BroadcastRecipient]] = {}
    for row in rows:
        by_conversation.setdefault(int(row.chatwoot_conversation_id or 0), []).append(row)
    changed = 0
    for conversation_id, recipients in by_conversation.items():
        try:
            messages = await client.list_messages(conversation_id)
        except ChatwootError as exc:
            log.warning("status refresh failed for conversation %s: %s", conversation_id, exc)
            continue
        status_by_id: dict[int, str] = {
            int(m["id"]): str(m.get("status") or "") for m in messages if m.get("id")
        }
        for row in recipients:
            new = status_by_id.get(int(row.chatwoot_message_id or 0))
            if new == "failed":
                row.status, row.error = "failed", "WhatsApp delivery failed"
                changed += 1
            elif new in STATUS_RANK and STATUS_RANK[new] > STATUS_RANK.get(row.status, 0):
                row.status = new
                changed += 1
    await session.flush()
    await recount(session, broadcast)
    return changed


def summary(broadcast: Broadcast, group: Group | None, tz: str) -> dict[str, Any]:
    return {
        "id": broadcast.id,
        "group_id": broadcast.group_id,
        "batch": group.name if group else broadcast.params.get("batch"),
        "message": broadcast.message,
        "audience": broadcast.audience,
        "status": broadcast.status,
        "recipients": broadcast.recipients_count,
        "sent": broadcast.sent_count,
        "delivered": broadcast.delivered_count,
        "read": broadcast.read_count,
        "failed": broadcast.failed_count,
        "counts": broadcast.params.get("counts", {}),
        "preview": preview(group, broadcast.message) if group else broadcast.message,
        "created_at": clock.to_local(broadcast.created_at, tz).isoformat(),
        "sent_at": clock.to_local(broadcast.sent_at, tz).isoformat() if broadcast.sent_at else None,
    }
