"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { bpath, useBusiness } from "@/lib/business";
import { addDays, fmtDate, fmtTime } from "@/lib/format";
import type { Appointment, Resource } from "@/lib/types";
import { AppointmentActions, BookModal } from "@/components/Booking";
import { Card, Empty, ErrorBox, StatusBadge, useLoad } from "@/components/ui";

function todayIn(tz: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}

export default function AppointmentsPage() {
  const { business } = useBusiness();
  const [date, setDate] = useState(() => (business ? todayIn(business.timezone) : ""));
  const [resourceId, setResourceId] = useState<number | "">("");
  const [booking, setBooking] = useState(false);
  const resources = useLoad(() => api<Resource[]>(bpath(business, "/resources")), [business?.id]);
  const { data, error, reload } = useLoad(
    () => api<Appointment[]>(bpath(business, "/appointments"), { query: { date, resource_id: resourceId || undefined } }),
    [business?.id, date, resourceId],
  );
  const now = new Date().toISOString();
  const nowLocal = business ? `${todayIn(business.timezone)}T${new Intl.DateTimeFormat("en-GB", { timeZone: business.timezone, hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date())}` : now;

  return (
    <div className="stack">
      <div className="page-head">
        <h1>Appointments</h1>
        <button className="btn primary" onClick={() => setBooking(true)}>Book appointment</button>
      </div>
      <Card>
        <div className="row" style={{ marginBottom: 12 }}>
          <button className="btn small" onClick={() => setDate(addDays(date, -1))} aria-label="Previous day">←</button>
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} style={{ width: 170 }} />
          <button className="btn small" onClick={() => setDate(addDays(date, 1))} aria-label="Next day">→</button>
          <strong>{fmtDate(date)}</strong>
          <span className="spacer" />
          <select value={resourceId} onChange={(e) => setResourceId(e.target.value ? Number(e.target.value) : "")} style={{ width: 200 }}>
            <option value="">All doctors</option>
            {resources.data?.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
        </div>
        <ErrorBox error={error} />
        {!data ? <Empty>Loading…</Empty> : data.length === 0 ? <Empty>No appointments on this day.</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Time</th><th>Patient</th><th>Visit</th><th>Doctor</th><th>Status</th><th>Source</th><th /></tr></thead>
              <tbody>
                {data.map((a) => (
                  <tr key={a.id}>
                    <td className="nowrap">{fmtTime(a.start_at)}–{fmtTime(a.end_at)}</td>
                    <td><Link href={`/patients/${a.contact_id}`}>{a.contact_name || a.contact_phone}</Link></td>
                    <td>{a.service || "—"}</td>
                    <td>{a.resource_name}</td>
                    <td>
                      <StatusBadge status={a.status} /> {a.recovered && <span className="badge accent">recovered</span>}
                      {a.reminder_sent && <div className="small muted">reminder sent</div>}
                    </td>
                    <td className="small muted">{a.source}</td>
                    <td className="actions"><AppointmentActions appt={a} now={nowLocal} onChange={() => void reload()} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {booking && <BookModal onClose={() => setBooking(false)} onDone={() => { setBooking(false); void reload(); }} />}
    </div>
  );
}
