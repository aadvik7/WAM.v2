"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { bpath, useBusiness } from "@/lib/business";
import { fmtDateTime } from "@/lib/format";
import type { Message } from "@/lib/types";
import { Card, Empty, ErrorBox, StatusBadge, useLoad } from "@/components/ui";
import { useVocab } from "@/lib/vocab";

export default function MessagesPage() {
  const { business } = useBusiness();
  const v = useVocab();
  const [audience, setAudience] = useState("");
  const [status, setStatus] = useState("");
  const [pages, setPages] = useState<Message[][]>([]);
  const { data, error } = useLoad(async () => {
    setPages([]);
    return api<Message[]>(bpath(business, "/messages"), { query: { audience, status, limit: 100 } });
  }, [business?.id, audience, status]);
  const all = [...(data || []), ...pages.flat()];

  async function more() {
    const last = all[all.length - 1];
    if (!last) return;
    const next = await api<Message[]>(bpath(business, "/messages"), { query: { audience, status, limit: 100, before_id: last.id } });
    setPages([...pages, next]);
  }

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Messages</h1>
          <div className="muted">Every WhatsApp message in and out (kept for the retention period set in Setup).</div>
        </div>
        <div className="row">
          <select value={audience} onChange={(e) => setAudience(e.target.value)} style={{ width: 150 }} aria-label="Audience">
            <option value="">Everyone</option>
            <option value="patient">{v.People}</option>
            <option value="staff">Staff</option>
          </select>
          <select value={status} onChange={(e) => setStatus(e.target.value)} style={{ width: 150 }} aria-label="Status">
            <option value="">Any status</option>
            <option value="failed">Failed</option>
            <option value="skipped">Skipped</option>
            <option value="dry_run">Dry run</option>
          </select>
        </div>
      </div>
      <Card>
        <ErrorBox error={error} />
        {!data ? <Empty>Loading…</Empty> : all.length === 0 ? <Empty>No messages yet.</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>When</th><th /><th>Who</th><th>Message</th><th>Handled</th><th>Status</th></tr></thead>
              <tbody>
                {all.map((m) => (
                  <tr key={m.id}>
                    <td className="nowrap small">{fmtDateTime(m.created_at)}</td>
                    <td>{m.direction === "in" ? "⬅" : "➡"}</td>
                    <td className="nowrap small">
                      {m.contact_id ? <Link href={`/patients/${m.contact_id}`}>{m.phone || v.person}</Link> : m.phone}
                      {m.audience === "staff" && <div><span className="badge info">staff</span></div>}
                    </td>
                    <td style={{ whiteSpace: "pre-wrap", maxWidth: 520 }}>
                      {m.content}
                      {m.template_name && <div className="small muted">template: {m.template_name}</div>}
                      {m.error && <div className="small" style={{ color: "var(--danger)" }}>{m.error}</div>}
                    </td>
                    <td className="small">{m.handled_by || ""}</td>
                    <td><StatusBadge status={m.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && all.length >= 100 && all.length % 100 === 0 && (
          <div className="form-actions"><button className="btn small" onClick={() => void more()}>Load older</button></div>
        )}
      </Card>
    </div>
  );
}
