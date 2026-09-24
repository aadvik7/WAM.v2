"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { bpath, useBusiness } from "@/lib/business";
import type { Meta, Role, StaffMember } from "@/lib/types";
import { Card, Empty, ErrorBox, Field, Modal, useAction, useLoad } from "@/components/ui";

const COMMAND_LABELS: Record<string, string> = {
  today: "Today's list",
  cancel: "Cancel a visit (PIN)",
  late: "Running late",
  leave: "On leave (PIN)",
  enrol: "Enrol in a plan",
  followup: "Schedule follow-up",
  attendance: "Mark attendance",
  summary: "Summary",
  find: "Find patient",
  help: "Help",
};

export function StaffTab() {
  const { business } = useBusiness();
  const staff = useLoad(() => api<StaffMember[]>(bpath(business, "/staff")), [business?.id]);
  const roles = useLoad(() => api<Role[]>(bpath(business, "/roles")), [business?.id]);
  const meta = useLoad(() => api<Meta>("/api/meta"), []);
  const [editing, setEditing] = useState<StaffMember | "new" | null>(null);
  const [pinFor, setPinFor] = useState<StaffMember | null>(null);
  const [roleEdit, setRoleEdit] = useState<Role | "new" | null>(null);
  const del = useAction();

  return (
    <div className="stack">
      <Card title="Staff on WhatsApp" actions={<button className="btn primary small" onClick={() => setEditing("new")}>Add staff</button>}>
        <p className="muted small">
          Staff message the clinic&apos;s WhatsApp number from their own phones. WAM recognises them by number. Cancelling visits and
          taking leave need &quot;YES&quot; plus their PIN; every action is in the audit log.
        </p>
        <ErrorBox error={staff.error || del.error} />
        {!staff.data ? <Empty>Loading…</Empty> : staff.data.length === 0 ? <Empty>No staff yet.</Empty> : (
          <table>
            <thead><tr><th>Name</th><th>WhatsApp</th><th>Role</th><th>PIN</th><th>End-of-day list</th><th /></tr></thead>
            <tbody>
              {staff.data.map((s) => (
                <tr key={s.id}>
                  <td>{s.name} {!s.is_active && <span className="badge">inactive</span>}</td>
                  <td className="nowrap">{s.phone}</td>
                  <td>{s.role || <span className="muted">—</span>}</td>
                  <td>{s.pin_locked ? <span className="badge danger">locked</span> : s.pin_set ? <span className="badge ok">set</span> : <span className="badge warn">not set</span>}</td>
                  <td>{s.receives_eod_list ? "Yes" : "—"}</td>
                  <td className="actions">
                    <button className="btn small" onClick={() => setPinFor(s)}>Set PIN</button>{" "}
                    <button className="btn small" onClick={() => setEditing(s)}>Edit</button>{" "}
                    <button className="btn small danger" onClick={() => void del.run(async () => { await api(bpath(business, `/staff/${s.id}`), { method: "DELETE" }); return true; }, "Removed").then(() => staff.reload())}>Remove</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      <Card title="Roles" actions={<button className="btn small" onClick={() => setRoleEdit("new")}>New role</button>}>
        {!roles.data ? <Empty>Loading…</Empty> : (
          <table>
            <thead><tr><th>Role</th><th>Allowed commands</th><th /></tr></thead>
            <tbody>
              {roles.data.map((r) => (
                <tr key={r.id}>
                  <td>{r.name}</td>
                  <td className="small">{r.allowed_commands.includes("*") ? "Everything" : r.allowed_commands.map((c) => COMMAND_LABELS[c] || c).join(", ")}</td>
                  <td className="actions"><button className="btn small" onClick={() => setRoleEdit(r)}>Edit</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {meta.data && (
        <Card title="What staff can send">
          <pre style={{ whiteSpace: "pre-wrap", margin: 0, fontFamily: "inherit" }}>{meta.data.staff_help}</pre>
        </Card>
      )}
      {editing && <StaffForm member={editing === "new" ? null : editing} roles={roles.data || []} onClose={() => setEditing(null)} onDone={() => { setEditing(null); void staff.reload(); }} />}
      {pinFor && <PinForm member={pinFor} onClose={() => setPinFor(null)} onDone={() => { setPinFor(null); void staff.reload(); }} />}
      {roleEdit && <RoleForm role={roleEdit === "new" ? null : roleEdit} keys={meta.data?.command_keys || Object.keys(COMMAND_LABELS)} onClose={() => setRoleEdit(null)} onDone={() => { setRoleEdit(null); void roles.reload(); }} />}
    </div>
  );
}

function StaffForm({ member, roles, onClose, onDone }: { member: StaffMember | null; roles: Role[]; onClose: () => void; onDone: () => void }) {
  const { business } = useBusiness();
  const [form, setForm] = useState({
    name: member?.name || "",
    phone: member?.phone || "",
    role_id: member?.role_id ?? roles.find((r) => r.name === "front_desk")?.id ?? "",
    receives_eod_list: member?.receives_eod_list ?? false,
    is_active: member?.is_active ?? true,
    pin: "",
  });
  const { busy, error, run } = useAction();
  async function save(e: React.FormEvent) {
    e.preventDefault();
    const body: Record<string, unknown> = {
      name: form.name,
      phone: form.phone,
      role_id: form.role_id === "" ? null : Number(form.role_id),
      receives_eod_list: form.receives_eod_list,
      is_active: form.is_active,
    };
    if (!member && form.pin) body.pin = form.pin;
    const ok = await run(() => api(bpath(business, member ? `/staff/${member.id}` : "/staff"), { method: member ? "PATCH" : "POST", body }), "Staff saved");
    if (ok) onDone();
  }
  return (
    <Modal title={member ? `Edit ${member.name}` : "Add staff member"} onClose={onClose}>
      <form onSubmit={save}>
        <ErrorBox error={error} />
        <div className="form-grid">
          <Field label="Name"><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></Field>
          <Field label="Their WhatsApp number"><input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} required placeholder="98xxxxxxxx" /></Field>
          <Field label="Role">
            <select value={form.role_id} onChange={(e) => setForm({ ...form, role_id: e.target.value === "" ? "" : Number(e.target.value) })}>
              <option value="">No role (read-only)</option>
              {roles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
            </select>
          </Field>
          {!member && <Field label="PIN (4–6 digits)"><input inputMode="numeric" pattern="\d{4,6}" value={form.pin} onChange={(e) => setForm({ ...form, pin: e.target.value })} /></Field>}
        </div>
        <div className="stack" style={{ gap: 8, marginTop: 12 }}>
          <label className="check"><input type="checkbox" checked={form.receives_eod_list} onChange={(e) => setForm({ ...form, receives_eod_list: e.target.checked })} /> Gets the end-of-day attendance list and alerts</label>
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

function PinForm({ member, onClose, onDone }: { member: StaffMember; onClose: () => void; onDone: () => void }) {
  const { business } = useBusiness();
  const [pin, setPin] = useState("");
  const { busy, error, run } = useAction();
  async function save(e: React.FormEvent) {
    e.preventDefault();
    const ok = await run(() => api(bpath(business, `/staff/${member.id}/pin`), { method: "POST", body: { pin } }), "PIN set");
    if (ok) onDone();
  }
  return (
    <Modal title={`Set PIN for ${member.name}`} onClose={onClose}>
      <form onSubmit={save}>
        <ErrorBox error={error} />
        <Field label="New PIN (4–6 digits)" hint="Share it with them privately. Setting a PIN also unlocks a locked PIN.">
          <input inputMode="numeric" autoComplete="off" pattern="\d{4,6}" value={pin} onChange={(e) => setPin(e.target.value)} required />
        </Field>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={busy}>Set PIN</button>
        </div>
      </form>
    </Modal>
  );
}

function RoleForm({ role, keys, onClose, onDone }: { role: Role | null; keys: string[]; onClose: () => void; onDone: () => void }) {
  const { business } = useBusiness();
  const [name, setName] = useState(role?.name || "");
  const [all, setAll] = useState(role?.allowed_commands.includes("*") ?? false);
  const [commands, setCommands] = useState<string[]>(role?.allowed_commands.filter((c) => c !== "*") || ["today", "help"]);
  const { busy, error, run } = useAction();
  async function save(e: React.FormEvent) {
    e.preventDefault();
    const body = { name, allowed_commands: all ? ["*"] : commands };
    const ok = await run(() => api(bpath(business, role ? `/roles/${role.id}` : "/roles"), { method: role ? "PATCH" : "POST", body }), "Role saved");
    if (ok) onDone();
  }
  return (
    <Modal title={role ? `Edit role: ${role.name}` : "New role"} onClose={onClose}>
      <form onSubmit={save}>
        <ErrorBox error={error} />
        <Field label="Name"><input value={name} onChange={(e) => setName(e.target.value)} required /></Field>
        <label className="check" style={{ margin: "12px 0" }}><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> Allow everything</label>
        {!all && (
          <div className="form-grid">
            {keys.map((k) => (
              <label key={k} className="check">
                <input type="checkbox" checked={commands.includes(k)} onChange={(e) => setCommands(e.target.checked ? [...commands, k] : commands.filter((c) => c !== k))} />
                {COMMAND_LABELS[k] || k}
              </label>
            ))}
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
