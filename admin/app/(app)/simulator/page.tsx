"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { bpath, useBusiness } from "@/lib/business";
import { fmtTime } from "@/lib/format";
import type { Message, StaffMember } from "@/lib/types";
import { Card, ErrorBox, Field, toast, useAction } from "@/components/ui";

const PATIENT_EXAMPLES = ["Hi", "What are your timings?", "What is the fee?", "I want to book an appointment", "2", "Can I come Thursday evening instead?", "My tooth is bleeding heavily", "STOP"];
const STAFF_EXAMPLES = ["Today's list", "Rahul 9811111111, root canal", "Cancel my 5 pm", "YES 1234", "Running 20 min late", "On leave Friday", "Follow-up for Rahul in 7 days", "Summary", "help"];

export default function SimulatorPage() {
  const { business } = useBusiness();
  const [phone, setPhone] = useState("9811111111");
  const [name, setName] = useState("Test Patient");
  const [text, setText] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [staff, setStaff] = useState<StaffMember[]>([]);
  const send = useAction();
  const tick = useAction();
  const chatRef = useRef<HTMLDivElement>(null);

  async function load() {
    if (!phone) return;
    const rows = await api<Message[]>(bpath(business, "/simulator/conversation"), { query: { phone } }).catch(() => []);
    setMessages(rows);
  }

  useEffect(() => {
    void api<StaffMember[]>(bpath(business, "/staff")).then(setStaff).catch(() => undefined);
  }, [business]);

  useEffect(() => {
    const t = setTimeout(() => void load(), 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phone, business?.id]);

  useEffect(() => {
    chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight });
  }, [messages]);

  async function submit(e?: React.FormEvent, override?: string) {
    e?.preventDefault();
    const body = (override ?? text).trim();
    if (!body) return;
    const ok = await send.run(() => api(bpath(business, "/simulator/message"), { method: "POST", body: { phone, name: name || null, text: body } }));
    if (ok) {
      setText("");
      await load();
    }
  }

  async function runTick() {
    const r = await tick.run(() => api<Record<string, unknown>>(bpath(business, "/simulator/tick"), { method: "POST" }));
    if (r) {
      toast(`Scheduler ran: ${JSON.stringify(r)}`);
      await load();
    }
  }

  const isStaff = staff.some((s) => s.phone.replace(/\D/g, "").endsWith(phone.replace(/\D/g, "").slice(-10)));

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Simulator</h1>
          <div className="muted">Chat with WAM as a patient or a staff member, without WhatsApp. Messages are real: bookings and plans are saved.</div>
        </div>
        <button className="btn" disabled={tick.busy} onClick={() => void runTick()}>Run scheduler now</button>
      </div>
      <ErrorBox error={send.error || tick.error} />
      <div className="grid grid-2" style={{ gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)" }}>
        <Card title={isStaff ? "Chatting as staff" : "Chatting as a patient"}>
          <div className="chat" ref={chatRef} style={{ minHeight: 360 }}>
            {messages.length === 0 && <div className="empty">Say hi to start.</div>}
            {messages.map((m) => (
              // From the sender's point of view: their messages on the right.
              <div key={m.id} className={`bubble ${m.direction === "in" ? "out" : "in"}`}>
                {m.content}
                <div className="meta">
                  {fmtTime(m.created_at)}
                  {m.template_name && ` · ${m.template_name}`}
                  {m.direction === "in" && m.handled_by && ` · ${m.handled_by}`}
                  {m.status === "skipped" && ` · not sent: ${m.error}`}
                </div>
              </div>
            ))}
          </div>
          <form onSubmit={(e) => void submit(e)} className="row" style={{ marginTop: 10, flexWrap: "nowrap" }}>
            <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Type a message…" aria-label="Message" />
            <button className="btn primary" disabled={send.busy || !text.trim()}>{send.busy ? "…" : "Send"}</button>
          </form>
        </Card>
        <div className="stack">
          <Card title="Sender">
            <div className="stack" style={{ gap: 10 }}>
              <Field label="WhatsApp number" hint="Use a staff member's number to test staff commands.">
                <input value={phone} onChange={(e) => setPhone(e.target.value)} />
              </Field>
              <Field label="Profile name"><input value={name} onChange={(e) => setName(e.target.value)} /></Field>
              {staff.length > 0 && (
                <div className="row">
                  {staff.slice(0, 4).map((s) => (
                    <button key={s.id} className="btn small" onClick={() => setPhone(s.phone)}>{s.name}</button>
                  ))}
                </div>
              )}
            </div>
          </Card>
          <Card title="Try">
            <div className="row">
              {(isStaff ? STAFF_EXAMPLES : PATIENT_EXAMPLES).map((ex) => (
                <button key={ex} className="btn small" disabled={send.busy} onClick={() => void submit(undefined, ex)}>{ex}</button>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
