"""Chatwoot agent-bot webhook: Chatwoot -> WAM core.

Configure the agent bot's outgoing URL as  https://<core-host>/webhooks/chatwoot/<WEBHOOK_SECRET>
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from sqlalchemy import select

from wam.config import get_settings
from wam.db import session_scope
from wam.jobs.queue import enqueue
from wam.models import Business, Contact
from wam.packs import get_pack
from wam.phone import normalize_phone
from wam.router.inbound import Inbound, process_inbound_safely, record_inbound

log = logging.getLogger(__name__)
router = APIRouter()


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def parse_chatwoot_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Extract what WAM needs from a `message_created` event; None if it should be ignored."""
    if payload.get("event") != "message_created":
        return None
    if payload.get("message_type") not in ("incoming", 0):
        return None
    if payload.get("private"):
        return None
    conversation = payload.get("conversation") or {}
    meta = conversation.get("meta") or {}
    sender = payload.get("sender") or meta.get("sender") or {}
    if sender.get("type") not in (None, "contact"):
        return None
    contact_inbox = conversation.get("contact_inbox") or {}
    phone = sender.get("phone_number") or contact_inbox.get("source_id") or ""
    return {
        "account_id": _int((payload.get("account") or {}).get("id")),
        "inbox_id": _int((payload.get("inbox") or {}).get("id") or conversation.get("inbox_id")),
        "phone": phone,
        "name": sender.get("name"),
        "text": (payload.get("content") or "").strip(),
        "has_attachments": bool(payload.get("attachments")),
        "conversation_id": _int(conversation.get("id")),
        "conversation_status": conversation.get("status"),
        "conversation_assigned": bool(meta.get("assignee") or conversation.get("assignee_id")),
        "chatwoot_contact_id": _int(sender.get("id")),
        "chatwoot_message_id": _int(payload.get("id")),
        "source_id": contact_inbox.get("source_id"),
    }


def verify_signature(secret: str, body: bytes, timestamp: str | None, signature: str | None) -> bool:
    """Chatwoot signs agent-bot webhooks: X-Chatwoot-Signature = sha256=HMAC(secret, "<ts>.<body>")."""
    if not timestamp or not signature:
        return False
    try:
        if abs(time.time() - int(timestamp)) > 300:
            return False
    except ValueError:
        return False
    expected = (
        "sha256=" + hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    )
    return hmac.compare_digest(expected, signature)


async def _business_for(session: Any, account_id: int | None, inbox_id: int | None) -> Business | None:
    if account_id is None or inbox_id is None:
        return None
    rows = (
        await session.execute(
            select(Business).where(Business.chatwoot_account_id == account_id, Business.is_active.is_(True))
        )
    ).scalars()
    return next((b for b in rows if b.chatwoot_inbox_id == inbox_id), None)


async def handle_conversation_event(payload: dict[str, Any], raw: bytes, request: Request) -> dict[str, Any]:
    """Staff resolved a chat in the inbox: the handoff is over, so WAM answers that patient again."""
    if payload.get("status") != "resolved":
        return {"ok": True, "ignored": True}
    sender = (payload.get("meta") or {}).get("sender") or {}
    phone = normalize_phone(sender.get("phone_number"))
    async with session_scope() as session:
        business = await _business_for(
            session, _int((payload.get("account") or {}).get("id")), _int(payload.get("inbox_id"))
        )
        if business is None or phone is None:
            return {"ok": True, "ignored": True}
        if business.chatwoot_webhook_secret and not verify_signature(
            business.chatwoot_webhook_secret,
            raw,
            request.headers.get("x-chatwoot-timestamp"),
            request.headers.get("x-chatwoot-signature"),
        ):
            raise HTTPException(status_code=401, detail="bad signature")
        contact = (
            await session.execute(
                select(Contact).where(
                    Contact.business_id == business.id, Contact.phone == phone, Contact.guardian_id.is_(None)
                )
            )
        ).scalar_one_or_none()
        if contact is not None:
            hooks = get_pack(business.type).hook_module()
            if hooks is not None:
                await hooks.on_conversation_resolved(session, business, contact)
        if contact is not None and contact.needs_staff:
            contact.needs_staff = False
            return {"ok": True, "handoff_cleared": True}
    return {"ok": True}


@router.post("/webhooks/chatwoot/{secret}")
async def chatwoot_webhook(secret: str, request: Request, background: BackgroundTasks) -> dict[str, Any]:
    settings = get_settings()
    if not hmac.compare_digest(secret.encode(), settings.webhook_secret.encode()):
        raise HTTPException(status_code=404)
    raw = await request.body()
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON") from exc
    payload = payload if isinstance(payload, dict) else {}
    if payload.get("event") in ("conversation_resolved", "conversation_status_changed"):
        return await handle_conversation_event(payload, raw, request)
    data = parse_chatwoot_payload(payload)
    if data is None:
        return {"ok": True, "ignored": True}
    phone = normalize_phone(data["phone"])
    if phone is None or (not data["text"] and not data["has_attachments"]):
        return {"ok": True, "ignored": True}

    if data["account_id"] is None or data["inbox_id"] is None:
        return {"ok": True, "ignored": True, "reason": "missing account or inbox"}

    async with session_scope() as session:
        business = await _business_for(session, data["account_id"], data["inbox_id"])
        if business is None:
            log.warning("no business for Chatwoot account=%s inbox=%s", data["account_id"], data["inbox_id"])
            return {"ok": True, "ignored": True, "reason": "unknown inbox"}
        if business.chatwoot_webhook_secret and not verify_signature(
            business.chatwoot_webhook_secret,
            raw,
            request.headers.get("x-chatwoot-timestamp"),
            request.headers.get("x-chatwoot-signature"),
        ):
            raise HTTPException(status_code=401, detail="bad signature")
        inbound = Inbound(
            business_id=business.id,
            phone=phone,
            text=data["text"][:4000],
            name=data["name"],
            conversation_id=data["conversation_id"],
            conversation_status=data["conversation_status"],
            conversation_assigned=data["conversation_assigned"],
            chatwoot_contact_id=data["chatwoot_contact_id"],
            chatwoot_message_id=data["chatwoot_message_id"],
            source_id=data["source_id"],
            has_attachments=data["has_attachments"],
        )
        log_id = await record_inbound(session, inbound)
    if log_id is None:
        return {"ok": True, "duplicate": True}

    meta = inbound.meta()
    if settings.process_inline:
        background.add_task(process_inbound_safely, log_id, meta)
    else:
        try:
            await enqueue("handle_inbound", log_id, meta, job_id=f"inbound:{log_id}")
        except Exception as exc:  # Redis down: still answer the patient
            log.warning("enqueue failed (%s); processing in-process", exc)
            background.add_task(process_inbound_safely, log_id, meta)
    return {"ok": True, "queued": log_id}
