"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { bpath, useBusiness } from "@/lib/business";
import { fmtDate } from "@/lib/format";
import type { Contact } from "@/lib/types";
import { Card, Empty, ErrorBox, Field, Modal, useAction, useLoad } from "@/components/ui";
import { useVocab } from "@/lib/vocab";

export default function PatientsPage() {
  const { business } = useBusiness();
  const v = useVocab();
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [waiting, setWaiting] = useState(false);
  const [page, setPage] = useState(1);
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => {
      setQuery(q);
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [q]);

  const { data, error } = useLoad(
    () =>
      api<{ total: number; items: Contact[] }>(bpath(business, "/contacts"), {
        query: { q: query, needs_staff: waiting ? true : undefined, page, page_size: 50 },
      }),
    [business?.id, query, waiting, page],
  );

  return (
    <div className="stack">
      <div className="page-head">
        <h1>{v.People}</h1>
        <button className="btn primary" onClick={() => setAdding(true)}>Add {v.person}</button>
      </div>
      <Card>
        <div className="row" style={{ marginBottom: 12 }}>
          <input style={{ maxWidth: 320 }} placeholder="Search by name or phone" value={q} onChange={(e) => setQ(e.target.value)} />
          <label className="check"><input type="checkbox" checked={waiting} onChange={(e) => setWaiting(e.target.checked)} /> Needs a person</label>
          <span className="spacer" />
          <span className="muted small">{data ? `${data.total} ${v.people}` : ""}</span>
        </div>
        <ErrorBox error={error} />
        {!data ? (
          <Empty>Loading…</Empty>
        ) : data.items.length === 0 ? (
          <Empty>No {v.people} found.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Name</th><th>WhatsApp</th><th>Active plans</th><th>Consent</th><th>Added</th></tr></thead>
              <tbody>
                {data.items.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <Link href={`/patients/${c.id}`}>{c.name || "Unknown"}</Link>{" "}
                      {c.needs_staff && <span className="badge warn">needs a person</span>}{" "}
                      {c.opted_out && <span className="badge">opted out</span>}
                    </td>
                    <td className="nowrap">{c.phone || (c.guardian ? `${c.guardian.phone} (guardian)` : "—")}</td>
                    <td>{c.active_plans ?? 0}</td>
                    <td>{c.consent_at ? <span className="badge ok">given</span> : c.consent_notice_sent_at ? <span className="badge info">notice sent</span> : <span className="muted small">—</span>}</td>
                    <td className="nowrap muted">{fmtDate(c.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && data.total > 50 && (
          <div className="row" style={{ marginTop: 12, justifyContent: "flex-end" }}>
            <button className="btn small" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
            <span className="small muted">Page {page} of {Math.ceil(data.total / 50)}</span>
            <button className="btn small" disabled={page * 50 >= data.total} onClick={() => setPage(page + 1)}>Next</button>
          </div>
        )}
      </Card>
      {adding && <AddPatient onClose={() => setAdding(false)} />}
    </div>
  );
}

function AddPatient({ onClose }: { onClose: () => void }) {
  const { business } = useBusiness();
  const v = useVocab();
  const router = useRouter();
  const [form, setForm] = useState({ name: "", phone: "", child: false, guardian_phone: "", guardian_name: "", date_of_birth: "", notes: "" });
  const { busy, error, run } = useAction();
  const set = (k: keyof typeof form, v: string | boolean) => setForm((f) => ({ ...f, [k]: v }));

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const body = {
      name: form.name || null,
      phone: form.child ? null : form.phone || null,
      guardian_phone: form.child ? form.guardian_phone : null,
      guardian_name: form.child ? form.guardian_name || null : null,
      date_of_birth: form.date_of_birth || null,
      notes: form.notes || null,
    };
    const created = await run(() => api<Contact>(bpath(business, "/contacts"), { method: "POST", body }), `${v.Person} added`);
    if (created) router.push(`/patients/${created.id}`);
  }

  return (
    <Modal title={`Add ${v.person}`} onClose={onClose}>
      <form onSubmit={save}>
        <ErrorBox error={error} />
        <div className="stack" style={{ gap: 12 }}>
          <Field label="Name"><input value={form.name} onChange={(e) => set("name", e.target.value)} required /></Field>
          <label className="check">
            <input type="checkbox" checked={form.child} onChange={(e) => set("child", e.target.checked)} /> Child — reach them through a parent&apos;s WhatsApp
          </label>
          {form.child ? (
            <div className="form-grid">
              <Field label="Parent's WhatsApp number"><input value={form.guardian_phone} onChange={(e) => set("guardian_phone", e.target.value)} required placeholder="98xxxxxxxx" /></Field>
              <Field label="Parent's name"><input value={form.guardian_name} onChange={(e) => set("guardian_name", e.target.value)} /></Field>
            </div>
          ) : (
            <Field label="WhatsApp number" hint="10-digit Indian numbers get +91 automatically.">
              <input value={form.phone} onChange={(e) => set("phone", e.target.value)} required placeholder="98xxxxxxxx" />
            </Field>
          )}
          <Field label="Date of birth (for vaccination schedules)"><input type="date" value={form.date_of_birth} onChange={(e) => set("date_of_birth", e.target.value)} /></Field>
          <Field label="Notes"><textarea value={form.notes} onChange={(e) => set("notes", e.target.value)} /></Field>
        </div>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={busy}>{busy ? "Saving…" : `Add ${v.person}`}</button>
        </div>
      </form>
    </Modal>
  );
}
