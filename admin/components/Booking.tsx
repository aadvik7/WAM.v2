"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { bpath, useBusiness } from "@/lib/business";
import { fmtTime } from "@/lib/format";
import type { Appointment, Contact, Resource, Schedule, Slot } from "@/lib/types";
import { ErrorBox, Field, Modal, StatusBadge, useAction } from "@/components/ui";
import { useVocab } from "@/lib/vocab";

function todayIn(tz: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}

export function BookModal({
  contact,
  schedule,
  moving,
  onClose,
  onDone,
}: {
  contact?: Contact;
  schedule?: Schedule;
  moving?: Appointment;
  onClose: () => void;
  onDone: () => void;
}) {
  const { business } = useBusiness();
  const v = useVocab();
  const [resources, setResources] = useState<Resource[]>([]);
  const [resourceId, setResourceId] = useState<number | null>(schedule?.resource_id ?? moving?.resource_id ?? null);
  const [date, setDate] = useState(business ? todayIn(business.timezone) : "");
  const [slots, setSlots] = useState<Slot[] | null>(null);
  const [custom, setCustom] = useState("");
  const [picked, setPicked] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<Contact[]>([]);
  const [who, setWho] = useState<Contact | null>(contact ?? null);
  const [notify, setNotify] = useState(true);
  const { busy, error, run } = useAction();

  useEffect(() => {
    api<Resource[]>(bpath(business, "/resources")).then((rs) => {
      const active = rs.filter((r) => r.is_active);
      setResources(active);
      setResourceId((cur) => cur ?? active[0]?.id ?? null);
    });
  }, [business]);

  useEffect(() => {
    if (!resourceId || !date) return;
    setSlots(null);
    setPicked(null);
    api<Slot[]>(bpath(business, `/resources/${resourceId}/slots`), { query: { date_from: date, date_to: date } })
      .then(setSlots)
      .catch(() => setSlots([]));
  }, [business, resourceId, date]);

  useEffect(() => {
    if (who || query.trim().length < 2) {
      setMatches([]);
      return;
    }
    const t = setTimeout(() => {
      api<{ items: Contact[] }>(bpath(business, "/contacts"), { query: { q: query, page_size: 8 } }).then((r) => setMatches(r.items));
    }, 250);
    return () => clearTimeout(t);
  }, [business, query, who]);

  async function save() {
    if (!who || !resourceId) return;
    const start = custom ? `${date}T${custom}:00` : picked;
    if (!start) return;
    const result = await run(async () => {
      return api<Appointment>(bpath(business, "/appointments"), {
        method: "POST",
        body: {
          contact_id: who.id,
          resource_id: resourceId,
          start_at: start.slice(0, 19),
          schedule_id: schedule?.id ?? moving?.schedule_id ?? null,
          enforce_availability: false,
          notify,
          move_appointment_id: moving?.id ?? null,
        },
      });
    }, moving ? "Appointment moved" : "Appointment booked");
    if (result) onDone();
  }

  return (
    <Modal title={moving ? "Move appointment" : "Book appointment"} onClose={onClose}>
      <ErrorBox error={error} />
      <div className="stack" style={{ gap: 12 }}>
        {who ? (
          <div className="row">
            <strong>{who.name || who.phone}</strong>
            <span className="muted">{who.phone || who.guardian?.phone}</span>
            {!contact && <button className="btn link" onClick={() => setWho(null)}>change</button>}
          </div>
        ) : (
          <Field label={v.Person}>
            <input placeholder="Search name or phone" value={query} onChange={(e) => setQuery(e.target.value)} />
            {matches.length > 0 && (
              <div className="card" style={{ padding: 6 }}>
                {matches.map((m) => (
                  <button key={m.id} className="btn link" style={{ display: "block", padding: 4 }} onClick={() => setWho(m)}>
                    {m.name || "Unknown"} <span className="muted">{m.phone || m.guardian?.phone}</span>
                  </button>
                ))}
              </div>
            )}
          </Field>
        )}
        {schedule && <div className="small muted">For plan: {schedule.template} (visit {schedule.sessions_done + 1})</div>}
        <div className="form-grid">
          <Field label={v.Resource}>
            <select value={resourceId ?? ""} onChange={(e) => setResourceId(Number(e.target.value))}>
              {resources.map((r) => (
                <option key={r.id} value={r.id}>{r.name}</option>
              ))}
            </select>
          </Field>
          <Field label="Date">
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </Field>
        </div>
        <Field label="Free slots">
          {slots === null ? (
            <span className="muted">Loading…</span>
          ) : slots.length === 0 ? (
            <span className="muted">No free slots that day.</span>
          ) : (
            <div className="row">
              {slots.map((s) => (
                <button
                  key={s.start_at}
                  type="button"
                  className={picked === s.start_at && !custom ? "btn small primary" : "btn small"}
                  onClick={() => {
                    setPicked(s.start_at);
                    setCustom("");
                  }}
                >
                  {fmtTime(s.start_at)}
                </button>
              ))}
            </div>
          )}
        </Field>
        <Field label="Or a custom time (staff override)" hint="Can be outside working hours, but never overlaps another booking.">
          <input type="time" value={custom} onChange={(e) => setCustom(e.target.value)} />
        </Field>
        <label className="check">
          <input type="checkbox" checked={notify} onChange={(e) => setNotify(e.target.checked)} /> Send a WhatsApp confirmation
        </label>
      </div>
      <div className="form-actions">
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn primary" disabled={busy || !who || !resourceId || (!picked && !custom)} onClick={() => void save()}>
          {busy ? "Booking…" : "Book"}
        </button>
      </div>
    </Modal>
  );
}

