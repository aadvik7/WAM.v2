"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useBusiness } from "@/lib/business";
import type { Business } from "@/lib/types";
import { Card, ErrorBox, Field, useAction } from "@/components/ui";

const DAYS: [string, string][] = [
  ["mon", "Monday"], ["tue", "Tuesday"], ["wed", "Wednesday"], ["thu", "Thursday"], ["fri", "Friday"], ["sat", "Saturday"], ["sun", "Sunday"],
];

type Hours = Record<string, [string, string][]>;

function hoursToText(hours: Hours, day: string): string {
  return (hours[day] || []).map(([a, b]) => `${a}-${b}`).join(", ");
}

function textToBlocks(text: string): [string, string][] | null {
  const trimmed = text.trim();
  if (!trimmed) return [];
  const blocks: [string, string][] = [];
  for (const part of trimmed.split(",")) {
    const m = part.trim().match(/^(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})$/);
    if (!m) return null;
    const pad = (t: string) => t.padStart(5, "0");
    blocks.push([pad(m[1]), pad(m[2])]);
  }
  return blocks;
}

const SETTING_FIELDS: { key: string; label: string; type: "number" | "time" | "text" | "bool"; hint?: string }[] = [
  { key: "min_notice_minutes", label: "Minimum notice (minutes)", type: "number", hint: "Earliest bookable slot is now + this." },
  { key: "booking_horizon_days", label: "Booking horizon (days)", type: "number" },
  { key: "offer_slot_count", label: "Slots offered per message", type: "number" },
  { key: "reschedule_cutoff_minutes", label: "Self-reschedule cut-off (minutes)", type: "number" },
  { key: "send_window_start", label: "Send messages from", type: "time", hint: "Reminders and follow-ups only go out in this window." },
  { key: "send_window_end", label: "Send messages until", type: "time" },
  { key: "reminder_time", label: "Day-before reminders at", type: "time" },
  { key: "eod_time", label: "End-of-day check at", type: "time", hint: "Front desk gets today's list to mark who didn't come." },
  { key: "followup_after_hours", label: "First missed-visit follow-up after (hours)", type: "number" },
  { key: "second_followup_after_hours", label: "Second follow-up after (hours)", type: "number" },
  { key: "renudge_after_days", label: "Re-send due reminder after (days)", type: "number" },
  { key: "max_nudges", label: "Due reminders before flagging staff", type: "number" },
  { key: "late_notify_window_hours", label: "'Running late' tells patients within (hours)", type: "number" },
  { key: "retention_days", label: "Delete message logs after (days)", type: "number", hint: "DPDP data-retention rule." },
  { key: "privacy_url", label: "Privacy policy URL", type: "text" },
  { key: "assistant_name", label: "Assistant name", type: "text" },
  { key: "template_language", label: "Template language code", type: "text", hint: "Exactly as approved in Meta, e.g. en, en_US, hi." },
  { key: "ai_enabled", label: "Use AI for patient chats", type: "bool", hint: "Off = rules only (FAQ, timings, booking by number, handoff)." },
];

