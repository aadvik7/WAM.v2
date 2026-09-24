"""Alerts: posts JSON {"text": ...} to ALERT_WEBHOOK_URL (Slack/Discord/ntfy-compatible), rate limited."""

from __future__ import annotations

import logging
import time

import httpx

from wam.config import get_settings

log = logging.getLogger(__name__)

_last_sent: dict[str, float] = {}
MIN_INTERVAL_SECONDS = 600


async def alert(text: str, key: str | None = None) -> None:
    log.error("ALERT: %s", text)
    url = get_settings().alert_webhook_url
    if not url:
        return
    key = key or text[:60]
    now = time.monotonic()
    if now - _last_sent.get(key, -1e9) < MIN_INTERVAL_SECONDS:
        return
    _last_sent[key] = now
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json={"text": f"[WAM] {text}", "content": f"[WAM] {text}"})
    except httpx.HTTPError as exc:
        log.warning("alert webhook failed: %s", exc)
