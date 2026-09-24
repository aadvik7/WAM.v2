"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { bpath, useBusiness } from "@/lib/business";
import { fmtDate, planProgress } from "@/lib/format";
import type { Schedule } from "@/lib/types";
import { Card, Empty, ErrorBox, StatusBadge, Tabs, useAction, useLoad } from "@/components/ui";

type View = "active" | "overdue" | "call" | "completed" | "cancelled";

export default function PlansPage() {
  const { business } = useBusiness();
  const [view, setView] = useState<View>("active");
  const query =
    view === "overdue" ? { status: "active", overdue: true }
    : view === "call" ? { status: "active", needs_staff: true }
    : { status: view };
  const { data, error, reload } = useLoad(() => api<Schedule[]>(bpath(business, "/schedules"), { query }), [business?.id, view]);
  const nudge = useAction();

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Plans</h1>
          <div className="muted">Every patient on a treatment plan or recall, and when their next visit is due.</div>
        </div>
      </div>
      <Card>
        <Tabs<View>
          value={view}
          onChange={setView}
          tabs={[
            { key: "active", label: "Active" },
            { key: "overdue", label: "Overdue" },
            { key: "call", label: "Needs a call" },
            { key: "completed", label: "Completed" },
            { key: "cancelled", label: "Stopped" },
          ]}
        />
        <ErrorBox error={error || nudge.error} />
        {!data ? <Empty>Loading…</Empty> : data.length === 0 ? <Empty>Nothing here.</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Patient</th><th>Plan</th><th>Progress</th><th>Next due</th><th>Reminders</th><th>Status</th><th /></tr></thead>
              <tbody>
                {data.map((s) => (
                  <tr key={s.id}>
                    <td><Link href={`/patients/${s.contact_id}`}>{s.contact_name || "Unknown"}</Link></td>
                    <td>{s.template}</td>
                    <td>{planProgress(s.sessions_done, s.sessions_total)}</td>
                    <td className="nowrap">{s.next_due_date ? fmtDate(s.next_due_date) : "—"} {s.overdue && <span className="badge danger">overdue</span>}</td>
                    <td>{s.nudge_count}{s.missed_count > 0 && <span className="small muted"> · {s.missed_count} missed</span>}</td>
                    <td><StatusBadge status={s.status} /> {s.needs_staff && <span className="badge warn">call</span>}</td>
                    <td className="actions">
                      {s.status === "active" && s.next_due_date && (
                        <button className="btn small" disabled={nudge.busy} onClick={() => void nudge.run(() => api(bpath(business, `/schedules/${s.id}/nudge`), { method: "POST" }), "Slots sent on WhatsApp").then(() => reload())}>
                          Send slots
                        </button>
                      )}
                    </td>
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
