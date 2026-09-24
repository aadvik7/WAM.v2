# Deploying WAM

Production is one VPS in Mumbai (8 GB RAM, so patient data stays in India) running Chatwoot, WAM core, the
WAM worker, Postgres and Redis with Docker Compose, plus Caddy for HTTPS. The WAM admin runs on Vercel and
calls WAM core's API. Budget roughly 4 GB for Chatwoot, 1 GB for Postgres and under 1 GB for WAM.

## 0. Start Meta verification in week 1

Connecting clinics' numbers needs Meta Tech Provider status or a WhatsApp partner (BSP) as a fallback.
Verification takes weeks, so start immediately:

1. Create a Meta Business account and complete **business verification**.
2. Create a Meta app with the **WhatsApp** product; add a test number first, then each clinic's verified
   number. Personal WhatsApp numbers can't be connected.
3. Create a **System User** with a permanent token that has `whatsapp_business_messaging` and
   `whatsapp_business_management` — Chatwoot needs it.
4. Submit the templates in [whatsapp-templates.md](whatsapp-templates.md) (week 2) and wait for approval.

## 1. Server

```bash
# Ubuntu 24.04 VPS in Mumbai, 8 GB RAM, 4 vCPU, 80+ GB disk
curl -fsSL https://get.docker.com | sh
git clone <this repo> /opt/wam && cd /opt/wam/infra
cp .env.example .env && nano .env          # fill every value; secrets via `openssl rand -hex 32`
```

DNS: point `INBOX_DOMAIN` (e.g. `inbox.yourdomain.in`) and `API_DOMAIN` (e.g. `api.yourdomain.in`) at the
server. Open ports 80 and 443 only.

## 2. Start the stack

```bash
./deploy.sh
```

This pulls images, builds WAM core, prepares Chatwoot's database, applies the WAM branding to the inbox,
runs WAM's migrations, creates the first WAM admin from `BOOTSTRAP_ADMIN_EMAIL`/`PASSWORD`, and starts
everything. Caddy fetches HTTPS certificates automatically. Check:

```bash
curl https://api.yourdomain.in/health     # {"status":"ok", ...} once the worker has ticked
docker compose ps
```

Re-run `./deploy.sh` after every `git pull` to update.

## 3. Chatwoot (WAM inbox)

1. Open `https://INBOX_DOMAIN`, create the super admin, then an **account per clinic** (or one account with
   one inbox per clinic).
2. **Inboxes → Add inbox → WhatsApp → WhatsApp Cloud** with the clinic's phone number ID, WABA ID and the
   System User token. Copy the webhook URL/verify token Chatwoot shows into the Meta app's WhatsApp webhook.
3. Create the WAM agent bot and attach it to the inbox:

   ```bash
   docker compose run --rm -e ACCOUNT_ID=1 -e INBOX_ID=1 \
     -e WAM_WEBHOOK_URL=https://api.yourdomain.in/webhooks/chatwoot/<WAM_WEBHOOK_SECRET> \
     chatwoot bundle exec rails runner /wam/setup_bot.rb
   ```

   It prints the bot token and webhook secret. (By hand: Settings → Bots → add a bot with that URL, then
   Inbox → Settings → Bot.) Use the **public** `https://` URL — Chatwoot refuses private addresses.
4. Create an admin agent for WAM (e.g. "WAM system") and copy its **access token** from Profile settings.
   WAM uses it to create contacts/conversations for reminders; the bot token is used for replies.
5. Invite the clinic's staff as agents so they can reply by hand when WAM hands a chat over.

## 4. WAM admin on Vercel

1. Import the repo in Vercel with **Root Directory** `admin`.
2. Environment variables: `CORE_URL=https://api.yourdomain.in`, `COOKIE_SECURE=true`.
3. Deploy, open the admin and sign in with the bootstrap admin.

Alternative: self-host it on the VPS with `docker compose --profile admin up -d` and set `ADMIN_DOMAIN`.

## 5. Set up the clinic in WAM admin

1. **Businesses** → add the clinic (type *Clinic*); starter plans and roles are created for you.
2. **Setup → Clinic**: address, maps link, opening hours, emergency number, privacy policy URL, reminder and
   end-of-day times, template language (must match the approved templates, e.g. `en`).
3. **Setup → Doctors & hours**: each doctor, specialty (matches plan specialties), slot length, weekly hours,
   breaks and leave. Link each doctor to their staff record so "Cancel my 5 pm" knows who "my" is.
