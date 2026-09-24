"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { bpath, useBusiness } from "@/lib/business";
import type { Template } from "@/lib/types";
import { Card, Empty, ErrorBox, Field, Modal, useAction, useLoad } from "@/components/ui";

function describe(t: Template): string {
  if (t.offsets_days) return `${t.offsets_days.length} visits at set ages (days from birth: ${t.offsets_days.join(", ")})`;
  if (t.session_count) return `${t.session_count} visit${t.session_count > 1 ? "s" : ""}, ${t.gap_days} days apart`;
  return `Ongoing, every ${t.gap_days} days`;
}

export function PlansTab() {
  const { business } = useBusiness();
  const { data, error, reload } = useLoad(() => api<Template[]>(bpath(business, "/templates")), [business?.id]);
  const [editing, setEditing] = useState<Template | "new" | null>(null);
  const remove = useAction();

  return (
    <Card title="Plan templates" actions={<button className="btn primary small" onClick={() => setEditing("new")}>New template</button>}>
      <p className="muted small">
        A plan is a series of due dates. WAM nudges the patient with free slots when each visit is due, reminds them the day
        before, and follows up if they miss it. Staff can enrol patients by WhatsApp with any name or alias, e.g. &quot;Rahul, RCT&quot;.
      </p>
      <ErrorBox error={error || remove.error} />
      {!data ? <Empty>Loading…</Empty> : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Name</th><th>Pattern</th><th>Visit length</th><th>WhatsApp aliases</th><th>Status</th><th /></tr></thead>
            <tbody>
              {data.map((t) => (
                <tr key={t.id}>
                  <td>{t.name}<div className="small muted">{t.specialty}</div></td>
                  <td>{describe(t)}</td>
                  <td>{t.duration_minutes ? `${t.duration_minutes} min` : "doctor's slot"}</td>
                  <td className="small">{t.aliases.join(", ") || "—"}</td>
                  <td>{t.is_active ? <span className="badge ok">active</span> : <span className="badge">hidden</span>}</td>
                  <td className="actions">
                    <button className="btn small" onClick={() => setEditing(t)}>Edit</button>{" "}
                    <button className="btn small danger" disabled={remove.busy} onClick={() => void remove.run(async () => { await api(bpath(business, `/templates/${t.id}`), { method: "DELETE" }); return true; }, "Template removed (hidden if already in use)").then(() => reload())}>Remove</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing && <TemplateForm template={editing === "new" ? null : editing} onClose={() => setEditing(null)} onDone={() => { setEditing(null); void reload(); }} />}
    </Card>
  );
}

type Kind = "fixed" | "ongoing" | "ages";

function TemplateForm({ template, onClose, onDone }: { template: Template | null; onClose: () => void; onDone: () => void }) {
  const { business } = useBusiness();
  const initialKind: Kind = template?.offsets_days ? "ages" : template && template.session_count === null ? "ongoing" : "fixed";
  const [kind, setKind] = useState<Kind>(initialKind);
  const [form, setForm] = useState({
    name: template?.name || "",
    specialty: template?.specialty || "",
    session_count: template?.session_count || 3,
    gap_days: template?.gap_days ?? 7,
    offsets: (template?.offsets_days || []).join(", "),
    labels: (template?.session_labels || []).join(", "),
    duration_minutes: template?.duration_minutes ?? "",
    aliases: (template?.aliases || []).join(", "),
    is_active: template?.is_active ?? true,
  });
  const { busy, error, run, setError } = useAction();

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const list = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);
    let offsets: number[] | null = null;
    if (kind === "ages") {
      offsets = list(form.offsets).map(Number);
      if (!offsets.length || offsets.some((n) => !Number.isInteger(n) || n < 0)) {
        setError(new Error("Offsets must be whole numbers of days, e.g. 0, 42, 70"));
        return;
      }
    }
    const body: Record<string, unknown> = {
      name: form.name,
      specialty: form.specialty || null,
      gap_days: Number(form.gap_days),
      duration_minutes: form.duration_minutes === "" ? null : Number(form.duration_minutes),
      aliases: list(form.aliases).map((a) => a.toLowerCase()),
      session_labels: list(form.labels).length ? list(form.labels) : null,
      is_active: form.is_active,
      offsets_days: offsets,
      session_count: kind === "fixed" ? Number(form.session_count) : null,
    };
    if (template && kind === "ongoing") body.ongoing = true;
    const ok = await run(
      () => api(bpath(business, template ? `/templates/${template.id}` : "/templates"), { method: template ? "PATCH" : "POST", body }),
      "Template saved",
    );
    if (ok) onDone();
  }

  return (
    <Modal title={template ? `Edit ${template.name}` : "New plan template"} onClose={onClose}>
      <form onSubmit={save}>
        <ErrorBox error={error} />
        <div className="stack" style={{ gap: 12 }}>
          <div className="form-grid">
            <Field label="Name"><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></Field>
            <Field label="Specialty" hint="Matches doctors with the same specialty."><input value={form.specialty} onChange={(e) => setForm({ ...form, specialty: e.target.value })} /></Field>
          </div>
          <Field label="Pattern">
            <select value={kind} onChange={(e) => setKind(e.target.value as Kind)}>
              <option value="fixed">Fixed number of visits (e.g. 3-sitting root canal)</option>
              <option value="ongoing">Ongoing recall (e.g. cleaning every 6 months)</option>
              <option value="ages">Set ages from date of birth (e.g. vaccinations)</option>
            </select>
          </Field>
          <div className="form-grid">
            {kind === "fixed" && <Field label="Number of visits"><input type="number" min={1} value={form.session_count} onChange={(e) => setForm({ ...form, session_count: Number(e.target.value) })} /></Field>}
            {kind !== "ages" && <Field label="Days between visits"><input type="number" min={0} value={form.gap_days} onChange={(e) => setForm({ ...form, gap_days: Number(e.target.value) })} /></Field>}
            <Field label="Visit length (minutes)" hint="Blank = the doctor's slot length."><input type="number" min={5} value={form.duration_minutes} onChange={(e) => setForm({ ...form, duration_minutes: e.target.value === "" ? "" : Number(e.target.value) })} /></Field>
          </div>
          {kind === "ages" && (
            <Field label="Days from birth for each visit" hint="Comma separated, e.g. 0, 42, 70, 98"><input value={form.offsets} onChange={(e) => setForm({ ...form, offsets: e.target.value })} /></Field>
          )}
          <Field label="Visit labels (optional)" hint="Comma separated, e.g. 1st sitting, 2nd sitting, 3rd sitting"><input value={form.labels} onChange={(e) => setForm({ ...form, labels: e.target.value })} /></Field>
          <Field label="WhatsApp aliases" hint="Other names staff may type, e.g. rct, root canal treatment"><input value={form.aliases} onChange={(e) => setForm({ ...form, aliases: e.target.value })} /></Field>
          <label className="check"><input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} /> Active</label>
        </div>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={busy}>Save</button>
        </div>
      </form>
    </Modal>
  );
}
