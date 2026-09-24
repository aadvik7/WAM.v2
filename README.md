# WAM

WAM is an assistant on a clinic's official WhatsApp number. It answers patients, books visits and brings
people back when their next visit is due, so **patients finish their treatment**. The full product spec is in
[CLAUDE.md](CLAUDE.md).

This repository contains version 1: the shared engine plus the clinic pack.

| Part | What it does | Where |
| --- | --- | --- |
| **WAM core** | Webhook router (staff vs patient), AI agent + tools, slot engine, schedules, reminders, staff commands, admin API | [`core/`](core) — Python, FastAPI, SQLAlchemy, arq |
| **WAM admin** | Setup, patients and plans, today's list, reports, simulator | [`admin/`](admin) — Next.js 16 |
| **WAM inbox** | WhatsApp connection and shared inbox: Chatwoot, configured and rebranded (not rewritten) | [`chatwoot/`](chatwoot) + [`infra/`](infra) |
| **Infra** | Docker Compose for one Mumbai VPS, HTTPS, backups, monitoring | [`infra/`](infra) |

```
Patient / staff on WhatsApp → WhatsApp Cloud API → Chatwoot inbox ──agent-bot webhook──► WAM core
                                                         ▲                               │  router → staff commands
                                                         └──── replies, templates ◄──────┤  router → AI agent + tools
                                                                                          │  scheduler (arq, every minute)
WAM admin (Next.js) ───────── admin API (JWT) ───────────────────────────────────────────►│  Postgres + Redis
```

## What works

- **Patient chats**: consent notice on first chat (DPDP), timings/address/fees from the clinic's own FAQ,
  booking by picking a numbered slot, rescheduling, confirming, cancelling, STOP/START, voice notes handed to
  staff. Emergency words (English, Hindi, Hinglish) trigger an instant emergency-number reply, an urgent
  handoff in the inbox and a WhatsApp alert to the front desk. WAM never gives medical advice.
- **AI agent** (Claude Haiku via the Anthropic API): understands free text and picks tools; plain code makes
  every booking decision and re-checks the slot under a database lock. Without an API key, WAM runs on rules.
- **Slot engine**: availability − appointments − breaks − leave, slot grid, minimum notice, booking horizon;
  a row lock plus a Postgres exclusion constraint make double booking impossible.
- **Return-visit loop**: enrol → nudge with 3 free slots when due → book → day-before reminder (reply 1/2)
  → end-of-day attendance check with the front desk → missed-visit follow-ups after 24h and again after 48h
  → flag to staff. Recalls for ongoing plans, re-nudges, visits recovered tracked per appointment.
- **Plan templates**: root canal, braces, cleaning recall, laser/peel, physio, vaccination (age-based from
  date of birth), chronic review, follow-up — all editable.
- **Staff commands on WhatsApp**: today's list, cancel my 5 pm (YES + PIN), running 20 min late, on leave
  Friday (YES + PIN), "Rahul, root canal", follow-up in 7 days, find, summary, attendance replies. PIN
  lockout after 5 wrong tries; every action audited. Free-form staff messages are rewritten by the AI into a
  command, then the same parser and confirmations apply.
- **WhatsApp rules**: 24-hour window respected (free text inside, Meta templates outside), messages only in
  the clinic's send window, template names/params in Chatwoot 4.x format, per-clinic template language.
- **Admin**: today's list with came/missed/cancel/move, due-but-unbooked plans, patients and plans,
  appointment booking with a slot picker, setup (hours, doctors, leave, plan templates, FAQ, staff, roles,
  PINs, WhatsApp connection), reports (visits recovered, plan completion, no-shows, answered without staff),
  message log, audit log, template list for Meta, and a **simulator** to test everything without WhatsApp.
- **Ops**: health endpoint (DB, Redis, worker heartbeat, failed sends), alerts to a webhook, nightly backups
  with 30-day retention and off-site copy, restore script, data-retention job, right-to-erasure.

Institute and business packs load with generic wording, booking, FAQ and handoff on the same engine; their
dedicated features (broadcasts, doubt queue, Excel uploads) are version 2 and 3.

## Run it locally (about 5 minutes)

Requirements: Python 3.11+, Node 22+, Postgres 16 (with contrib) and Redis 7.

```bash
# 1. Databases
psql -U postgres -c "CREATE USER wam WITH SUPERUSER PASSWORD 'wam'"   # or run postgres/redis in Docker
createdb -U postgres -O wam wam && createdb -U postgres -O wam wam_test

# 2. WAM core
cd core
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                       # defaults work for local dev
python -m wam.cli migrate
python -m wam.cli create-admin --email you@example.com --password 'a-long-password'
python -m wam.cli seed-demo                # optional: demo clinic, doctor, staff, patients, FAQ
uvicorn wam.main:app --reload --port 8000  # API
arq wam.jobs.worker.WorkerSettings         # in another terminal: queue + scheduler

# 3. WAM admin
cd ../admin
npm install
CORE_URL=http://localhost:8000 npm run dev # http://localhost:3000
```

Sign in, open **Simulator**, and chat as a patient (`9811111111`) or as staff (`+919800000002`, PIN `4321`
in the demo). Without `CHATWOOT_BASE_URL` nothing is sent to WhatsApp; messages are logged as `dry_run`.
Add `ANTHROPIC_API_KEY` to `core/.env` to switch on the AI agent.

## Tests

```bash
cd core && pytest -q        # needs Postgres (TEST_DATABASE_URL) and Redis; see tests/conftest.py
ruff check wam tests
cd ../admin && npm run build
```

The suite (53 tests) runs against real Postgres and covers the slot engine, concurrent double-booking,
schedules, the full 3-sitting root-canal loop including a missed visit, staff commands with YES + PIN and
lockout, emergency handoff, the AI tool loop (scripted model), Chatwoot webhooks, signatures and template
delivery, and the admin API. CI runs the same on every push ([.github/workflows/ci.yml](.github/workflows/ci.yml)).

## Deploy

See **[docs/deployment.md](docs/deployment.md)**: one VPS in Mumbai via Docker Compose (Chatwoot, WAM core,
worker, Postgres, Redis, Caddy for HTTPS), WAM admin on Vercel, Meta/WhatsApp setup, templates, backups and
monitoring.

More docs:
- [docs/staff-guide.md](docs/staff-guide.md) — what doctors and the front desk can send on WhatsApp
- [docs/whatsapp-templates.md](docs/whatsapp-templates.md) — templates to submit to Meta
- [docs/privacy-and-safety.md](docs/privacy-and-safety.md) — DPDP, medical safety, security

## Repository layout

```
core/            WAM core (FastAPI)
  wam/router/    Chatwoot webhook, inbound pipeline, patient conversation handling
  wam/agent/     AI agent loop, tools, emergency detection
  wam/engine/    slots, appointments, schedules
  wam/packs/     clinic (v1), institute and business packs
  wam/staff/     staff command parser, dates, commands with YES + PIN
  wam/jobs/      arq worker, scheduler tick, durable jobs
  wam/api/       admin REST API, reports, simulator, health
  alembic/       database migrations
  tests/
admin/           WAM admin (Next.js)
chatwoot/        rebrand assets + scripts (branding, agent-bot setup)
infra/           docker-compose, Caddyfile, deploy, backup, restore, monitor
docs/
```
