"use client";

import { api } from "@/lib/api";
import { bpath, useBusiness } from "@/lib/business";
import { fmtDateTime } from "@/lib/format";
import { Card, Empty, ErrorBox, useLoad } from "@/components/ui";

interface AuditRow {
  id: number;
  action: string;
  staff_id: number | null;
  admin_user_id: number | null;
  phone: string | null;
  details: Record<string, unknown>;
  created_at: string;
}

export default function AuditPage() {
  const { business } = useBusiness();
  const { data, error } = useLoad(() => api<AuditRow[]>(bpath(business, "/audit"), { query: { limit: 300 } }), [business?.id]);
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Audit log</h1>
          <div className="muted">Who did what, when, and from which phone.</div>
        </div>
      </div>
      <Card>
        <ErrorBox error={error} />
        {!data ? <Empty>Loading…</Empty> : data.length === 0 ? <Empty>Nothing yet.</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>When</th><th>Action</th><th>By</th><th>Details</th></tr></thead>
              <tbody>
                {data.map((r) => (
                  <tr key={r.id}>
                    <td className="nowrap small">{fmtDateTime(r.created_at)}</td>
                    <td><span className="badge">{r.action.replaceAll("_", " ")}</span></td>
                    <td className="small">{r.phone ? `WhatsApp ${r.phone}` : r.admin_user_id ? `admin #${r.admin_user_id}` : "system"}</td>
                    <td className="mono" style={{ whiteSpace: "pre-wrap", maxWidth: 560 }}>{Object.keys(r.details).length ? JSON.stringify(r.details) : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
