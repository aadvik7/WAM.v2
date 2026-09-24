"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { api, apiUpload } from "@/lib/api";
import { bpath, useBusiness } from "@/lib/business";
import { WEEKDAYS, fmtDateTime } from "@/lib/format";
import type { Batch, Upload, UploadRow } from "@/lib/types";
import { Card, Confirm, Empty, ErrorBox, Field, Modal, StatusBadge, Tabs, useAction, useLoad } from "@/components/ui";

type Kind = Upload["kind"];

const KINDS: {
  key: Kind;
  label: string;
  intro: string;
  columns: string;
  sample: string[][];
  labelField?: { label: string; placeholder: string; hint: string };
  batchHint: string;
}[] = [
  {
    key: "students",
    label: "Students",
    intro: "Add or update students and link each one to 1–2 parent numbers. Nothing is sent.",
    columns: "Roll No, Name, Phone, Parent Phone, Parent 2 Phone (optional), Batch",
    sample: [
      ["Roll No", "Name", "Phone", "Parent Phone", "Parent 2 Phone", "Batch"],
      ["12", "Aarav Shah", "98200 11111", "98200 22222", "", "NEET-A2"],
      ["15", "Diya Nair", "", "98200 33333", "98200 44444", "NEET-A2"],
    ],
    batchHint: "Used for rows without a Batch column",
  },
  {
    key: "attendance",
    label: "Attendance",
    intro: "Parents of absent students get an alert. List everyone with a P/A column, or only the absent students.",
    columns: "Roll No (or Name), Status (P / A — optional)",
    sample: [
      ["Roll No", "Name", "Status"],
      ["12", "Aarav Shah", "P"],
      ["15", "Diya Nair", "A"],
    ],
    labelField: { label: "Class", placeholder: "e.g. Physics", hint: "Shown to parents: “… absent in Physics today”" },
    batchHint: "Optional; helps match students by name",
  },
  {
    key: "results",
    label: "Test results",
    intro: "Each parent (and the student) gets that student's score.",
    columns: "Roll No (or Name), Marks, Max Marks (optional), Test (optional)",
    sample: [
      ["Roll No", "Name", "Marks", "Max Marks"],
      ["12", "Aarav Shah", "620", "720"],
      ["15", "Diya Nair", "588", "720"],
    ],
    labelField: { label: "Test name", placeholder: "e.g. Weekly Test 7", hint: "Used when the sheet has no Test column" },
    batchHint: "Optional; helps match students by name",
  },
  {
    key: "timetable",
    label: "Timetable",
    intro: "Students and parents can then ask “What's my timetable tomorrow?”. A weekly sheet replaces the batch's old weekly timetable.",
    columns: "Batch, Day (Mon–Sun) or Date, Start, End, Subject, Teacher, Room",
    sample: [
      ["Batch", "Day", "Start", "End", "Subject", "Teacher", "Room"],
      ["NEET-A2", "Mon", "4:00 PM", "5:30 PM", "Physics", "Mr. Rao", "Room 2"],
      ["NEET-A2", "Tue", "4:00 PM", "5:30 PM", "Chemistry", "Ms. Iyer", "Room 2"],
    ],
    batchHint: "Used for rows without a Batch column",
  },
];

