"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { bpath, useBusiness } from "@/lib/business";
import { fmtDateTime } from "@/lib/format";
import type { Batch, BroadcastDetail, BroadcastSummary } from "@/lib/types";
import { Card, Confirm, Empty, ErrorBox, Field, Modal, StatusBadge, useAction, useLoad } from "@/components/ui";

const MAX = 700;
const AUDIENCE_LABEL: Record<BroadcastSummary["audience"], string> = {
  everyone: "Students and parents",
  parents: "Parents only",
  students: "Students only",
};

export default function AnnouncementsPage() {
  return (
    <Suspense fallback={<Empty>Loading…</Empty>}>
      <Announcements />
    </Suspense>
  );
}

function Announcements() {
  const { business } = useBusiness();
  const params = useSearchParams();
  const batches = useLoad(() => api<Batch[]>(bpath(business, "/institute/batches")), [business?.id]);
  const list = useLoad(() => api<BroadcastSummary[]>(bpath(business, "/institute/broadcasts")), [business?.id]);
  const [groupId, setGroupId] = useState(params.get("batch") || "");
  const [audience, setAudience] = useState<BroadcastSummary["audience"]>("everyone");
  const [message, setMessage] = useState("");
  const [draft, setDraft] = useState<BroadcastSummary | null>(null);
  const [sending, setSending] = useState<BroadcastSummary | null>(null);
  const [viewing, setViewing] = useState<number | null>(null);
  const act = useAction();

  // While anything is going out, keep the counts fresh.
  const busy = (list.data || []).some((b) => b.status === "sending");
  const reloadList = list.reload;
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(() => void reloadList(), 5000);
    return () => clearInterval(t);
  }, [busy, reloadList]);

  async function preview(e: React.FormEvent) {
    e.preventDefault();
    const b = await act.run(() =>
      api<BroadcastSummary>(bpath(business, "/institute/broadcasts"), {
        method: "POST",
        body: { group_id: Number(groupId), message, audience },
      }),
    );
    if (b) {
      setDraft(b);
      void list.reload();
    }
  }

  async function send(b: BroadcastSummary) {
    const sent = await act.run(
      () => api<BroadcastSummary>(bpath(business, `/institute/broadcasts/${b.id}/send`), { method: "POST" }),
      `Sending to ${b.recipients} people`,
    );
    setSending(null);
    if (sent) {
      if (draft?.id === b.id) {
        setDraft(null);
        setMessage("");
      }
      void list.reload();
    }
  }

  async function cancel(b: BroadcastSummary) {
    const ok = await act.run(
      () => api(bpath(business, `/institute/broadcasts/${b.id}/cancel`), { method: "POST" }),
      b.status === "draft" ? "Draft discarded" : "Sending stopped",
    );
    if (ok) {
      if (draft?.id === b.id) setDraft(null);
      void list.reload();
    }
  }

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Announcements</h1>
          <div className="muted">
            Each student and parent gets the message individually, from the institute&apos;s number, with delivery and read counts.
          </div>
        </div>
      </div>

      <div className="grid grid-2">
        <Card title="New announcement">
          {draft ? (
            <div className="stack" style={{ gap: 12 }}>
              <div className="small muted">What people will see</div>
              <div className="bubble out" style={{ maxWidth: "100%", whiteSpace: "pre-wrap" }}>{draft.preview}</div>
              <div className="small">
                <strong>{draft.recipients}</strong> people in <strong>{draft.batch}</strong>:{" "}
                {draft.counts.students ?? 0} students, {draft.counts.parents ?? 0} parents
                {draft.counts.unreachable ? <> · <span className="badge warn">{draft.counts.unreachable} students have no number</span></> : null}
              </div>
              <ErrorBox error={act.error} />
              <div className="form-actions">
                <button className="btn" onClick={() => void cancel(draft)} disabled={act.busy}>Edit</button>
                <button className="btn primary" onClick={() => setSending(draft)} disabled={act.busy}>
                  Send to {draft.recipients} people
                </button>
              </div>
            </div>
          ) : (
            <form onSubmit={preview} className="stack" style={{ gap: 10 }}>
              <ErrorBox error={act.error} />
              <Field label="Batch">
                <select value={groupId} onChange={(e) => setGroupId(e.target.value)} required>
                  <option value="">Choose a batch</option>
                  {(batches.data || []).map((b) => (
                    <option key={b.id} value={b.id}>{b.name} ({b.students} students)</option>
                  ))}
                </select>
              </Field>
              <Field label="Send to">
                <select value={audience} onChange={(e) => setAudience(e.target.value as BroadcastSummary["audience"])}>
                  {Object.entries(AUDIENCE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </Field>
              <Field label="Message" hint={`${message.length}/${MAX} · goes out as "Update for <batch>: <message>. Reply here if you have questions."`}>
                <textarea
                  value={message}
                  onChange={(e) => setMessage(e.target.value.slice(0, MAX))}
                  rows={4}
                  required
                  placeholder="Tomorrow's class is at 4 PM instead of 5 PM"
                />
              </Field>
              <div className="form-actions">
                <button className="btn primary" disabled={act.busy || !groupId || !message.trim()}>Preview</button>
              </div>
            </form>
          )}
        </Card>

        <Card title="From WhatsApp">
          <p className="small">Coordinators and teachers can send the same announcement from their own phone:</p>
          <div className="bubble in mono small">Send to NEET-A2: Tomorrow&apos;s class is at 4 PM</div>
          <p className="small muted">
            WAM replies with a preview and the number of people. Replying YES and the PIN sends it. Teachers can message only
            their own batches.
          </p>
          <p className="small muted">
            Announcements go out as a Meta-approved template with fill-in blanks, so keep them short and factual.
          </p>
        </Card>
      </div>

      <Card title="Sent announcements" actions={<button className="btn small" onClick={() => void list.reload()}>Refresh</button>}>
        <ErrorBox error={list.error} />
        {!list.data ? <Empty>Loading…</Empty> : list.data.length === 0 ? <Empty>No announcements yet.</Empty> : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>When</th><th>Batch</th><th>Message</th><th>Status</th><th>Reach</th><th /></tr>
              </thead>
              <tbody>
                {list.data.map((b) => (
                  <tr key={b.id}>
                    <td className="nowrap">{fmtDateTime(b.sent_at || b.created_at)}</td>
                    <td className="nowrap">{b.batch || "—"}</td>
                    <td style={{ maxWidth: 300 }}>
                      <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={b.message}>{b.message}</div>
                      <div className="small muted">{AUDIENCE_LABEL[b.audience]}</div>
                    </td>
                    <td><StatusBadge status={b.status} /></td>
                    <td className="nowrap">
                      {b.recipients} people
                      {b.status !== "draft" && (
                        <div className="small muted">
                          {b.delivered} delivered · {b.read} read{b.failed ? <> · <span className="badge danger">{b.failed} failed</span></> : null}
                        </div>
                      )}
                    </td>
                    <td className="actions">
                      {b.status === "draft" && (
                        <button className="btn small primary" onClick={() => setSending(b)}>Send</button>
                      )}{" "}
                      {(b.status === "draft" || b.status === "sending") && (
                        <button className="btn small" onClick={() => void cancel(b)}>{b.status === "draft" ? "Discard" : "Stop"}</button>
                      )}{" "}
                      <button className="btn small" onClick={() => setViewing(b.id)}>Details</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {sending && (
        <Confirm
          title={`Send to ${sending.recipients} people?`}
          confirmLabel="Yes, send"
          busy={act.busy}
          onConfirm={() => void send(sending)}
          onClose={() => setSending(null)}
        >
          <p>Everyone in {sending.batch} ({AUDIENCE_LABEL[sending.audience].toLowerCase()}) gets this message. It can&apos;t be unsent.</p>
          <div className="bubble out" style={{ maxWidth: "100%", whiteSpace: "pre-wrap" }}>{sending.preview}</div>
        </Confirm>
      )}
      {viewing !== null && <Detail id={viewing} onClose={() => { setViewing(null); void list.reload(); }} />}
    </div>
  );
}

function Detail({ id, onClose }: { id: number; onClose: () => void }) {
  const { business } = useBusiness();
  const detail = useLoad(() => api<BroadcastDetail>(bpath(business, `/institute/broadcasts/${id}`)), [business?.id, id]);
  const act = useAction();

  async function refresh() {
    const ok = await act.run(() => api(bpath(business, `/institute/broadcasts/${id}/refresh`), { method: "POST" }), "Read counts updated");
    if (ok) void detail.reload();
  }

  const d = detail.data;
  return (
    <Modal title="Announcement" onClose={onClose} wide>
      <ErrorBox error={detail.error || act.error} />
      {!d ? <Empty>Loading…</Empty> : (
        <div className="stack" style={{ gap: 12 }}>
          <div className="bubble out" style={{ maxWidth: "100%", whiteSpace: "pre-wrap" }}>{d.preview}</div>
          <div className="row small">
            <StatusBadge status={d.status} />
            <span>{d.sent} sent · {d.delivered} delivered · {d.read} read · {d.failed} failed</span>
            <span className="spacer" />
            {d.status !== "draft" && d.status !== "cancelled" && (
              <button className="btn small" disabled={act.busy} onClick={() => void refresh()}>Check read status</button>
            )}
          </div>
          <div className="table-wrap" style={{ maxHeight: 360, overflowY: "auto" }}>
            <table>
              <thead><tr><th>Name</th><th>Phone</th><th>Status</th></tr></thead>
              <tbody>
                {d.recipients.map((r) => (
                  <tr key={r.contact_id}>
                    <td>{r.name || "—"}</td>
                    <td className="mono small">{r.phone}</td>
                    <td>
                      <StatusBadge status={r.status} />
                      {r.error && <div className="small muted">{r.error}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Modal>
  );
}
