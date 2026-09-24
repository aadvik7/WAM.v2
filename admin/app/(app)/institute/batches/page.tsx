"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { bpath, useBusiness } from "@/lib/business";
import type { Batch } from "@/lib/types";
import { Card, Empty, ErrorBox, useAction, useLoad } from "@/components/ui";

export default function BatchesPage() {
  const { business } = useBusiness();
  const { data, error, reload } = useLoad(() => api<Batch[]>(bpath(business, "/institute/batches")), [business?.id]);
  const [name, setName] = useState("");
  const create = useAction();

  async function add(e: React.FormEvent) {
    e.preventDefault();
    const ok = await create.run(() => api(bpath(business, "/institute/batches"), { method: "POST", body: { name } }), "Batch created");
    if (ok) {
      setName("");
      void reload();
    }
  }

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Batches</h1>
          <div className="muted">Each student is linked to 1–2 parent numbers. Teachers can message only their own batches.</div>
        </div>
        <Link className="btn" href="/institute/uploads">Import students from Excel</Link>
      </div>
      <div className="grid grid-wide">
        <Card title="All batches">
          <ErrorBox error={error} />
          {!data ? <Empty>Loading…</Empty> : data.length === 0 ? <Empty>No batches yet. Add one, or import a student list.</Empty> : (
            <table>
              <thead><tr><th>Batch</th><th>Students</th><th>Teachers</th><th /></tr></thead>
              <tbody>
                {data.map((b) => (
                  <tr key={b.id}>
                    <td><Link href={`/institute/batches/${b.id}`}>{b.name}</Link></td>
                    <td>{b.students}</td>
                    <td>{b.teachers || <span className="badge warn">none</span>}</td>
                    <td className="actions">
                      <Link className="btn small" href={`/institute/announcements?batch=${b.id}`}>Announce</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card title="New batch">
          <form onSubmit={add} className="stack" style={{ gap: 10 }}>
            <ErrorBox error={create.error} />
            <input placeholder="e.g. NEET-A2" value={name} onChange={(e) => setName(e.target.value)} required aria-label="Batch name" />
            <div className="form-actions"><button className="btn primary" disabled={create.busy}>Create batch</button></div>
          </form>
        </Card>
      </div>
    </div>
  );
}
