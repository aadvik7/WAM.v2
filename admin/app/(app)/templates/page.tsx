"use client";

import { api } from "@/lib/api";
import { Card, Empty, ErrorBox, useLoad } from "@/components/ui";

interface WaTemplate {
  key: string;
  name: string;
  pack: string;
  category: string;
  language: string;
  body: string;
  params: string[];
  example: string[];
}

export default function TemplatesPage() {
  const { data, error } = useLoad(() => api<WaTemplate[]>("/api/whatsapp-templates"), []);
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>WhatsApp templates</h1>
          <div className="muted">
            Submit these in Meta Business Manager (WhatsApp Manager → Message templates) with the exact names below, category
            Utility. WAM uses them for messages it starts outside WhatsApp&apos;s 24-hour window.
          </div>
        </div>
      </div>
      <ErrorBox error={error} />
      {!data ? <Empty>Loading…</Empty> : (
        <div className="stack">
          {data.map((t) => (
            <Card
              key={t.key}
              title={<span className="mono" style={{ fontSize: 14 }}>{t.name}</span>}
              actions={<><span className="badge">{t.category}</span><span className="badge">{t.language}</span><span className="badge accent">{t.pack}</span></>}
            >
              <p style={{ whiteSpace: "pre-wrap" }}>{t.body}</p>
              <table>
                <thead><tr><th>Variable</th><th>Meaning</th><th>Example</th></tr></thead>
                <tbody>
                  {t.params.map((p, i) => (
                    <tr key={p}><td className="mono">{`{{${i + 1}}}`}</td><td>{p}</td><td className="muted">{t.example[i]}</td></tr>
                  ))}
                </tbody>
              </table>
              <button
                className="btn small"
                style={{ marginTop: 10 }}
                onClick={() => void navigator.clipboard?.writeText(t.body)}
              >
                Copy body
              </button>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
