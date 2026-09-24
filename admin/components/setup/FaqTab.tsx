"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { bpath, useBusiness } from "@/lib/business";
import type { Faq } from "@/lib/types";
import { Card, Empty, ErrorBox, Field, Modal, useAction, useLoad } from "@/components/ui";

const SUGGESTIONS = [
  { question: "What is the consultation fee?", keywords: "fee, fees, cost, price, charges, consultation" },
  { question: "Do you accept cards and UPI?", keywords: "upi, card, payment, pay, gpay, paytm, cash" },
  { question: "When will my reports be ready?", keywords: "report, reports, x-ray, xray, results" },
  { question: "Is there parking?", keywords: "parking, park, car" },
  { question: "Do you accept insurance?", keywords: "insurance, cashless, mediclaim, tpa" },
];

export function FaqTab() {
  const { business } = useBusiness();
  const { data, error, reload } = useLoad(() => api<Faq[]>(bpath(business, "/faqs")), [business?.id]);
  const [editing, setEditing] = useState<Partial<Faq> | null>(null);
  const del = useAction();
  const existing = new Set(data?.map((f) => f.question.toLowerCase()));

  return (
    <div className="stack">
      <Card title="FAQ" actions={<button className="btn primary small" onClick={() => setEditing({})}>Add question</button>}>
        <p className="muted small">
          WAM answers fees, reports, payment and similar questions only from these answers (plus your hours and address). It never
          gives medical advice. Keywords help match the way patients ask, e.g. &quot;kitna fees&quot;.
        </p>
        <ErrorBox error={error || del.error} />
        {!data ? <Empty>Loading…</Empty> : data.length === 0 ? <Empty>No questions yet — start with the suggestions below.</Empty> : (
          <table>
            <thead><tr><th>Question</th><th>Answer</th><th>Keywords</th><th /></tr></thead>
            <tbody>
              {data.map((f) => (
                <tr key={f.id}>
                  <td>{f.question}</td>
                  <td style={{ whiteSpace: "pre-wrap" }}>{f.answer}</td>
                  <td className="small">{f.keywords.join(", ")}</td>
                  <td className="actions">
                    <button className="btn small" onClick={() => setEditing(f)}>Edit</button>{" "}
                    <button className="btn small danger" onClick={() => void del.run(async () => { await api(bpath(business, `/faqs/${f.id}`), { method: "DELETE" }); return true; }, "Deleted").then(() => reload())}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      <Card title="Suggested questions">
        <div className="row">
          {SUGGESTIONS.filter((s) => !existing.has(s.question.toLowerCase())).map((s) => (
            <button key={s.question} className="btn small" onClick={() => setEditing({ question: s.question, answer: "", keywords: s.keywords.split(", ") })}>
              + {s.question}
            </button>
          ))}
        </div>
      </Card>
      {editing && <FaqForm faq={editing} onClose={() => setEditing(null)} onDone={() => { setEditing(null); void reload(); }} />}
    </div>
  );
}

function FaqForm({ faq, onClose, onDone }: { faq: Partial<Faq>; onClose: () => void; onDone: () => void }) {
  const { business } = useBusiness();
  const [question, setQuestion] = useState(faq.question || "");
  const [answer, setAnswer] = useState(faq.answer || "");
  const [keywords, setKeywords] = useState((faq.keywords || []).join(", "));
  const { busy, error, run } = useAction();
  async function save(e: React.FormEvent) {
    e.preventDefault();
    const body = { question, answer, keywords: keywords.split(",").map((k) => k.trim()).filter(Boolean) };
    const ok = await run(() => api(bpath(business, faq.id ? `/faqs/${faq.id}` : "/faqs"), { method: faq.id ? "PATCH" : "POST", body }), "Saved");
    if (ok) onDone();
  }
  return (
    <Modal title={faq.id ? "Edit question" : "Add question"} onClose={onClose}>
      <form onSubmit={save}>
        <ErrorBox error={error} />
        <div className="stack" style={{ gap: 12 }}>
          <Field label="Question"><input value={question} onChange={(e) => setQuestion(e.target.value)} required /></Field>
          <Field label="Answer (sent as-is on WhatsApp)"><textarea value={answer} onChange={(e) => setAnswer(e.target.value)} required rows={4} /></Field>
          <Field label="Keywords (comma separated)"><input value={keywords} onChange={(e) => setKeywords(e.target.value)} /></Field>
        </div>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={busy}>Save</button>
        </div>
      </form>
    </Modal>
  );
}