function sampleUrl(rows: string[][]): string {
  const csv = rows.map((r) => r.map((c) => (/[",\n]/.test(c) ? `"${c.replace(/"/g, '""')}"` : c)).join(",")).join("\n");
  return `data:text/csv;charset=utf-8,${encodeURIComponent(csv)}`;
}

export default function UploadsPage() {
  return (
    <Suspense fallback={<Empty>Loading…</Empty>}>
      <Uploads />
    </Suspense>
  );
}

function Uploads() {
  const { business } = useBusiness();
  const params = useSearchParams();
  const initial = (KINDS.find((k) => k.key === params.get("kind"))?.key || "students") as Kind;
  const [kind, setKind] = useState<Kind>(initial);
  const batches = useLoad(() => api<Batch[]>(bpath(business, "/institute/batches")), [business?.id]);
  const history = useLoad(() => api<Upload[]>(bpath(business, "/institute/uploads")), [business?.id]);
  const [groupId, setGroupId] = useState("");
  const [label, setLabel] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [current, setCurrent] = useState<Upload | null>(null);
  const [viewing, setViewing] = useState<number | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const act = useAction();
  const spec = KINDS.find((k) => k.key === kind)!;

  // Sends go out in the background; keep the history fresh while any are still going.
  const sending = (history.data || []).some((u) => Number(u.summary.remaining || 0) > 0);
  const reloadHistory = history.reload;
  useEffect(() => {
    if (!sending) return;
    const t = setInterval(() => void reloadHistory(), 5000);
    return () => clearInterval(t);
  }, [sending, reloadHistory]);

  function reset() {
    setFile(null);
    setLabel("");
    if (fileRef.current) fileRef.current.value = "";
  }

  async function upload(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    const form = new FormData();
    form.set("kind", kind);
    form.set("file", file);
    if (label.trim()) form.set("label", label.trim());
    if (groupId) form.set("group_id", groupId);
    const result = await act.run(() => apiUpload<Upload>(bpath(business, "/institute/uploads"), form));
    if (result) {
      setCurrent(result);
      reset();
      void history.reload();
    }
  }

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Uploads</h1>
          <div className="muted">Upload an Excel (.xlsx) or CSV sheet. You always see a preview before anything is saved or sent.</div>
        </div>
      </div>

      <Tabs tabs={KINDS.map((k) => ({ key: k.key, label: k.label }))} value={kind} onChange={(k) => { setKind(k); setCurrent(null); act.setError(null); }} />

      <div className="grid grid-2">
        <Card title={`Upload ${spec.label.toLowerCase()}`}>
          <form onSubmit={upload} className="stack" style={{ gap: 10 }}>
            <p className="small" style={{ margin: 0 }}>{spec.intro}</p>
            <ErrorBox error={act.error} />
            <Field label="Batch" hint={spec.batchHint}>
              <select value={groupId} onChange={(e) => setGroupId(e.target.value)}>
                <option value="">{kind === "students" || kind === "timetable" ? "From the sheet" : "Any batch"}</option>
                {(batches.data || []).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
            </Field>
            {spec.labelField && (
              <Field label={spec.labelField.label} hint={spec.labelField.hint}>
                <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder={spec.labelField.placeholder} maxLength={120} />
              </Field>
            )}
            <Field label="Sheet" hint="Excel .xlsx or .csv, up to 5 MB">
              <input ref={fileRef} type="file" accept=".xlsx,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv" onChange={(e) => setFile(e.target.files?.[0] || null)} required />
            </Field>
            <div className="form-actions">
              <button className="btn primary" disabled={act.busy || !file}>{act.busy ? "Reading…" : "Upload and preview"}</button>
            </div>
          </form>
        </Card>
        <Card title="Columns WAM looks for">
          <p className="small">{spec.columns}</p>
          <p className="small muted">
            Common names work too (“Roll No.”, “Adm No”, “Father Mobile”, “Marks Obtained”…). Phone numbers can be written with or without +91.
          </p>
          <div className="table-wrap">
            <table className="small">
              <thead><tr>{spec.sample[0].map((h) => <th key={h}>{h}</th>)}</tr></thead>
              <tbody>
                {spec.sample.slice(1).map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c || "—"}</td>)}</tr>)}
              </tbody>
            </table>
          </div>
          <div className="form-actions" style={{ justifyContent: "flex-start" }}>
            <a className="btn small" href={sampleUrl(spec.sample)} download={`wam-${kind}-sample.csv`}>Download sample sheet</a>
          </div>
        </Card>
      </div>

      {current && (
        <Preview
          upload={current}
          onChange={(u) => { setCurrent(u); void history.reload(); }}
          onClose={() => setCurrent(null)}
        />
      )}

      <Card title="Recent uploads" actions={<button className="btn small" onClick={() => void history.reload()}>Refresh</button>}>
        <ErrorBox error={history.error} />
        {!history.data ? <Empty>Loading…</Empty> : history.data.length === 0 ? <Empty>No uploads yet.</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>When</th><th>Type</th><th>File</th><th>Status</th><th>Result</th><th /></tr></thead>
              <tbody>
                {history.data.map((u) => (
                  <tr key={u.id}>
                    <td className="nowrap">{fmtDateTime(u.created_at)}</td>
                    <td>{KINDS.find((k) => k.key === u.kind)?.label}{u.label ? ` · ${u.label}` : ""}</td>
                    <td className="small">{u.filename}</td>
                    <td><StatusBadge status={u.status} /></td>
                    <td className="small">{resultText(u)}</td>
                    <td className="actions"><button className="btn small" onClick={() => setViewing(u.id)}>{u.status === "preview" ? "Review" : "View"}</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {viewing !== null && (
        <UploadModal id={viewing} onClose={() => { setViewing(null); void history.reload(); }} />
      )}
    </div>
  );
}

function num(v: unknown): number {
  return Number(v || 0);
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

function previewText(u: Upload): string {
  const s = u.summary;
  switch (u.kind) {
    case "students":
      return `${num(s.new)} new, ${num(s.update)} to update, ${num(s.errors)} with problems`;
    case "attendance":
      return `${num(s.absent)} absent, ${num(s.present)} present, ${num(s.unmatched)} not matched · ${plural(num(s.messages), "message")}`;
    case "results":
      return `${num(s.scores)} scores, ${num(s.unmatched)} not matched · ${plural(num(s.messages), "message")}`;
    default:
      return `${num(s.entries)} classes, ${num(s.errors)} with problems`;
  }
}

function resultText(u: Upload): string {
  if (u.status === "cancelled") return "Not applied";
  if (u.status === "preview") return previewText(u);
  const s = u.summary;
  const applied = (s.applied || {}) as Record<string, unknown>;
  if (u.kind === "students") return `${num(applied.created)} added, ${num(applied.updated)} updated`;
  if (u.kind === "timetable") return `${num(applied.entries)} classes saved`;
  const remaining = num(s.remaining);
  return `${num(s.sent)} sent${num(s.failed) ? `, ${num(s.failed)} failed` : ""}${remaining ? ` · sending ${remaining} more…` : ""}`;
}

function messageCount(u: Upload): number {
  return u.kind === "attendance" || u.kind === "results" ? num(u.summary.messages) : 0;
}

function Preview({ upload, onChange, onClose }: { upload: Upload; onChange: (u: Upload) => void; onClose?: () => void }) {
  const { business } = useBusiness();
  const act = useAction();
  const [confirming, setConfirming] = useState(false);
  const rows = upload.rows || [];
  const problems = rows.filter((r) => r.error).length;
  const messages = messageCount(upload);
  const canApply = upload.status === "preview" && rows.some((r) => !r.error);

  async function apply() {
    const result = await act.run(
      () => api<Upload & { result: Record<string, unknown> }>(bpath(business, `/institute/uploads/${upload.id}/apply`), { method: "POST" }),
      messages ? `Sending ${messages} message${messages === 1 ? "" : "s"}` : "Saved",
    );
    setConfirming(false);
    if (result) onChange({ ...upload, ...result, rows: upload.rows });
  }

  async function cancel() {
    const result = await act.run(() => api<Upload>(bpath(business, `/institute/uploads/${upload.id}/cancel`), { method: "POST" }), "Upload cancelled");
    if (result) onChange({ ...upload, ...result, rows: upload.rows });
  }

  return (
    <Card
      title={`${KINDS.find((k) => k.key === upload.kind)?.label} preview · ${upload.filename}`}
      actions={onClose && <button className="btn small" onClick={onClose}>Close</button>}
    >
      <div className="stack" style={{ gap: 12 }}>
        <div className="row">
          <StatusBadge status={upload.status} />
          <span className="small">{upload.status === "preview" ? previewText(upload) : resultText(upload)}</span>
        </div>
        {problems > 0 && upload.status === "preview" && (
          <div className="alert info">{problems} row{problems === 1 ? "" : "s"} can&apos;t be used and will be skipped. Fix the sheet and upload again if they matter.</div>
        )}
        <ErrorBox error={act.error} />
        <RowsTable upload={upload} />
        {upload.status === "preview" && (
          <div className="form-actions">
            <button className="btn" disabled={act.busy} onClick={() => void cancel()}>Cancel upload</button>
            <button className="btn primary" disabled={act.busy || !canApply} onClick={() => (messages ? setConfirming(true) : void apply())}>
              {messages ? `Send ${messages} message${messages === 1 ? "" : "s"}` : "Save"}
            </button>
          </div>
        )}
        {upload.status === "applied" && Array.isArray((upload.summary.applied as { notes?: string[] } | undefined)?.notes) &&
          ((upload.summary.applied as { notes: string[] }).notes.length > 0) && (
            <div className="alert info small">
              {(upload.summary.applied as { notes: string[] }).notes.map((n) => <div key={n}>{n}</div>)}
            </div>
        )}
      </div>
      {confirming && (
        <Confirm
          title={`Send ${messages} message${messages === 1 ? "" : "s"}?`}
          confirmLabel="Yes, send"
          busy={act.busy}
          onConfirm={() => void apply()}
          onClose={() => setConfirming(false)}
        >
          <p>
            {upload.kind === "attendance"
              ? `Parents of ${num(upload.summary.absent)} absent students will get an attendance alert.`
              : `Families of ${num(upload.summary.scores)} students will get their child's score.`}{" "}
            This can&apos;t be undone.
          </p>
        </Confirm>
      )}
    </Card>
  );
}

function fmt12(hhmm: unknown): string {
  if (typeof hhmm !== "string" || !hhmm) return "";
  const [h, m] = hhmm.split(":").map(Number);
  return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
}

function RowsTable({ upload }: { upload: Upload }) {
  const rows = upload.rows || [];
  if (!rows.length) return <Empty>No rows.</Empty>;
  const str = (v: unknown) => (v === null || v === undefined || v === "" ? "—" : String(v));
  let head: string[];
  let cells: (r: UploadRow) => React.ReactNode[];
  switch (upload.kind) {
    case "students":
      head = ["Row", "Roll", "Name", "Phone", "Parents", "Batch", ""];
      cells = (r) => [r.row, str(r.roll), str(r.name), str(r.phone), ((r.parents as string[]) || []).join(", ") || "—", str(r.batch), r.error ? null : <StatusBadge key="a" status={r.action === "new" ? "booked" : "active"} label={String(r.action)} />];
      break;
    case "attendance":
      head = ["Row", "Student", "Class", "Status", "Messages"];
      cells = (r) => [r.row, str(r.student ?? r.key), str(r.class ?? upload.label), r.error ? "—" : r.absent ? <span key="a" className="badge danger">absent</span> : <span key="p" className="badge ok">present</span>, r.absent && !r.error ? str(r.recipients) : "—"];
      break;
    case "results":
      head = ["Row", "Student", "Test", "Score", "Messages"];
      cells = (r) => [r.row, str(r.student ?? r.key), str(r.test), str(r.score_text ?? r.score), r.error ? "—" : str(r.recipients)];
      break;
    default:
      head = ["Row", "Batch", "When", "Time", "Subject", "Teacher", "Room"];
      cells = (r) => [
        r.row,
        str(r.batch),
        r.date ? str(r.date) : typeof r.weekday === "number" ? WEEKDAYS[r.weekday] : "—",
        r.start ? `${fmt12(r.start)}${r.end ? `–${fmt12(r.end)}` : ""}` : "—",
        str(r.subject),
        str(r.teacher),
        str(r.room),
      ];
  }
  return (
    <div className="table-wrap" style={{ maxHeight: 420, overflowY: "auto" }}>
      <table>
        <thead><tr>{head.map((h, i) => <th key={i}>{h}</th>)}<th>Problem</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.row} style={r.error ? { background: "var(--danger-soft, transparent)" } : undefined}>
              {cells(r).map((c, i) => <td key={i}>{c}</td>)}
              <td className="small">{r.error ? <span className="badge danger">{r.error}</span> : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function UploadModal({ id, onClose }: { id: number; onClose: () => void }) {
  const { business } = useBusiness();
  const detail = useLoad(() => api<Upload>(bpath(business, `/institute/uploads/${id}`)), [business?.id, id]);
  return (
    <Modal title="Upload" onClose={onClose} wide>
      <ErrorBox error={detail.error} />
      {!detail.data ? <Empty>Loading…</Empty> : <Preview upload={detail.data} onChange={(u) => detail.setData(u)} />}
    </Modal>
  );
}
