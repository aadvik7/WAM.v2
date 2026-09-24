"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { bpath, useBusiness } from "@/lib/business";
import { useVocab } from "@/lib/vocab";
import { WEEKDAYS, fmtDate } from "@/lib/format";
import type { AvailabilityBlock, Resource, StaffMember } from "@/lib/types";
import { Card, Empty, ErrorBox, Field, Modal, toast, useAction, useLoad } from "@/components/ui";

interface AvailabilityOut {
  weekly: AvailabilityBlock[];
  breaks: AvailabilityBlock[];
  leave: AvailabilityBlock[];
}

export function DoctorsTab() {
  const { business } = useBusiness();
  const v = useVocab();
  const resources = useLoad(() => api<Resource[]>(bpath(business, "/resources")), [business?.id]);
  const staff = useLoad(() => api<StaffMember[]>(bpath(business, "/staff")), [business?.id]);
  const [editing, setEditing] = useState<Resource | "new" | null>(null);
  const [selected, setSelected] = useState<number | null>(null);

  useEffect(() => {
    if (selected === null && resources.data?.length) setSelected(resources.data[0].id);
  }, [resources.data, selected]);

  const current = resources.data?.find((r) => r.id === selected) ?? null;

  return (
    <div className="stack">
      <Card title={v.Resources} actions={<button className="btn primary small" onClick={() => setEditing("new")}>Add {v.resource}</button>}>
        <ErrorBox error={resources.error} />
        {!resources.data ? <Empty>Loading…</Empty> : resources.data.length === 0 ? <Empty>Add your first {v.resource} to start taking bookings.</Empty> : (
          <table>
            <thead><tr><th>Name</th><th>{business?.type === "institute" ? "Subject" : "Specialty"}</th><th>Slot length</th><th>WhatsApp staff</th><th>Status</th><th /></tr></thead>
            <tbody>
              {resources.data.map((r) => (
                <tr key={r.id} style={selected === r.id ? { background: "var(--accent-soft)" } : undefined}>
                  <td><button className="btn link" onClick={() => setSelected(r.id)}>{r.name}</button></td>
                  <td>{r.specialty || "—"}</td>
                  <td>{r.slot_minutes} min</td>
                  <td>{staff.data?.find((s) => s.id === r.staff_id)?.name || <span className="muted">—</span>}</td>
                  <td>{r.is_active ? <span className="badge ok">bookable</span> : <span className="badge">inactive</span>}</td>
                  <td className="actions"><button className="btn small" onClick={() => setEditing(r)}>Edit</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="small muted" style={{ marginTop: 10 }}>
          {business?.type === "clinic"
            ? "Plans are offered with doctors whose specialty matches the plan (e.g. a Dental plan only offers Dental doctors)."
            : `Link each ${v.resource} to their staff WhatsApp number so their own commands work.`}
        </p>
      </Card>
      {current && <AvailabilityEditor key={current.id} resource={current} />}
      {editing && (
        <ResourceForm
          resource={editing === "new" ? null : editing}
          staff={staff.data || []}
          onClose={() => setEditing(null)}
          onDone={(r) => {
            setEditing(null);
            setSelected(r.id);
            void resources.reload();
          }}
        />
      )}
    </div>
  );
}

function ResourceForm({ resource, staff, onClose, onDone }: { resource: Resource | null; staff: StaffMember[]; onClose: () => void; onDone: (r: Resource) => void }) {
  const { business } = useBusiness();
  const v = useVocab();
  const institute = business?.type === "institute";
  const [form, setForm] = useState({
    name: resource?.name || "",
    specialty: resource?.specialty || "",
    slot_minutes: resource?.slot_minutes || 15,
    staff_id: resource?.staff_id ?? "",
    is_active: resource?.is_active ?? true,
    kind: resource?.kind || v.resource.split(" ")[0],
  });
  const { busy, error, run } = useAction();
  async function save(e: React.FormEvent) {
    e.preventDefault();
    const body = { ...form, specialty: form.specialty || null, staff_id: form.staff_id === "" ? null : Number(form.staff_id), slot_minutes: Number(form.slot_minutes) };
    const r = await run(
      () => api<Resource>(bpath(business, resource ? `/resources/${resource.id}` : "/resources"), { method: resource ? "PATCH" : "POST", body }),
      `${v.Resource} saved`,
    );
    if (r) onDone(r);
  }
  return (
    <Modal title={resource ? `Edit ${resource.name}` : `Add ${v.resource}`} onClose={onClose}>
      <form onSubmit={save}>
        <ErrorBox error={error} />
        <div className="form-grid">
          <Field label="Name"><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required placeholder={institute ? "Mr. Rao" : business?.type === "clinic" ? "Dr. Mehta" : "Asha"} /></Field>
          <Field label={institute ? "Subject" : "Specialty"} hint={institute ? "Physics, Chemistry, Maths…" : business?.type === "clinic" ? "Dental, Skin, Physiotherapy, Paediatrics, Physician…" : "Hair, Nails, Trainer…"}><input value={form.specialty} onChange={(e) => setForm({ ...form, specialty: e.target.value })} /></Field>
          <Field label="Slot length (minutes)"><input type="number" min={5} max={480} value={form.slot_minutes} onChange={(e) => setForm({ ...form, slot_minutes: Number(e.target.value) })} /></Field>
          <Field label="Linked staff (their WhatsApp)" hint={`'Cancel my 5 pm' uses this ${v.resource}.`}>
            <select value={form.staff_id} onChange={(e) => setForm({ ...form, staff_id: e.target.value === "" ? "" : Number(e.target.value) })}>
              <option value="">None</option>
              {staff.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </Field>
        </div>
        <label className="check" style={{ marginTop: 12 }}><input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} /> Bookable</label>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={busy}>Save</button>
        </div>
      </form>
    </Modal>
  );
}

interface Row { weekday: number | null; start: string; end: string }

function AvailabilityEditor({ resource }: { resource: Resource }) {
  const { business } = useBusiness();
  const v = useVocab();
  const avail = useLoad(() => api<AvailabilityOut>(bpath(business, `/resources/${resource.id}/availability`)), [business?.id, resource.id]);
  const [weekly, setWeekly] = useState<Row[]>([]);
  const [breaks, setBreaks] = useState<Row[]>([]);
  const [leave, setLeave] = useState({ start_date: "", end_date: "", reason: "", move_appointments: true });
  const save = useAction();
  const leaveAction = useAction();

  useEffect(() => {
    if (!avail.data) return;
    setWeekly(avail.data.weekly.map((b) => ({ weekday: b.weekday, start: b.start || "", end: b.end || "" })));
    setBreaks(avail.data.breaks.map((b) => ({ weekday: b.weekday, start: b.start || "", end: b.end || "" })));
  }, [avail.data]);

  async function saveHours() {
    const ok = await save.run(
      () =>
        api(bpath(business, `/resources/${resource.id}/availability`), {
          method: "PUT",
          body: {
            weekly: weekly.map((w) => ({ weekday: w.weekday ?? 0, start: w.start, end: w.end })),
            breaks: breaks.map((b) => ({ weekday: b.weekday, start: b.start, end: b.end })),
          },
        }),
      "Working hours saved",
    );
    if (ok) void avail.reload();
  }

  function copyMondayToWeekdays() {
    const monday = weekly.filter((w) => w.weekday === 0);
    const others = weekly.filter((w) => w.weekday !== null && w.weekday > 5);
    const copied: Row[] = [];
    for (let d = 0; d <= 5; d++) for (const m of monday) copied.push({ ...m, weekday: d });
    setWeekly([...copied, ...others]);
  }

  async function addLeave(e: React.FormEvent) {
    e.preventDefault();
    const r = await leaveAction.run(
      () => api<{ cancelled: number; offered_new_slots: number }>(bpath(business, `/resources/${resource.id}/leave`), { method: "POST", body: { ...leave, end_date: leave.end_date || leave.start_date, reason: leave.reason || null } }),
    );
    if (r) {
      toast(`Leave added. ${r.cancelled} appointment(s) cancelled, ${r.offered_new_slots} ${v.person}(s) offered new slots.`);
      setLeave({ start_date: "", end_date: "", reason: "", move_appointments: true });
      void avail.reload();
    }
  }

  async function removeLeave(id: number) {
    await leaveAction.run(async () => {
      await api(bpath(business, `/leave/${id}`), { method: "DELETE" });
      return true;
    }, "Leave removed");
    void avail.reload();
  }

  const rowEditor = (rows: Row[], setRows: (r: Row[]) => void, allowEveryDay: boolean) => (
    <div className="stack" style={{ gap: 8 }}>
      {rows.map((r, i) => (
        <div className="row" key={i}>
          <select value={r.weekday ?? ""} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, weekday: e.target.value === "" ? null : Number(e.target.value) } : x)))} style={{ width: 130 }}>
            {allowEveryDay && <option value="">Every day</option>}
            {WEEKDAYS.map((d, idx) => <option key={d} value={idx}>{d}</option>)}
          </select>
          <input type="time" value={r.start} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, start: e.target.value } : x)))} style={{ width: 120 }} />
          <span>to</span>
          <input type="time" value={r.end} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, end: e.target.value } : x)))} style={{ width: 120 }} />
          <button className="btn small danger" onClick={() => setRows(rows.filter((_, j) => j !== i))} aria-label="Remove">×</button>
        </div>
      ))}
    </div>
  );

  return (
    <div className="grid grid-2">
      <Card title={`${resource.name}: working hours`}>
        <ErrorBox error={save.error || avail.error} />
        <h3>Weekly hours</h3>
        {weekly.length === 0 && <p className="muted small">No hours yet — {resource.name} can&apos;t be booked.</p>}
        {rowEditor(weekly.slice().sort((a, b) => (a.weekday ?? 0) - (b.weekday ?? 0) || a.start.localeCompare(b.start)), setWeekly, false)}
        <div className="row" style={{ marginTop: 8 }}>
          <button className="btn small" onClick={() => setWeekly([...weekly, { weekday: 0, start: "10:00", end: "13:00" }])}>Add block</button>
          <button className="btn small" onClick={copyMondayToWeekdays} disabled={!weekly.some((w) => w.weekday === 0)}>Copy Monday to Mon–Sat</button>
        </div>
        <h3 style={{ marginTop: 16 }}>Breaks</h3>
        {rowEditor(breaks, setBreaks, true)}
        <div className="row" style={{ marginTop: 8 }}>
          <button className="btn small" onClick={() => setBreaks([...breaks, { weekday: null, start: "13:00", end: "14:00" }])}>Add break</button>
        </div>
        <div className="form-actions">
          <button className="btn primary" disabled={save.busy} onClick={() => void saveHours()}>Save hours</button>
        </div>
      </Card>
      <Card title="Leave">
        <ErrorBox error={leaveAction.error} />
        {avail.data?.leave.length ? (
          <table>
            <tbody>
              {avail.data.leave.map((l) => (
                <tr key={l.id}>
                  <td>{fmtDate(l.start_at)}{l.end_at && l.end_at.slice(0, 10) !== l.start_at?.slice(0, 10) ? ` → ${fmtDate(l.end_at)}` : ""}</td>
                  <td className="muted small">{l.reason}</td>
                  <td className="actions"><button className="btn small" onClick={() => void removeLeave(l.id)}>Remove</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="muted small">No upcoming leave.</p>}
        <form onSubmit={addLeave} className="stack" style={{ gap: 10, marginTop: 12 }}>
          <div className="form-grid">
            <Field label="From"><input type="date" value={leave.start_date} onChange={(e) => setLeave({ ...leave, start_date: e.target.value })} required /></Field>
            <Field label="To (inclusive)"><input type="date" value={leave.end_date} onChange={(e) => setLeave({ ...leave, end_date: e.target.value })} /></Field>
          </div>
          <Field label="Reason (internal)"><input value={leave.reason} onChange={(e) => setLeave({ ...leave, reason: e.target.value })} /></Field>
          <label className="check"><input type="checkbox" checked={leave.move_appointments} onChange={(e) => setLeave({ ...leave, move_appointments: e.target.checked })} /> Cancel booked {v.people} and offer them 3 new slots each</label>
          <div className="form-actions"><button className="btn primary" disabled={leaveAction.busy}>Add leave</button></div>
        </form>
      </Card>
    </div>
  );
}
