"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { bpath, useBusiness } from "@/lib/business";
import { fmtDateTime } from "@/lib/format";
import type { Doubt, Subject } from "@/lib/types";
import { Card, Confirm, Empty, ErrorBox, Field, Modal, StatusBadge, Tabs, useAction, useLoad } from "@/components/ui";

type Filter = "open" | "closed" | "all";

export default function DoubtsPage() {
  const { business } = useBusiness();
  const [filter, setFilter] = useState<Filter>("open");
  const doubts = useLoad(() => api<Doubt[]>(bpath(business, "/institute/doubts"), { query: { status: filter } }), [business?.id, filter]);
  const subjects = useLoad(() => api<Subject[]>(bpath(business, "/institute/subjects")), [business?.id]);
  const [editing, setEditing] = useState<Subject | "new" | null>(null);
  const [removing, setRemoving] = useState<Subject | null>(null);
  const act = useAction();

  async function close(d: Doubt) {
    const ok = await act.run(() => api(bpath(business, `/institute/doubts/${d.id}/close`), { method: "POST" }), "Doubt closed");
    if (ok) void doubts.reload();
  }

  async function removeSubject(s: Subject) {
    const ok = await act.run(async () => {
      await api(bpath(business, `/institute/subjects/${s.id}`), { method: "DELETE" });
      return true;
    }, `${s.name} removed`);
    setRemoving(null);
    if (ok) void subjects.reload();
  }

  const noTeams = (subjects.data || []).filter((s) => !s.chatwoot_team_id).length;

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Doubt queue</h1>
          <div className="muted">
            A student sends “Doubt: …” on WhatsApp. WAM works out the subject and hands the chat to that subject&apos;s teachers in the inbox.
          </div>
        </div>
      </div>
      <ErrorBox error={act.error} />

      <Card title="Doubts" actions={<button className="btn small" onClick={() => void doubts.reload()}>Refresh</button>}>
        <Tabs
          tabs={[{ key: "open", label: "Open" }, { key: "closed", label: "Closed" }, { key: "all", label: "All" }]}
          value={filter}
          onChange={setFilter}
        />
        <ErrorBox error={doubts.error} />
        {!doubts.data ? <Empty>Loading…</Empty> : doubts.data.length === 0 ? (
          <Empty>{filter === "open" ? "No open doubts. Teachers answer them from the inbox." : "Nothing here."}</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Asked</th><th>Student</th><th>Batch</th><th>Subject</th><th>Doubt</th><th>Status</th><th /></tr></thead>
              <tbody>
                {doubts.data.map((d) => (
                  <tr key={d.id}>
                    <td className="nowrap">{fmtDateTime(d.created_at)}</td>
                    <td><Link href={`/patients/${d.contact_id}`}>{d.student || "—"}</Link></td>
                    <td>{d.batch || "—"}</td>
                    <td>{d.subject || <span className="badge warn">not sure</span>}</td>
                    <td style={{ maxWidth: 360, whiteSpace: "pre-wrap" }}>{d.question}</td>
                    <td><StatusBadge status={d.status} /></td>
                    <td className="actions">
                      {d.status === "open" && <button className="btn small" disabled={act.busy} onClick={() => void close(d)}>Mark answered</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="small muted" style={{ marginBottom: 0 }}>A doubt also closes on its own when the teacher resolves the conversation in the inbox.</p>
      </Card>

      <Card title="Subjects and teacher teams" actions={<button className="btn small primary" onClick={() => setEditing("new")}>Add subject</button>}>
        <p className="small">
          In the inbox, create a team for each subject (Settings → Teams), add that subject&apos;s teachers, and enter the team&apos;s number here. Its
          number is at the end of the team&apos;s address, e.g. <span className="mono">…/settings/teams/<strong>3</strong>/edit</span>.
        </p>
        {noTeams > 0 && <div className="alert info small">{noTeams} subject{noTeams === 1 ? " has" : "s have"} no team yet; those doubts go to the general inbox.</div>}
        <ErrorBox error={subjects.error} />
        {!subjects.data ? <Empty>Loading…</Empty> : subjects.data.length === 0 ? <Empty>No subjects yet. Add Physics, Chemistry, Biology…</Empty> : (
          <table>
            <thead><tr><th>Subject</th><th>Other words students use</th><th>Inbox team</th><th /></tr></thead>
            <tbody>
              {subjects.data.map((s) => (
                <tr key={s.id}>
                  <td>{s.name}</td>
                  <td className="small">{s.aliases.join(", ") || "—"}</td>
                  <td>{s.chatwoot_team_id ? `Team ${s.chatwoot_team_id}` : <span className="badge warn">none</span>}</td>
                  <td className="actions">
                    <button className="btn small" onClick={() => setEditing(s)}>Edit</button>{" "}
                    <button className="btn small danger" onClick={() => setRemoving(s)}>Remove</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {editing && (
        <SubjectForm
          subject={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onDone={() => { setEditing(null); void subjects.reload(); }}
        />
      )}
      {removing && (
        <Confirm title={`Remove ${removing.name}?`} confirmLabel="Remove" danger busy={act.busy} onConfirm={() => void removeSubject(removing)} onClose={() => setRemoving(null)}>
          <p>New {removing.name} doubts will go to the general inbox. Past doubts stay in the list.</p>
        </Confirm>
      )}
    </div>
  );
}

function SubjectForm({ subject, onClose, onDone }: { subject: Subject | null; onClose: () => void; onDone: () => void }) {
  const { business } = useBusiness();
  const [name, setName] = useState(subject?.name || "");
  const [aliases, setAliases] = useState(subject?.aliases.join(", ") || "");
  const [team, setTeam] = useState(subject?.chatwoot_team_id ? String(subject.chatwoot_team_id) : "");
  const { run, busy, error } = useAction();

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const body = {
      name,
      aliases: aliases.split(",").map((a) => a.trim()).filter(Boolean),
      chatwoot_team_id: team ? Number(team) : null,
    };
    const ok = await run(
      () => api(bpath(business, subject ? `/institute/subjects/${subject.id}` : "/institute/subjects"), { method: subject ? "PATCH" : "POST", body }),
      "Subject saved",
    );
    if (ok) onDone();
  }

  return (
    <Modal title={subject ? `Edit ${subject.name}` : "Add subject"} onClose={onClose}>
      <form onSubmit={save} className="stack" style={{ gap: 10 }}>
        <ErrorBox error={error} />
        <Field label="Subject">
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Physics" required maxLength={80} />
        </Field>
        <Field label="Other words students use" hint="Comma-separated, e.g. phy, phys, mechanics">
          <input value={aliases} onChange={(e) => setAliases(e.target.value)} />
        </Field>
        <Field label="Inbox team number" hint="Leave empty to send these doubts to the general inbox">
          <input type="number" min={1} value={team} onChange={(e) => setTeam(e.target.value)} />
        </Field>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={busy}>Save</button>
        </div>
      </form>
    </Modal>
  );
}
