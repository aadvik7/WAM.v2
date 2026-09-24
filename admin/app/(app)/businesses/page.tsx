"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useBusiness } from "@/lib/business";
import type { Business } from "@/lib/types";
import { Card, Empty, ErrorBox, Field, useAction } from "@/components/ui";

export default function BusinessesPage() {
  const { user, businesses, select, reload, business } = useBusiness();
  const [form, setForm] = useState({ name: "", type: "clinic", timezone: "Asia/Kolkata" });
  const { busy, error, run } = useAction();
  const isSuper = user?.business_id === null;

  if (!isSuper) return <Empty>Only a super admin can manage businesses.</Empty>;

  async function create(e: React.FormEvent) {
    e.preventDefault();
    const created = await run(() => api<Business>("/api/businesses", { method: "POST", body: form }), "Business created with starter plans and roles");
    if (created) {
      await reload();
      select(created.id);
      setForm({ name: "", type: "clinic", timezone: "Asia/Kolkata" });
    }
  }

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Businesses</h1>
          <div className="muted">Every clinic on this WAM install. Each gets its own WhatsApp inbox, staff, plans and data.</div>
        </div>
      </div>
      <div className="grid grid-2">
        <Card title="All businesses">
          {businesses.length === 0 ? <Empty>None yet.</Empty> : (
            <table>
              <tbody>
                {businesses.map((b) => (
                  <tr key={b.id}>
                    <td>{b.name}<div className="small muted">{b.type} · {b.timezone}</div></td>
                    <td>{b.chatwoot_inbox_id ? <span className="badge ok">WhatsApp linked</span> : <span className="badge warn">not linked</span>}</td>
                    <td className="actions">
                      {business?.id === b.id ? <span className="badge accent">selected</span> : <button className="btn small" onClick={() => select(b.id)}>Open</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card title="Add a business">
          <form onSubmit={create} className="stack" style={{ gap: 12 }}>
            <ErrorBox error={error} />
            <Field label="Name"><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></Field>
            <Field label="Type" hint="Decides which pack loads: starter plans, roles and wording.">
              <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
                <option value="clinic">Clinic (version 1)</option>
                <option value="institute">Institute (preview)</option>
                <option value="business">Business (preview)</option>
              </select>
            </Field>
            <Field label="Timezone"><input value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })} /></Field>
            <div className="form-actions"><button className="btn primary" disabled={busy}>Create</button></div>
          </form>
        </Card>
      </div>
    </div>
  );
}
