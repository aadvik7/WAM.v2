"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { bpath, useBusiness } from "@/lib/business";
import { fmtDate } from "@/lib/format";
import type { Batch, BroadcastSummary, PtmEvent, Resource } from "@/lib/types";
import { Card, Confirm, Empty, ErrorBox, Field, StatusBadge, useAction, useLoad } from "@/components/ui";

function fmt12(hhmm: string): string {
  const [h, m] = hhmm.split(":").map(Number);
  return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
}

function todayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function PtmPage() {
  const { business } = useBusiness();
  const events = useLoad(() => api<PtmEvent[]>(bpath(business, "/institute/ptm")), [business?.id]);
  const batches = useLoad(() => api<Batch[]>(bpath(business, "/institute/batches")), [business?.id]);
  const resources = useLoad(() => api<Resource[]>(bpath(business, "/resources")), [business?.id]);
  const invites = useLoad(() => api<BroadcastSummary[]>(bpath(business, "/institute/broadcasts")), [business?.id]);
  const [form, setForm] = useState({ group_id: "", title: "Parent-teacher meeting", date: "", start: "10:00", end: "13:00", slot_minutes: 10, invite: true });
  const [teachers, setTeachers] = useState<number[]>([]);
  const [inviting, setInviting] = useState<BroadcastSummary | null>(null);
  const [removing, setRemoving] = useState<PtmEvent | null>(null);
  const act = useAction();

  const activeResources = (resources.data || []).filter((r) => r.is_active);
  const resourceName = (id: number) => resources.data?.find((r) => r.id === id)?.name || `#${id}`;
  const inviteFor = (e: PtmEvent) => invites.data?.find((b) => b.id === e.broadcast_id) || null;
  const slotsPerTeacher = (() => {
    if (!form.start || !form.end) return 0;
    const [sh, sm] = form.start.split(":").map(Number);
    const [eh, em] = form.end.split(":").map(Number);
    return Math.max(0, Math.floor((eh * 60 + em - (sh * 60 + sm)) / (form.slot_minutes || 10)));
  })();

  function reloadAll() {
    void events.reload();
    void invites.reload();
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    const res = await act.run(
      () =>
        api<{ id: number; invite: BroadcastSummary | null }>(bpath(business, "/institute/ptm"), {
          method: "POST",
          body: { ...form, group_id: Number(form.group_id), resource_ids: teachers },
        }),
      "Meeting created",
    );
    if (res) {
      reloadAll();
      if (res.invite) setInviting(res.invite);
    }
  }

  async function sendInvite(b: BroadcastSummary) {
    await act.run(() => api(bpath(business, `/institute/broadcasts/${b.id}/send`), { method: "POST" }), `Inviting ${b.recipients} parents`);
    setInviting(null);
    reloadAll();
  }

  async function remove(ev: PtmEvent) {
    const ok = await act.run(async () => {
      await api(bpath(business, `/institute/ptm/${ev.id}`), { method: "DELETE" });
      return true;
    }, "Meeting removed");
    setRemoving(null);
    if (ok) reloadAll();
  }

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Parent-teacher meetings</h1>
          <div className="muted">Parents reply PTM on WhatsApp and pick a short slot with the teachers. Bookings show on the Appointments page.</div>
        </div>
      </div>
      <ErrorBox error={act.error} />

      <div className="grid grid-2">
        <Card title="New meeting">
          <form onSubmit={create} className="stack" style={{ gap: 10 }}>
            <Field label="Batch">
              <select value={form.group_id} onChange={(e) => setForm({ ...form, group_id: e.target.value })} required>
                <option value="">Choose a batch</option>
                {(batches.data || []).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
            </Field>
            <Field label="Title">
              <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} maxLength={120} required />
            </Field>
            <div className="form-grid">
              <Field label="Date">
                <input type="date" min={todayIso()} value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} required />
              </Field>
              <Field label="Slot length (minutes)">
                <input type="number" min={5} max={60} value={form.slot_minutes} onChange={(e) => setForm({ ...form, slot_minutes: Number(e.target.value) })} required />
              </Field>
              <Field label="From">
                <input type="time" value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} required />
              </Field>
              <Field label="To">
                <input type="time" value={form.end} onChange={(e) => setForm({ ...form, end: e.target.value })} required />
              </Field>
            </div>
            <Field label="Teachers" hint={teachers.length ? `${slotsPerTeacher} slots per teacher, ${slotsPerTeacher * teachers.length} in all` : "Parents book a slot with one of them"}>
              <div className="stack" style={{ gap: 4 }}>
                {activeResources.length === 0 && (
                  <span className="small muted">No teachers yet. Add them under <Link href="/setup">Setup</Link>.</span>
                )}
                {activeResources.map((r) => (
                  <label key={r.id} className="check">
                    <input
                      type="checkbox"
                      checked={teachers.includes(r.id)}
                      onChange={(e) => setTeachers(e.target.checked ? [...teachers, r.id] : teachers.filter((t) => t !== r.id))}
                    />
                    {r.name}{r.specialty ? <span className="muted small"> · {r.specialty}</span> : null}
                  </label>
                ))}
              </div>
            </Field>
            <label className="check">
              <input type="checkbox" checked={form.invite} onChange={(e) => setForm({ ...form, invite: e.target.checked })} />
              Invite the batch&apos;s parents (you&apos;ll see the message before it&apos;s sent)
            </label>
            <div className="form-actions">
              <button className="btn primary" disabled={act.busy || !teachers.length || !form.group_id || !form.date}>Create meeting</button>
            </div>
          </form>
        </Card>

        <Card title="How parents book">
          <div className="chat">
            <div className="bubble out small">Update for NEET-A2: Parent-teacher meeting on Sat 10 Oct, 10:00 AM–1:00 PM. Reply PTM to book a 10-minute slot with the teachers. Reply here if you have questions.</div>
            <div className="bubble in small">PTM</div>
            <div className="bubble out small">Parent-teacher meeting on Sat 10 Oct, 10:00 AM–1:00 PM. Free slots:<br />1) 10:00 AM with Mr. Rao<br />2) 10:10 AM with Mr. Rao<br />3) 10:20 AM with Mr. Rao<br /><br />Reply 1, 2 or 3 to book.</div>
            <div className="bubble in small">2</div>
          </div>
          <p className="small muted">Parents get the usual day-before reminder. The slots use extra hours for the teachers, so their normal timings don&apos;t need to change.</p>
        </Card>
      </div>

      <Card title="Meetings" actions={<button className="btn small" onClick={reloadAll}>Refresh</button>}>
        <ErrorBox error={events.error} />
        {!events.data ? <Empty>Loading…</Empty> : events.data.length === 0 ? <Empty>No meetings yet.</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Date</th><th>Batch</th><th>Time</th><th>Teachers</th><th>Booked</th><th>Free</th><th>Invite</th><th /></tr></thead>
              <tbody>
                {events.data.map((ev) => {
                  const inv = inviteFor(ev);
                  return (
                    <tr key={ev.id}>
                      <td className="nowrap">{fmtDate(ev.date)}<div className="small muted">{ev.title}</div></td>
                      <td>{ev.batch || "—"}</td>
                      <td className="nowrap">{fmt12(ev.start)}–{fmt12(ev.end)}<div className="small muted">{ev.slot_minutes}-min slots</div></td>
                      <td className="small">{ev.resource_ids.map(resourceName).join(", ")}</td>
                      <td>{ev.booked}</td>
                      <td>{ev.free}</td>
                      <td>
                        {inv ? (
                          <>
                            <StatusBadge status={inv.status} />
                            {inv.status !== "draft" && inv.status !== "cancelled" && <div className="small muted">{inv.read} of {inv.recipients} read</div>}
                          </>
                        ) : "—"}
                      </td>
                      <td className="actions">
                        {inv?.status === "draft" && <button className="btn small primary" onClick={() => setInviting(inv)}>Send invite</button>}{" "}
                        <button className="btn small danger" onClick={() => setRemoving(ev)}>Remove</button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {inviting && (
        <Confirm title={`Invite ${inviting.recipients} parents?`} confirmLabel="Yes, send invite" busy={act.busy} onConfirm={() => void sendInvite(inviting)} onClose={() => { setInviting(null); reloadAll(); }}>
          <p>Each parent in {inviting.batch} gets this message:</p>
          <div className="bubble out" style={{ maxWidth: "100%", whiteSpace: "pre-wrap" }}>{inviting.preview}</div>
          <p className="small muted">You can also send it later from this page.</p>
        </Confirm>
      )}
      {removing && (
        <Confirm title="Remove this meeting?" confirmLabel="Remove meeting" danger busy={act.busy} onConfirm={() => void remove(removing)} onClose={() => setRemoving(null)}>
          <p>
            Parents can no longer book it.
            {removing.booked > 0 && <> The {removing.booked} slots already booked stay on the <Link href="/appointments">Appointments</Link> page; cancel them there so parents are told.</>}
          </p>
        </Confirm>
      )}
    </div>
  );
}
