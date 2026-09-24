"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { bpath, useBusiness } from "@/lib/business";
import { WEEKDAYS, fmtDate } from "@/lib/format";
import type { BatchDetail, StaffMember, Student, TimetableRow } from "@/lib/types";
import { Card, Confirm, Empty, ErrorBox, Field, Modal, useAction, useLoad } from "@/components/ui";

function fmt12(hhmm: string | null): string {
  if (!hhmm) return "";
  const [h, m] = hhmm.split(":").map(Number);
  return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
}

export default function BatchPage() {
  const { id } = useParams<{ id: string }>();
  const { business } = useBusiness();
  const router = useRouter();
  const batch = useLoad(() => api<BatchDetail>(bpath(business, `/institute/batches/${id}`)), [business?.id, id]);
  const staff = useLoad(() => api<StaffMember[]>(bpath(business, "/staff")), [business?.id]);
  const timetable = useLoad(() => api<TimetableRow[]>(bpath(business, "/institute/timetable"), { query: { group_id: id } }), [business?.id, id]);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Student | null>(null);
  const [teacherIds, setTeacherIds] = useState<number[]>([]);
  const [renaming, setRenaming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const act = useAction();

  useEffect(() => {
    if (batch.data) setTeacherIds(batch.data.teachers.map((t) => t.id));
  }, [batch.data]);

  if (batch.error) return <ErrorBox error={batch.error} />;
  if (!batch.data) return <Empty>Loading…</Empty>;
  const b = batch.data;

  async function saveTeachers() {
    const ok = await act.run(() => api(bpath(business, `/institute/batches/${id}/teachers`), { method: "PUT", body: { staff_ids: teacherIds } }), "Teachers saved");
    if (ok) void batch.reload();
  }

  async function remove(s: Student) {
    await act.run(async () => {
      await api(bpath(business, `/institute/batches/${id}/students/${s.id}`), { method: "DELETE" });
      return true;
    }, `${s.name || s.roll} removed from ${b.name}`);
    void batch.reload();
  }

  async function deleteBatch() {
    const ok = await act.run(async () => {
      await api(bpath(business, `/institute/batches/${id}`), { method: "DELETE" });
      return true;
    }, "Batch deleted");
    if (ok) router.push("/institute/batches");
  }

  const weekly = (timetable.data || []).filter((t) => t.weekday !== null);
  const dated = (timetable.data || []).filter((t) => t.date);

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <div className="small"><Link href="/institute/batches">← Batches</Link></div>
          <h1>{b.name}</h1>
          <div className="muted">{b.students.length} student{b.students.length === 1 ? "" : "s"} · {b.teachers.length} teacher{b.teachers.length === 1 ? "" : "s"}</div>
        </div>
        <div className="row">
          <button className="btn" onClick={() => setRenaming(true)}>Rename</button>
          <Link className="btn" href={`/institute/announcements?batch=${b.id}`}>Send announcement</Link>
          <button className="btn primary" onClick={() => setAdding(true)}>Add student</button>
        </div>
      </div>
      <ErrorBox error={act.error} />

      <Card title="Students">
        {b.students.length === 0 ? <Empty>No students yet. Add them one by one or import an Excel sheet on the Uploads page.</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Roll</th><th>Name</th><th>Student WhatsApp</th><th>Parents</th><th /></tr></thead>
              <tbody>
                {b.students.map((s) => (
                  <tr key={s.id}>
                    <td>{s.roll || "—"}</td>
                    <td><Link href={`/patients/${s.id}`}>{s.name || "—"}</Link> {s.opted_out && <span className="badge">opted out</span>}</td>
                    <td className="nowrap">{s.phone || <span className="muted">via parent</span>}</td>
                    <td className="small">
                      {s.parents.length === 0 ? <span className="badge warn">no parent number</span> : s.parents.map((p) => (
                        <div key={p.id}>{p.name ? `${p.name} ` : ""}<span className="muted">{p.phone}</span></div>
                      ))}
                    </td>
                    <td className="actions">
                      <button className="btn small" onClick={() => setEditing(s)}>Edit</button>{" "}
                      <button className="btn small danger" onClick={() => void remove(s)}>Remove</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="grid grid-2">
        <Card title="Teachers" actions={<button className="btn small primary" disabled={act.busy} onClick={() => void saveTeachers()}>Save</button>}>
          <p className="small muted">Teachers can send announcements and absence alerts only to their own batches.</p>
          {!staff.data ? <Empty>Loading…</Empty> : (
            <div className="stack" style={{ gap: 6 }}>
              {staff.data.filter((s) => s.is_active).map((s) => (
                <label key={s.id} className="check">
                  <input
                    type="checkbox"
                    checked={teacherIds.includes(s.id)}
                    onChange={(e) => setTeacherIds(e.target.checked ? [...teacherIds, s.id] : teacherIds.filter((x) => x !== s.id))}
                  />
                  {s.name} <span className="muted small">{s.role}</span>
                </label>
              ))}
            </div>
          )}
        </Card>
        <Card title="Timetable" actions={<Link className="btn small" href="/institute/uploads?kind=timetable">Upload timetable</Link>}>
          {weekly.length === 0 && dated.length === 0 ? <Empty>No timetable uploaded.</Empty> : (
            <table>
              <tbody>
                {weekly.map((t) => (
                  <tr key={t.id}>
                    <td className="nowrap">{WEEKDAYS[t.weekday ?? 0]}</td>
                    <td className="nowrap">{fmt12(t.start)}{t.end ? `–${fmt12(t.end)}` : ""}</td>
                    <td>{t.subject}<div className="small muted">{[t.teacher, t.room].filter(Boolean).join(" · ")}</div></td>
                  </tr>
                ))}
                {dated.map((t) => (
                  <tr key={t.id}>
                    <td className="nowrap"><span className="badge info">{fmtDate(t.date)}</span></td>
                    <td className="nowrap">{fmt12(t.start)}{t.end ? `–${fmt12(t.end)}` : ""}</td>
                    <td>{t.subject}<div className="small muted">{[t.teacher, t.room].filter(Boolean).join(" · ")}</div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="small muted" style={{ marginTop: 8 }}>Students and parents get answers to &quot;timetable tomorrow&quot; from this.</p>
        </Card>
      </div>

      <Card title="Danger zone">
        <button className="btn danger" onClick={() => setDeleting(true)}>Delete batch</button>
        <span className="small muted"> Students stay in WAM; only the batch is removed.</span>
      </Card>

      {adding && <StudentForm groupId={b.id} onClose={() => setAdding(false)} onDone={() => { setAdding(false); void batch.reload(); }} />}
      {editing && <EditStudent student={editing} onClose={() => setEditing(null)} onDone={() => { setEditing(null); void batch.reload(); }} />}
      {deleting && (
        <Confirm title={`Delete ${b.name}?`} confirmLabel="Delete batch" danger busy={act.busy} onConfirm={() => void deleteBatch()} onClose={() => setDeleting(false)}>
          <p>The batch, its teacher links and its timetable are removed. Students and parents stay in WAM.</p>
        </Confirm>
      )}
      {renaming && <RenameBatch id={b.id} name={b.name} onClose={() => setRenaming(false)} onDone={() => { setRenaming(false); void batch.reload(); }} />}
    </div>
  );
}

function StudentForm({ groupId, onClose, onDone }: { groupId: number; onClose: () => void; onDone: () => void }) {
  const { business } = useBusiness();
  const [f, setF] = useState({ name: "", roll: "", phone: "", p1: "", p1name: "", p2: "", p2name: "" });
  const { busy, error, run } = useAction();
  async function save(e: React.FormEvent) {
    e.preventDefault();
    const body = {
      name: f.name || null,
      roll: f.roll || null,
      phone: f.phone || null,
      parent_phones: [f.p1, f.p2].filter(Boolean),
      parent_names: [f.p1 ? f.p1name || null : null, f.p2 ? f.p2name || null : null].filter((_, i) => [f.p1, f.p2][i]),
    };
    const ok = await run(() => api(bpath(business, `/institute/batches/${groupId}/students`), { method: "POST", body }), "Student saved");
    if (ok) onDone();
  }
  return (
    <Modal title="Add student" onClose={onClose}>
      <form onSubmit={save}>
        <ErrorBox error={error} />
        <div className="form-grid">
          <Field label="Name"><input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required /></Field>
          <Field label="Roll number"><input value={f.roll} onChange={(e) => setF({ ...f, roll: e.target.value })} /></Field>
          <Field label="Student WhatsApp (optional)"><input value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} /></Field>
        </div>
        <div className="form-grid" style={{ marginTop: 12 }}>
          <Field label="Parent 1 WhatsApp"><input value={f.p1} onChange={(e) => setF({ ...f, p1: e.target.value })} /></Field>
          <Field label="Parent 1 name"><input value={f.p1name} onChange={(e) => setF({ ...f, p1name: e.target.value })} /></Field>
          <Field label="Parent 2 WhatsApp"><input value={f.p2} onChange={(e) => setF({ ...f, p2: e.target.value })} /></Field>
          <Field label="Parent 2 name"><input value={f.p2name} onChange={(e) => setF({ ...f, p2name: e.target.value })} /></Field>
        </div>
        <p className="small muted" style={{ marginTop: 8 }}>An existing roll number updates that student and adds them to this batch.</p>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={busy}>Save</button>
        </div>
      </form>
    </Modal>
  );
}

function EditStudent({ student, onClose, onDone }: { student: Student; onClose: () => void; onDone: () => void }) {
  const { business } = useBusiness();
  const [name, setName] = useState(student.name || "");
  const [roll, setRoll] = useState(student.roll || "");
  const [phone, setPhone] = useState("");
  const [pname, setPname] = useState("");
  const { busy, error, run } = useAction();
  async function save(e: React.FormEvent) {
    e.preventDefault();
    const ok = await run(async () => {
      await api(bpath(business, `/institute/students/${student.id}`), { method: "PATCH", body: { name, roll: roll || null } });
      if (phone) await api(bpath(business, `/institute/students/${student.id}/parents`), { method: "POST", body: { phone, name: pname || null } });
      return true;
    }, "Student updated");
    if (ok) onDone();
  }
  async function unlink(pid: number) {
    const ok = await run(async () => {
      await api(bpath(business, `/institute/students/${student.id}/parents/${pid}`), { method: "DELETE" });
      return true;
    }, "Parent number removed");
    if (ok) onDone();
  }
  return (
    <Modal title={`Edit ${student.name || student.roll}`} onClose={onClose}>
      <form onSubmit={save}>
        <ErrorBox error={error} />
        <div className="form-grid">
          <Field label="Name"><input value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Roll number"><input value={roll} onChange={(e) => setRoll(e.target.value)} /></Field>
        </div>
        <h3 style={{ marginTop: 14 }}>Parents</h3>
        {student.parents.map((p) => (
          <div key={p.id} className="row">
            <span>{p.name || "Parent"} <span className="muted">{p.phone}</span></span>
            <button type="button" className="btn small danger" onClick={() => void unlink(p.id)}>Remove</button>
          </div>
        ))}
        {student.parents.length < 2 && (
          <div className="form-grid" style={{ marginTop: 8 }}>
            <Field label="Add parent WhatsApp"><input value={phone} onChange={(e) => setPhone(e.target.value)} /></Field>
            <Field label="Parent name"><input value={pname} onChange={(e) => setPname(e.target.value)} /></Field>
          </div>
        )}
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={busy}>Save</button>
        </div>
      </form>
    </Modal>
  );
}

function RenameBatch({ id, name, onClose, onDone }: { id: number; name: string; onClose: () => void; onDone: () => void }) {
  const { business } = useBusiness();
  const [value, setValue] = useState(name);
  const { busy, error, run } = useAction();
  return (
    <Modal title="Rename batch" onClose={onClose}>
      <form onSubmit={async (e) => {
        e.preventDefault();
        const ok = await run(() => api(bpath(business, `/institute/batches/${id}`), { method: "PATCH", body: { name: value } }), "Renamed");
        if (ok) onDone();
      }}>
        <ErrorBox error={error} />
        <Field label="Name"><input value={value} onChange={(e) => setValue(e.target.value)} required /></Field>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={busy}>Save</button>
        </div>
      </form>
    </Modal>
  );
}
