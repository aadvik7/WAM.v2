"""Minimal Chatwoot API client (application API, api_access_token auth)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from wam.config import get_settings

log = logging.getLogger(__name__)


class ChatwootError(Exception):
    pass


def _unwrap(data: Any) -> Any:
    """Chatwoot wraps some responses in {"payload": ...}."""
    if isinstance(data, dict) and "payload" in data and len(data) <= 2:
        return data["payload"]
    return data


class ChatwootClient:
    def __init__(self, base_url: str, account_id: int, api_token: str, bot_token: str | None = None):
        if not base_url:
            raise ChatwootError("Chatwoot base URL is not configured")
        self.base_url = base_url.rstrip("/")
        self.account_id = account_id
        self.api_token = api_token
        self.bot_token = bot_token or api_token

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/v1/accounts/{self.account_id}{path}"

    async def _request(
        self, method: str, path: str, *, json: Any = None, params: Any = None, token: str | None = None
    ) -> Any:
        token = token or self.api_token
        if not token:
            raise ChatwootError("Chatwoot API token is not configured")
        timeout = get_settings().chatwoot_timeout_seconds
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.request(
                    method, self._url(path), json=json, params=params, headers={"api_access_token": token}
                )
        except httpx.HTTPError as exc:
            raise ChatwootError(f"Chatwoot request failed: {exc}") from exc
        if resp.status_code >= 400:
            raise ChatwootError(f"Chatwoot {method} {path} -> {resp.status_code}: {resp.text[:300]}")
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    # --- Messages & conversations ---------------------------------------------------

    async def send_message(
        self,
        conversation_id: int,
        content: str,
        *,
        private: bool = False,
        template_params: dict[str, Any] | None = None,
        as_bot: bool = True,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"content": content, "message_type": "outgoing", "private": private}
        if template_params:
            body["template_params"] = template_params
        data = await self._request(
            "POST",
            f"/conversations/{conversation_id}/messages",
            json=body,
            token=self.bot_token if as_bot else self.api_token,
        )
        return data or {}

    async def toggle_status(self, conversation_id: int, status: str) -> None:
        await self._request(
            "POST",
            f"/conversations/{conversation_id}/toggle_status",
            json={"status": status},
            token=self.bot_token,
        )

    async def set_priority(self, conversation_id: int, priority: str) -> None:
        await self._request(
            "POST", f"/conversations/{conversation_id}/toggle_priority", json={"priority": priority}
        )

    async def add_labels(self, conversation_id: int, labels: list[str]) -> None:
        await self._request("POST", f"/conversations/{conversation_id}/labels", json={"labels": labels})

    async def create_conversation(
        self,
        *,
        inbox_id: int,
        contact_id: int,
        source_id: str,
        message: dict[str, Any] | None = None,
        status: str = "pending",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "inbox_id": inbox_id,
            "contact_id": contact_id,
            "source_id": source_id,
            "status": status,
        }
        if message:
            body["message"] = message
        data = await self._request("POST", "/conversations", json=body)
        return _unwrap(data) or {}

    async def contact_conversations(self, contact_id: int) -> list[dict[str, Any]]:
        data = _unwrap(await self._request("GET", f"/contacts/{contact_id}/conversations"))
        return data if isinstance(data, list) else []

    # --- Contacts -------------------------------------------------------------------

    async def search_contact(self, phone: str) -> dict[str, Any] | None:
        data = _unwrap(
            await self._request("GET", "/contacts/search", params={"q": phone, "include_contacts": "true"})
        )
        items = data if isinstance(data, list) else []
        digits = "".join(ch for ch in phone if ch.isdigit())
        for item in items:
            cand = "".join(ch for ch in str(item.get("phone_number") or "") if ch.isdigit())
            if cand and cand == digits:
                return item
        return None

    async def create_contact(self, *, inbox_id: int, name: str | None, phone: str) -> dict[str, Any]:
        body = {"inbox_id": inbox_id, "name": name or phone, "phone_number": phone}
        data = await self._request("POST", "/contacts", json=body)
        payload = _unwrap(data) or {}
        if isinstance(payload, dict) and "contact" in payload:
            contact = dict(payload["contact"])
            if payload.get("contact_inbox"):
                contact.setdefault("contact_inboxes", [payload["contact_inbox"]])
            return contact
        return payload

    async def create_contact_inbox(self, contact_id: int, inbox_id: int, source_id: str) -> dict[str, Any]:
        data = await self._request(
            "POST",
            f"/contacts/{contact_id}/contact_inboxes",
            json={"inbox_id": inbox_id, "source_id": source_id},
        )
        return _unwrap(data) or {}


def source_id_for(contact: dict[str, Any], inbox_id: int) -> str | None:
    for ci in contact.get("contact_inboxes") or []:
        inbox = ci.get("inbox") or {}
        if inbox.get("id") == inbox_id or ci.get("inbox_id") == inbox_id:
            return ci.get("source_id")
    return None