4. **Setup → Plan templates**: edit gaps, visit counts, labels, aliases.
5. **Setup → FAQ**: fees, reports, payment, parking, insurance.
6. **Setup → Staff & roles**: every doctor and front-desk person with their own WhatsApp number, role and a
   PIN; tick *Gets the end-of-day list* for the front desk.
7. **Setup → WhatsApp connection**: Chatwoot account ID, inbox ID, admin token, bot token and webhook secret.
8. Test: send "hi" to the clinic number from your phone; then "Today's list" from a staff phone.
9. Optional: add `ANTHROPIC_API_KEY` to `infra/.env` and re-run `./deploy.sh` to switch on the AI agent.

### Setting up an institute instead

Same steps, with these differences:

1. **Businesses** → add the institute with type *Institute*. Starter plans (fee installments,
   parent-teacher meeting) and roles (owner, coordinator, teacher, front desk) are created for you.
2. **Setup → Teachers & hours**: add teachers who take parent-teacher meetings (subject, slot length). They
   don't need weekly hours; each meeting adds its own hours.
3. **Setup → Staff & roles**: every coordinator, teacher and front-desk person with their WhatsApp number,
   role and PIN.
4. **Uploads → Students**: import the student list (roll number, name, student phone, 1–2 parent phones,
   batch). Then **Batches** → each batch → tick its teachers.
5. **Uploads → Timetable**: the weekly timetable (batch, day, start, end, subject, teacher, room).
6. **Doubts → Subjects**: in the WAM inbox create one team per subject (Settings → Teams), add that subject's
   teachers as agents, and enter each team's number against the subject in WAM admin.
7. **Setup → Plan templates → Fee installments**: amount per installment, number of installments, days
   between them and how many days before the due date to remind.
8. Submit the institute templates to Meta (`wam_announcement`, `wam_absence_alert`, `wam_test_result`,
   `wam_fee_reminder`, plus the shared ones); see [whatsapp-templates.md](whatsapp-templates.md).
9. Test: from a coordinator's phone send `Send to <batch>: test` and reply `YES <PIN>`; from a student's phone
   send `Doubt: …` and check it lands with the right team.

## 6. Backups and monitoring

```bash
crontab -e     # paste infra/crontab.example (adjust /opt/wam)
```

- `backup.sh` dumps both databases nightly, keeps 30 days, and copies to separate storage when
  `BACKUP_REMOTE` is set (install and configure `rclone` first, e.g. Backblaze B2 or S3 in `ap-south-1`).
- **Test a restore before the pilot**: `./restore.sh wam backups/wam-<stamp>.dump` on a staging copy.
- `monitor.sh` checks WAM core's `/health` (database, Redis, worker heartbeat, failed sends, unprocessed
  messages) and the inbox every 5 minutes and posts to `ALERT_WEBHOOK_URL` (Slack, Discord or an ntfy topic).
  WAM core also posts alerts when message processing or jobs fail.
- If WAM core is down, Chatwoot still shows every message (and opens the chat when the bot webhook fails),
  so staff can reply by hand.

## Configuration reference

WAM core reads environment variables (see `core/wam/config.py` and `core/.env.example`):

| Variable | Meaning |
| --- | --- |
| `DATABASE_URL`, `REDIS_URL` | Postgres (asyncpg URL) and Redis |
| `SECRET_KEY` | signs admin sessions (32+ random characters) |
| `WEBHOOK_SECRET` | path secret in the agent-bot URL |
| `CHATWOOT_BASE_URL` | Chatwoot URL reachable from WAM core; empty = dry run |
| `CHATWOOT_API_TOKEN`, `CHATWOOT_BOT_TOKEN` | defaults when a clinic has no tokens set in the admin |
| `CHATWOOT_TEMPLATE_FORMAT` | `enhanced` (Chatwoot 4.x, default) or `legacy` |
| `ANTHROPIC_API_KEY`, `AI_MODEL` | AI agent (default `claude-haiku-4-5`); empty key = rules only |
| `ENABLE_SIMULATOR` | admin simulator endpoints (admin login still required) |
| `ALERT_WEBHOOK_URL` | where failure alerts go |
| `PROCESS_INLINE` | process webhooks in the API process instead of the queue (small installs/dev) |

Per-clinic behaviour (send window, reminder time, end-of-day time, follow-up hours, retention, consent text,
extra emergency words, AI on/off) is edited in WAM admin → Setup → Clinic.