export function ClinicTab() {
  const { business, reload } = useBusiness();
  const [form, setForm] = useState<Partial<Business>>({});
  const [hoursText, setHoursText] = useState<Record<string, string>>({});
  const [settings, setSettings] = useState<Record<string, unknown>>({});
  const [consent, setConsent] = useState("");
  const [emergencyWords, setEmergencyWords] = useState("");
  const { busy, error, run, setError } = useAction();

  useEffect(() => {
    if (!business) return;
    setForm({ name: business.name, phone: business.phone, address: business.address, maps_url: business.maps_url, emergency_number: business.emergency_number, timezone: business.timezone });
    setHoursText(Object.fromEntries(DAYS.map(([d]) => [d, hoursToText(business.hours, d)])));
    setSettings({ ...business.settings });
    setConsent(String(business.settings.consent_text ?? ""));
    setEmergencyWords(((business.settings.extra_emergency_words as string[]) || []).join(", "));
  }, [business]);

  if (!business) return null;

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const hours: Hours = {};
    for (const [d, label] of DAYS) {
      const blocks = textToBlocks(hoursText[d] || "");
      if (blocks === null) {
        setError(new Error(`${label}: use times like 10:00-13:00, 17:00-20:00`));
        return;
      }
      if (blocks.length) hours[d] = blocks;
    }
    const cleanSettings: Record<string, unknown> = {};
    for (const f of SETTING_FIELDS) {
      const v = settings[f.key];
      cleanSettings[f.key] = f.type === "number" ? Number(v) : v;
    }
    cleanSettings.consent_text = consent;
    cleanSettings.extra_emergency_words = emergencyWords.split(",").map((w) => w.trim().toLowerCase()).filter(Boolean);
    const ok = await run(
      () => api(`/api/businesses/${business!.id}`, { method: "PATCH", body: { ...form, hours, settings: cleanSettings } }),
      "Clinic settings saved",
    );
    if (ok) await reload();
  }

  return (
    <form onSubmit={save} className="stack">
      <ErrorBox error={error} />
      <Card title="Clinic details" actions={<span className="badge accent">{business.type} pack</span>}>
        <div className="form-grid">
          <Field label="Name"><input value={form.name || ""} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></Field>
          <Field label="Phone (shown to patients)"><input value={form.phone || ""} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></Field>
          <Field label="Emergency number" hint="Sent instantly when a patient uses emergency words."><input value={form.emergency_number || ""} onChange={(e) => setForm({ ...form, emergency_number: e.target.value })} /></Field>
          <Field label="Timezone"><input value={form.timezone || ""} onChange={(e) => setForm({ ...form, timezone: e.target.value })} /></Field>
        </div>
        <div className="form-grid" style={{ marginTop: 12 }}>
          <Field label="Address"><textarea value={form.address || ""} onChange={(e) => setForm({ ...form, address: e.target.value })} /></Field>
          <Field label="Google Maps link"><input value={form.maps_url || ""} onChange={(e) => setForm({ ...form, maps_url: e.target.value })} /></Field>
        </div>
      </Card>
      <Card title="Opening hours (shown to patients)">
        <p className="small muted">Doctors&apos; bookable hours are set per doctor under &quot;Doctors &amp; hours&quot;. Leave a day empty if closed.</p>
        <div className="form-grid">
          {DAYS.map(([d, label]) => (
            <Field key={d} label={label}>
              <input placeholder="Closed" value={hoursText[d] || ""} onChange={(e) => setHoursText({ ...hoursText, [d]: e.target.value })} />
            </Field>
          ))}
        </div>
      </Card>
      <Card title="Reminders, follow-ups and privacy">
        <div className="form-grid">
          {SETTING_FIELDS.map((f) => (
            <Field key={f.key} label={f.label} hint={f.hint}>
              {f.type === "bool" ? (
                <select value={settings[f.key] ? "yes" : "no"} onChange={(e) => setSettings({ ...settings, [f.key]: e.target.value === "yes" })}>
                  <option value="yes">Yes</option>
                  <option value="no">No</option>
                </select>
              ) : (
                <input
                  type={f.type === "number" ? "number" : f.type === "time" ? "time" : "text"}
                  value={String(settings[f.key] ?? "")}
                  onChange={(e) => setSettings({ ...settings, [f.key]: e.target.value })}
                />
              )}
            </Field>
          ))}
        </div>
        <div className="stack" style={{ marginTop: 12, gap: 12 }}>
          <Field label="Consent message (first chat)" hint="{business} and {privacy_url} are filled in automatically.">
            <textarea value={consent} onChange={(e) => setConsent(e.target.value)} rows={4} />
          </Field>
          <Field label="Extra emergency words (comma separated)" hint="Added to WAM's built-in English/Hindi list.">
            <input value={emergencyWords} onChange={(e) => setEmergencyWords(e.target.value)} />
          </Field>
        </div>
      </Card>
      <div className="form-actions">
        <button className="btn primary" disabled={busy}>{busy ? "Saving…" : "Save clinic settings"}</button>
      </div>
    </form>
  );
}
