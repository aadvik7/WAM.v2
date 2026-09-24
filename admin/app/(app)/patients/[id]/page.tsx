"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { bpath, useBusiness } from "@/lib/business";
import { fmtDate, fmtDateTime, fmtTime, planProgress } from "@/lib/format";
import type { Appointment, Contact, Message, Resource, Schedule, Template } from "@/lib/types";
import { AppointmentActions, BookModal } from "@/components/Booking";
import { Card, Empty, ErrorBox, Field, Modal, StatusBadge, useAction, useLoad } from "@/components/ui";

interface Detail {
  contact: Contact;
  children: Contact[];
  schedules: Schedule[];
  appointments: Appointment[];
  messages: Message[];
}

export default function PatientPage() {
  const { id } = useParams<{ id: string }>();
  const { business } = useBusiness();
  const router = useRouter();
  const { data, error, reload } = useLoad(() => api<Detail>(bpath(business, `/contacts/${id}`)), [business?.id, id]);
  const [enrolling, setEnrolling] = useState(false);
  const [booking, setBooking] = useState<Schedule | null | false>(false);
  const [editing, setEditing] = useState(false);
  const [erasing, setErasing] = useState(false);
  const action = useAction();

  if (error) return <ErrorBox error={error} />;
  if (!data) return <Empty>Loading…</Empty>;
  const c = data.contact;
  const upcoming = data.appointments.filter((a) => a.status === "booked" || a.status === "confirmed").reverse();
  const past = data.appointments.filter((a) => !(a.status === "booked" || a.status === "confirmed"));

  async function patchSchedule(s: Schedule, body: Record<string, unknown>, msg: string) {
    const ok = await action.run(() => api(bpath(business, `/schedules/${s.id}`), { method: "PATCH", body }), msg);
    if (ok) void reload();
  }

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <div className="small"><Link href="/patients">← Patients</Link></div>
          <h1>{c.name || "Unknown patient"}</h1>
          <div className="muted">
            {c.phone || (c.guardian ? `via ${c.guardian.name || "guardian"} ${c.guardian.phone}` : "no number")}
            {c.date_of_birth && ` · born ${fmtDate(c.date_of_birth)}`}
          </div>
          <div className="row" style={{ marginTop: 6 }}>
            {c.needs_staff && <span className="badge warn">needs a person</span>}
            {c.opted_out && <span className="badge">opted out of messages</span>}
            {c.consent_at ? <span className="badge ok">consent {fmtDate(c.consent_at)}</span> : c.consent_notice_sent_at ? <span className="badge info">privacy notice sent</span> : null}
          </div>
        </div>
        <div className="row">
          <button className="btn" onClick={() => setEditing(true)}>Edit</button>
          <button className="btn" onClick={() => setEnrolling(true)}>Start a plan</button>
          <button className="btn primary" onClick={() => setBooking(null)}>Book visit</button>
        </div>
      </div>
      <ErrorBox error={action.error} />
      {c.notes && <div className="alert info">{c.notes}</div>}

      <Card title="Treatment plans">
        {data.schedules.length === 0 ? (
          <Empty>No plans yet. Start one so WAM reminds {c.name || "the patient"} when each visit is due.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Plan</th><th>Progress</th><th>Next due</th><th>Status</th><th /></tr></thead>
              <tbody>
                {data.schedules.map((s) => (
                  <tr key={s.id}>
                    <td>{s.template}{s.notes && <div className="small muted">{s.notes}</div>}</td>
                    <td>{planProgress(s.sessions_done, s.sessions_total)}{s.missed_count > 0 && <div className="small muted">{s.missed_count} missed in a row</div>}</td>
                    <td className="nowrap">
                      {s.next_due_date ? fmtDate(s.next_due_date) : "—"} {s.overdue && <span className="badge danger">overdue</span>}
                      {s.nudge_count > 0 && <div className="small muted">{s.nudge_count} reminder(s) sent</div>}
                    </td>
                    <td><StatusBadge status={s.status} /> {s.needs_staff && <span className="badge warn">call</span>}</td>
                    <td className="actions">
                      {s.status === "active" && (
                        <>
                          <button className="btn small" onClick={() => setBooking(s)}>Book</button>{" "}
                          <button className="btn small" disabled={action.busy} onClick={() => void action.run(() => api(bpath(business, `/schedules/${s.id}/nudge`), { method: "POST" }), "Slots sent on WhatsApp").then(() => reload())}>Send slots</button>{" "}
                          <DueEditor schedule={s} onSave={(d) => void patchSchedule(s, { next_due_date: d }, "Next due date updated")} />{" "}
                          <button className="btn small" onClick={() => void patchSchedule(s, { status: "paused" }, "Plan paused")}>Pause</button>{" "}
                          <button className="btn small danger" onClick={() => void patchSchedule(s, { status: "cancelled" }, "Plan stopped")}>Stop</button>
                        </>
                      )}
                      {s.status === "paused" && <button className="btn small" onClick={() => void patchSchedule(s, { status: "active" }, "Plan resumed")}>Resume</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="grid grid-2">
        <Card title="Upcoming visits">
          {upcoming.length === 0 ? <Empty>Nothing booked.</Empty> : (
            <table>
              <tbody>
                {upcoming.map((a) => (
                  <tr key={a.id}>
                    <td className="nowrap">{fmtDateTime(a.start_at)}</td>
                    <td>{a.service || "Visit"}<div className="small muted">{a.resource_name}</div></td>
                    <td><StatusBadge status={a.status} /></td>
                    <td className="actions"><AppointmentActions appt={a} onChange={() => void reload()} now={new Date(0).toISOString()} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card title="Past visits">
          {past.length === 0 ? <Empty>No past visits.</Empty> : (
            <table>
              <tbody>
                {past.slice(0, 20).map((a) => (
                  <tr key={a.id}>
                    <td className="nowrap">{fmtDate(a.start_at)} {fmtTime(a.start_at)}</td>
                    <td>{a.service || "Visit"}{a.cancelled_reason && <div className="small muted">{a.cancelled_reason}</div>}</td>
                    <td><StatusBadge status={a.status} /> {a.recovered && <span className="badge accent">recovered</span>}</td>
                    <td className="actions">{(a.status === "done" || a.status === "missed") && <AppointmentActions appt={a} onChange={() => void reload()} />}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      {data.children.length > 0 && (
        <Card title="Children reached through this number">
          <div className="row">{data.children.map((k) => <Link key={k.id} href={`/patients/${k.id}`} className="badge accent">{k.name}</Link>)}</div>
        </Card>
      )}

      <Card title="WhatsApp messages">
        {data.messages.length === 0 ? <Empty>No messages yet.</Empty> : (
          <div className="chat">
            {data.messages.map((m) => (
              <div key={m.id} className={`bubble ${m.direction}`}>
                {m.content}
                <div className="meta">
                  {fmtDateTime(m.created_at)}
                  {m.template_name && ` · template ${m.template_name}`}
                  {m.direction === "in" && m.handled_by && ` · answered by ${m.handled_by}`}
                  {m.status !== "ok" && m.status !== "processed" && ` · ${m.status}`}
                  {m.error && ` (${m.error})`}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title="Data">
        <p className="muted small">Erase this patient and all their messages, plans and visits (DPDP right to erasure). This can&apos;t be undone.</p>
        <button className="btn danger" onClick={() => setErasing(true)}>Erase patient data</button>
      </Card>

      {enrolling && <EnrolModal contact={c} onClose={() => setEnrolling(false)} onDone={() => { setEnrolling(false); void reload(); }} />}
      {booking !== false && (
        <BookModal contact={c} schedule={booking ?? undefined} onClose={() => setBooking(false)} onDone={() => { setBooking(false); void reload(); }} />
      )}
      {editing && <EditContact contact={c} onClose={() => setEditing(false)} onDone={() => { setEditing(false); void reload(); }} />}
      {erasing && (
        <Modal title="Erase this patient?" onClose={() => setErasing(false)}>
          <p>All of {c.name || "this patient"}&apos;s data will be deleted permanently.</p>
          <div className="form-actions">
            <button className="btn" onClick={() => setErasing(false)}>Keep</button>
            <button className="btn danger" disabled={action.busy} onClick={() => void action.run(async () => { await api(bpath(business, `/contacts/${c.id}`), { method: "DELETE" }); return true; }, "Patient erased").then((r) => r && router.push("/patients"))}>Erase</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function DueEditor({ schedule, onSave }: { schedule: Schedule; onSave: (date: string) => void }) {
  const [open, setOpen] = useState(false);
  const [date, setDate] = useState(schedule.next_due_date || "");
  if (!open) return <button className="btn small" onClick={() => setOpen(true)}>Change due</button>;
  return (
    <span className="row" style={{ display: "inline-flex" }}>
      <input type="date" value={date} onChange={(e) => setDate(e.target.value)} style={{ width: 150 }} />
      <button className="btn small primary" disabled={!date} onClick={() => { onSave(date); setOpen(false); }}>Save</button>
      <button className="btn small" onClick={() => setOpen(false)}>×</button>
    </span>
  );
}

function EnrolModal({ contact, onClose, onDone }: { contact: Contact; onClose: () => void; onDone: () => void }) {
  const { business } = useBusiness();
  const templates = useLoad(() => api<Template[]>(bpath(business, "/templates")), [business?.id]);
  const resources = useLoad(() => api<Resource[]>(bpath(business, "/resources")), [business?.id]);
  const [templateId, setTemplateId] = useState<number | "">("");
  const [resourceId, setResourceId] = useState<number | "">("");
  const [done, setDone] = useState(0);
  const [anchor, setAnchor] = useState(contact.date_of_birth || "");
  const [firstDue, setFirstDue] = useState("");
  const [nudge, setNudge] = useState(true);
  const { busy, error, run } = useAction();
  const tpl = templates.data?.find((t) => t.id === templateId);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const ok = await run(
      () =>
        api(bpath(business, `/contacts/${contact.id}/schedules`), {
          method: "POST",
          body: {
            template_id: templateId,
            resource_id: resourceId || null,
            sessions_done: done,
            anchor_date: anchor || null,
            first_due: firstDue || null,
            nudge_now: nudge,
          },
        }),
      "Plan started",
    );
    if (ok) onDone();
  }

  return (
    <Modal title={`Start a plan for ${contact.name || "patient"}`} onClose={onClose}>
      <form onSubmit={save}>
        <ErrorBox error={error} />
        <div className="stack" style={{ gap: 12 }}>
          <Field label="Plan">
            <select value={templateId} onChange={(e) => setTemplateId(Number(e.target.value))} required>
              <option value="">Choose…</option>
              {templates.data?.filter((t) => t.is_active).map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} — {t.offsets_days ? "age-based schedule" : t.session_count ? `${t.session_count} visits, ${t.gap_days} days apart` : `every ${t.gap_days} days`}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Doctor (optional)">
            <select value={resourceId} onChange={(e) => setResourceId(e.target.value ? Number(e.target.value) : "")}>
              <option value="">Any matching doctor</option>
              {resources.data?.filter((r) => r.is_active).map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
            </select>
          </Field>
          {tpl?.offsets_days ? (
            <Field label="Date of birth" hint="Visits are due at fixed ages from this date. Doses long past are skipped automatically by staff commands; set 'visits already done' here.">
              <input type="date" value={anchor} onChange={(e) => setAnchor(e.target.value)} required />
            </Field>
          ) : null}
          <div className="form-grid">
            <Field label="Visits already done"><input type="number" min={0} value={done} onChange={(e) => setDone(Number(e.target.value))} /></Field>
            <Field label="Next visit due (optional)" hint="Default: today, or gap after today if visits are done."><input type="date" value={firstDue} onChange={(e) => setFirstDue(e.target.value)} /></Field>
          </div>
          <label className="check"><input type="checkbox" checked={nudge} onChange={(e) => setNudge(e.target.checked)} /> If due now, send free slots on WhatsApp right away</label>
        </div>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={busy || !templateId}>{busy ? "Saving…" : "Start plan"}</button>
        </div>
      </form>
    </Modal>
  );
}

function EditContact({ contact, onClose, onDone }: { contact: Contact; onClose: () => void; onDone: () => void }) {
  const { business } = useBusiness();
  const [form, setForm] = useState({
    name: contact.name || "",
    phone: contact.phone || "",
    date_of_birth: contact.date_of_birth || "",
    notes: contact.notes || "",
    opted_out: contact.opted_out,
    needs_staff: contact.needs_staff,
  });
  const { busy, error, run } = useAction();
  async function save(e: React.FormEvent) {
    e.preventDefault();
    const body: Record<string, unknown> = {
      name: form.name || null,
      date_of_birth: form.date_of_birth || null,
      notes: form.notes || null,
      opted_out: form.opted_out,
      needs_staff: form.needs_staff,
    };
    if (contact.phone || form.phone) body.phone = form.phone || null;
    const ok = await run(() => api(bpath(business, `/contacts/${contact.id}`), { method: "PATCH", body }), "Saved");
    if (ok) onDone();
  }
  return (
    <Modal title="Edit patient" onClose={onClose}>
      <form onSubmit={save}>
        <ErrorBox error={error} />
        <div className="stack" style={{ gap: 12 }}>
          <Field label="Name"><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          {!contact.guardian && <Field label="WhatsApp number"><input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></Field>}
          <Field label="Date of birth"><input type="date" value={form.date_of_birth} onChange={(e) => setForm({ ...form, date_of_birth: e.target.value })} /></Field>
          <Field label="Notes"><textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></Field>
          <label className="check"><input type="checkbox" checked={form.needs_staff} onChange={(e) => setForm({ ...form, needs_staff: e.target.checked })} /> Needs a person (flagged for staff)</label>
          <label className="check"><input type="checkbox" checked={form.opted_out} onChange={(e) => setForm({ ...form, opted_out: e.target.checked })} /> Opted out of reminders</label>
        </div>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={busy}>Save</button>
        </div>
      </form>
    </Modal>
  );
}
