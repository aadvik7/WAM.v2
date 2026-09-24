"""WAM core FastAPI application."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from wam.api import auth, health, patients, reports, setup, simulator
from wam.config import get_settings
from wam.db import dispose_engine
from wam.jobs.queue import close_pool
from wam.logging_setup import setup_logging
from wam.packs.institute import api as institute_api
from wam.router import webhook

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings.log_level)
    if settings.is_production:
        if settings.secret_key == "change-me-in-production" or len(settings.secret_key) < 32:
            raise RuntimeError("Set SECRET_KEY (32+ random characters) before running in production")
        if settings.webhook_secret == "change-me-webhook-secret" or len(settings.webhook_secret) < 16:
            raise RuntimeError("Set WEBHOOK_SECRET (16+ random characters) before running in production")
    log.info("WAM core starting (chatwoot=%s, ai=%s)", settings.chatwoot_enabled, settings.ai_enabled)
    yield
    await close_pool()
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="WAM core", version="1.0.0", lifespan=lifespan)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.include_router(health.router)
    app.include_router(webhook.router)
    app.include_router(auth.router)
    app.include_router(setup.router)
    app.include_router(patients.router)
    app.include_router(reports.router)
    app.include_router(simulator.router)
    app.include_router(institute_api.router)
    return app


app = create_app()
