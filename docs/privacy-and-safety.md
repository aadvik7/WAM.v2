# Privacy, medical safety and security

## DPDP Act

- **Consent notice on the first chat**: the text is set per clinic (Setup → Clinic → Consent message) and
  includes the privacy policy link. Continuing the chat after the notice records consent (`consent_at`);
  `STOP` opts the patient out of all reminders and proactive messages (`START` turns them back on).
- **Purpose limitation**: numbers and messages are used only to manage bookings, reminders and updates. Nothing is sold
  or used for ads.
- **Data retention**: message logs older than the clinic's retention period (default 365 days) are deleted
  every night at 03:00.
- **Right to erasure**: WAM admin → patient → *Erase patient data* deletes the patient, their plans, visits
  and messages. (Also erase the contact in the Chatwoot inbox.)
- **Data residency**: production runs on a VPS in Mumbai; backups should go to storage in India.
- Publish a privacy policy and terms before going live and put the link in Setup → Clinic.

## Medical safety

- WAM never gives medical advice. The AI's instructions forbid diagnoses, medicines and opinions on symptoms;
  medical questions are handed to staff.
- **Emergency words** (English, Hindi and Hinglish, plus any the clinic adds) are checked before anything
  else, even the AI: WAM replies with 112/108 and the clinic's emergency number, opens the chat in the inbox
  with urgent priority and an `emergency` label, and alerts the front desk on WhatsApp.
- Vaccination schedules are reminders only, based on ages the clinic configures.

## Staff and admin security

- Staff are identified by their WhatsApp number. Cancelling visits and taking leave need `YES <PIN>`; PINs
  are bcrypt-hashed, expire the request after 10 minutes, and lock after 5 wrong tries for 15 minutes.
- Every staff and admin action is written to the audit log with the phone number or admin user.
- Admin sign-in uses bcrypt passwords and short-lived signed sessions stored in an httpOnly cookie; failed
  logins are rate-limited per email and per IP. Clinic admins only see their own clinic.
- The Chatwoot webhook URL contains a secret, and when the agent bot's webhook secret is saved in WAM the
  `X-Chatwoot-Signature` HMAC and timestamp are verified too.
- WAM refuses to start in production with default secrets.
