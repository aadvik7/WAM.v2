"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useBusiness } from "@/lib/business";
import type { AdminUser } from "@/lib/types";
import { Card, Empty, ErrorBox, Field, useAction, useLoad } from "@/components/ui";

export function UsersTab() {
  const { business, user, businesses } = useBusiness();
  const users = useLoad(() => api<AdminUser[]>("/api/admin-users"), []);
  const [form, setForm] = useState({ email: "", name: "", password: "", scope: "business" });
  const { busy, error, run } = useAction();
  const del = useAction();
  const isSuper = user?.business_id === null;

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const body = {
      email: form.email,
      name: form.name || null,
      password: form.password,
      business_id: isSuper && form.scope === "super" ? null : business?.id,
    };
    const ok = await run(() => api("/api/admin-users", { method: "POST", body }), "Admin user added");
    if (ok) {
      setForm({ email: "", name: "", password: "", scope: "business" });
      void users.reload();
    }
  }

  return (
    <div className="grid grid-2">
      <Card title="Admin users">
        <ErrorBox error={users.error || del.error} />
        {!users.data ? <Empty>Loading…</Empty> : (
          <table>
            <tbody>
              {users.data.filter((u) => u.is_active).map((u) => (
                <tr key={u.id}>
                  <td>{u.name || u.email}<div className="small muted">{u.email}</div></td>
                  <td className="small">{u.business_id === null ? <span className="badge accent">super admin</span> : businesses.find((b) => b.id === u.business_id)?.name}</td>
                  <td className="actions">
                    {u.id !== user?.id && (
                      <button className="btn small danger" onClick={() => void del.run(async () => { await api(`/api/admin-users/${u.id}`, { method: "DELETE" }); return true; }, "Access removed").then(() => users.reload())}>Remove</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      <Card title="Add admin user">
        <form onSubmit={save} className="stack" style={{ gap: 12 }}>
          <ErrorBox error={error} />
          <Field label="Email"><input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required /></Field>
          <Field label="Name"><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Password (8+ characters)"><input type="password" autoComplete="new-password" minLength={8} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required /></Field>
          {isSuper && (
            <Field label="Access">
              <select value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value })}>
                <option value="business">Only {business?.name}</option>
                <option value="super">All businesses (super admin)</option>
              </select>
            </Field>
          )}
          <div className="form-actions"><button className="btn primary" disabled={busy}>Add user</button></div>
        </form>
      </Card>
    </div>
  );
}
