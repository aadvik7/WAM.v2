"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { bpath, useBusiness } from "@/lib/business";
import { fmtDate, fmtTime, inr, planProgress } from "@/lib/format";
import type { Appointment, Contact, Schedule } from "@/lib/types";
import { AppointmentActions, BookModal } from "@/components/Booking";
import { Card, Empty, ErrorBox, StatusBadge, Tile, useAction, useLoad } from "@/components/ui";
import { useVocab } from "@/lib/vocab";

interface Today {
  date: string;
  now: string;
  appointments: Appointment[];
  counts: Record<string, number>;
  needs_staff: Contact[];
  due_unbooked: Schedule[];
  fees_due?: Schedule[];
}

export default function TodayPage() {
  const { business } = useBusiness();
  const v = useVocab();
  const { data, error, loading, reload } = useLoad(() => api<Today>(bpath(business, "/today")), [business?.id]);
  const [booking, setBooking] = useState(false);
  const nudge = useAction();

  const counts = data?.counts ?? {};
  const total = data ? data.appointments.length : 0;
  const unmarked = data
    ? data.appointments.filter((a) => (a.status === "booked" || a.status === "confirmed") && a.start_at.slice(0, 16) <= data.now.slice(0, 16)).length
    : 0;

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Today</h1>
          <div className="muted">{data ? fmtDate(data.date) : ""} · {business?.name}</div>
        </div>
        <div className="row">
          <button className="btn" onClick={() => void reload()} disabled={loading}>Refresh</button>
          <button className="btn primary" onClick={() => setBooking(true)}>Book appointment</button>
        </div>
      </div>
      <ErrorBox error={error} />
      <div className="grid grid-4">
        <Tile label="Appointments" value={total} sub={`${counts.confirmed ?? 0} confirmed`} />
        <Tile label="Came" value={counts.done ?? 0} />
        <Tile label="Missed" value={counts.missed ?? 0} sub="WAM follows up after 24h" />
        <Tile label="To mark" value={unmarked} sub="visit time passed" />
      </div>

      <Card title="Today's list">
        {!data ? (
          <Empty>Loading…</Empty>
        ) : data.appointments.length === 0 ? (
          <Empty>No appointments today.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Time</th><th>{v.Person}</th><th>{v.Visit}</th><th>{v.Resource}</th><th>Status</th><th /></tr>
              </thead>
              <tbody>
                {data.appointments.map((a) => (
                  <tr key={a.id}>
                    <td className="nowrap">{fmtTime(a.start_at)}</td>
                    <td>
                      <Link href={`/patients/${a.contact_id}`}>{a.contact_name || a.contact_phone}</Link>
                      {a.recovered && <> <span className="badge accent" title={`Overdue or missed ${v.person} who rebooked through WAM`}>recovered</span></>}
                    </td>
                    <td>{a.service || "—"}</td>
                    <td>{a.resource_name}</td>
                    <td><StatusBadge status={a.status} /></td>
                    <td className="actions"><AppointmentActions appt={a} now={data.now} onChange={() => void reload()} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="grid grid-2">
        <Card title={`Due, not booked (${data?.due_unbooked.length ?? 0})`}>
          <ErrorBox error={nudge.error} />
          {!data || data.due_unbooked.length === 0 ? (
            <Empty>Everyone who is due has a booking.</Empty>
          ) : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>{v.Person}</th><th>Plan</th><th>Due</th><th>Nudges</th><th /></tr></thead>
                <tbody>
                  {data.due_unbooked.map((s) => (
                    <tr key={s.id}>
                      <td><Link href={`/patients/${s.contact_id}`}>{s.contact_name || "Unknown"}</Link></td>
                      <td>{s.template}<div className="small muted">{planProgress(s.sessions_done, s.sessions_total, s.kind)}</div></td>
                      <td className="nowrap">{fmtDate(s.next_due_date)} {s.overdue && <span className="badge danger">overdue</span>}</td>
                      <td>{s.nudge_count}{s.needs_staff && <> <span className="badge warn">call</span></>}</td>
                      <td className="actions">
                        <button
                          className="btn small"
                          disabled={nudge.busy}
                          onClick={() => void nudge.run(() => api(bpath(business, `/schedules/${s.id}/nudge`), { method: "POST" }), "Slots sent on WhatsApp").then(() => reload())}
                        >
                          Send slots
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        <Card title={`Needs a person (${data?.needs_staff.length ?? 0})`}>
          {!data || data.needs_staff.length === 0 ? (
            <Empty>No chats waiting for staff.</Empty>
          ) : (
            <table>
              <tbody>
                {data.needs_staff.map((c) => (
                  <tr key={c.id}>
                    <td><Link href={`/patients/${c.id}`}>{c.name || c.phone}</Link><div className="small muted">{c.phone || c.guardian?.phone}</div></td>
                    <td className="actions">
                      <button
                        className="btn small"
                        onClick={() => void api(bpath(business, `/contacts/${c.id}`), { method: "PATCH", body: { needs_staff: false } }).then(() => reload())}
                      >
                        Mark handled
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="small muted" style={{ marginTop: 10 }}>Reply to these {v.people} from the WAM inbox (Chatwoot).</p>
        </Card>
      </div>
      {data?.fees_due && data.fees_due.length > 0 && (
        <Card title={`Fees due (${data.fees_due.length})`}>
          <p className="small muted" style={{ marginTop: 0 }}>WAM reminds families before and on the due date. Record a payment when it comes in.</p>
          <div className="table-wrap">
            <table>
              <thead><tr><th>{v.Person}</th><th>Plan</th><th>Due</th><th>Reminders</th><th /></tr></thead>
              <tbody>
                {data.fees_due.map((s) => (
                  <tr key={s.id}>
                    <td><Link href={`/patients/${s.contact_id}`}>{s.contact_name || "Unknown"}</Link></td>
                    <td>{s.template}{s.amount ? ` · ${inr(s.amount)}` : ""}<div className="small muted">{planProgress(s.sessions_done, s.sessions_total, s.kind)}</div></td>
                    <td className="nowrap">{fmtDate(s.next_due_date)} {s.overdue && <span className="badge danger">overdue</span>}</td>
                    <td>{s.nudge_count}{s.needs_staff && <> <span className="badge warn">call</span></>}</td>
                    <td className="actions">
                      <button
                        className="btn small primary"
                        disabled={nudge.busy}
                        onClick={() => void nudge.run(() => api(bpath(business, `/schedules/${s.id}/payment`), { method: "POST" }), "Payment recorded").then(() => reload())}
                      >
                        Record payment
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      {booking && <BookModal onClose={() => setBooking(false)} onDone={() => { setBooking(false); void reload(); }} />}
    </div>
  );
}