export function AppointmentActions({ appt, onChange, now }: { appt: Appointment; onChange: () => void; now?: string }) {
  const { business } = useBusiness();
  const v = useVocab();
  const { busy, error, run } = useAction();
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [moving, setMoving] = useState(false);
  const started = now ? appt.start_at.slice(0, 16) <= now.slice(0, 16) : true;
  const active = appt.status === "booked" || appt.status === "confirmed";

  async function mark(status: "done" | "missed") {
    const ok = await run(() => api(bpath(business, `/appointments/${appt.id}/mark`), { method: "POST", body: { status } }), status === "done" ? "Marked as came" : "Marked as missed; WAM will follow up");
    if (ok) onChange();
  }

  async function cancel() {
    const ok = await run(
      () => api(bpath(business, `/appointments/${appt.id}/cancel`), { method: "POST", body: { offer_rebook: true } }),
      `Cancelled; the ${v.person} was offered new slots`,
    );
    setConfirmCancel(false);
    if (ok) onChange();
  }

  return (
    <>
      {error ? <span className="small" style={{ color: "var(--danger)" }}>{(error as Error).message} </span> : null}
      {(active || appt.status === "missed" || appt.status === "done") && started && (
        <>
          {appt.status !== "done" && <button className="btn small" disabled={busy} onClick={() => void mark("done")}>Came</button>}{" "}
          {appt.status !== "missed" && <button className="btn small" disabled={busy} onClick={() => void mark("missed")}>Missed</button>}{" "}
        </>
      )}
      {active && !started && <button className="btn small" disabled={busy} onClick={() => setMoving(true)}>Move</button>}{" "}
      {active && <button className="btn small danger" disabled={busy} onClick={() => setConfirmCancel(true)}>Cancel</button>}
      {confirmCancel && (
        <Modal title="Cancel this appointment?" onClose={() => setConfirmCancel(false)}>
          <p>
            {appt.contact_name} · <StatusBadge status={appt.status} /> · {fmtTime(appt.start_at)} with {appt.resource_name}
          </p>
          <p className="muted">WAM will message the {v.person} with 3 new slots and rebook on their reply.</p>
          <div className="form-actions">
            <button className="btn" onClick={() => setConfirmCancel(false)}>Keep it</button>
            <button className="btn danger" disabled={busy} onClick={() => void cancel()}>Yes, cancel</button>
          </div>
        </Modal>
      )}
      {moving && (
        <BookModal
          contact={{ id: appt.contact_id, name: appt.contact_name, phone: appt.contact_phone } as Contact}
          moving={appt}
          onClose={() => setMoving(false)}
          onDone={() => {
            setMoving(false);
            onChange();
          }}
        />
      )}
    </>
  );
}
