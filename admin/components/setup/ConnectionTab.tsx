"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useBusiness } from "@/lib/business";
import { Card, ErrorBox, Field, useAction, useLoad } from "@/components/ui";
import { useVocab } from "@/lib/vocab";

interface Health {
  status: string;
  checks: Record<string, string | number | null>;
}

export function ConnectionTab() {
  const { business, reload } = useBusiness();
  const v = useVocab();
  const [form, setForm] = useState({ chatwoot_account_id: "", chatwoot_inbox_id: "", chatwoot_api_token: "", chatwoot_bot_token: "", chatwoot_webhook_secret: "" });
  const { busy, error, run } = useAction();
  // /health answers 503 with details when something is wrong, so read the body either way.
  const health = useLoad(
    () =>
      fetch("/api/core/health", { cache: "no-store" })
        .then((r) => r.json() as Promise<Health>)
        .catch((e: Error) => ({ status: "error", checks: { error: e.message } }) as Health),
    [],
  );

  useEffect(() => {
    if (!business) return;
    setForm({
      chatwoot_account_id: business.chatwoot_account_id?.toString() || "",
      chatwoot_inbox_id: business.chatwoot_inbox_id?.toString() || "",
      chatwoot_api_token: "",
      chatwoot_bot_token: "",
      chatwoot_webhook_secret: "",
    });
  }, [business]);

  if (!business) return null;

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const body: Record<string, unknown> = {
      chatwoot_account_id: form.chatwoot_account_id ? Number(form.chatwoot_account_id) : null,
      chatwoot_inbox_id: form.chatwoot_inbox_id ? Number(form.chatwoot_inbox_id) : null,
    };
    if (form.chatwoot_api_token) body.chatwoot_api_token = form.chatwoot_api_token;
    if (form.chatwoot_bot_token) body.chatwoot_bot_token = form.chatwoot_bot_token;
    if (form.chatwoot_webhook_secret) body.chatwoot_webhook_secret = form.chatwoot_webhook_secret;
    const ok = await run(() => api(`/api/businesses/${business!.id}`, { method: "PATCH", body }), "Connection saved");
    if (ok) await reload();
  }

  return (
    <div className="stack">
      <Card title="WhatsApp inbox (Chatwoot)">
        <p className="muted small">
          WAM sends and receives WhatsApp messages through the WAM inbox (Chatwoot), so every conversation stays in one place and staff
          can reply by hand. Find the account and inbox IDs in the inbox URL, e.g. <span className="mono">/app/accounts/1/inbox/5</span>.
          Tokens are write-only here: they are saved on the WAM server and never shown again.
        </p>
        <form onSubmit={save}>
          <ErrorBox error={error} />
          <div className="form-grid">
            <Field label="Chatwoot account ID"><input inputMode="numeric" value={form.chatwoot_account_id} onChange={(e) => setForm({ ...form, chatwoot_account_id: e.target.value })} /></Field>
            <Field label="WhatsApp inbox ID"><input inputMode="numeric" value={form.chatwoot_inbox_id} onChange={(e) => setForm({ ...form, chatwoot_inbox_id: e.target.value })} /></Field>
            <Field label="Admin access token" hint={business.chatwoot_api_token_set ? "Set — leave blank to keep" : "Profile → Access token of an admin agent (optional if set on the server)"}>
              <input type="password" autoComplete="off" value={form.chatwoot_api_token} onChange={(e) => setForm({ ...form, chatwoot_api_token: e.target.value })} />
            </Field>
            <Field label="Agent bot token" hint={business.chatwoot_bot_token_set ? "Set — leave blank to keep" : "Settings → Bots → WAM (optional)"}>
              <input type="password" autoComplete="off" value={form.chatwoot_bot_token} onChange={(e) => setForm({ ...form, chatwoot_bot_token: e.target.value })} />
            </Field>
            <Field label="Agent bot webhook secret" hint={business.chatwoot_webhook_secret_set ? "Set — signatures are checked. Leave blank to keep" : "Optional: WAM then rejects unsigned webhooks"}>
              <input type="password" autoComplete="off" value={form.chatwoot_webhook_secret} onChange={(e) => setForm({ ...form, chatwoot_webhook_secret: e.target.value })} />
            </Field>
          </div>
          <div className="form-actions"><button className="btn primary" disabled={busy}>Save connection</button></div>
        </form>
      </Card>
      <Card title="Checklist">
        <ol style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 6 }}>
          <li>Connect your verified WhatsApp Business number as a WhatsApp inbox in Chatwoot (WhatsApp Cloud API).</li>
          <li>Create an agent bot in Chatwoot with the webhook URL <span className="mono">https://&lt;core-host&gt;/webhooks/chatwoot/&lt;WEBHOOK_SECRET&gt;</span> and attach it to the inbox.</li>
          <li>Enter the account ID, inbox ID and tokens above.</li>
          <li>Submit the templates on the <a href="/templates">WhatsApp templates</a> page to Meta and wait for approval.</li>
          <li>Send &quot;hi&quot; to the {v.org} number from your phone — WAM should answer within seconds.</li>
        </ol>
      </Card>
      <Card title="System health" actions={<button className="btn small" onClick={() => void health.reload()}>Check again</button>}>
        {health.data && (
          <>
            <p>
              Status: <span className={`badge ${health.data.status === "ok" ? "ok" : "danger"}`}>{health.data.status}</span>
            </p>
            <table>
              <tbody>
                {Object.entries(health.data.checks).map(([k, v]) => (
                  <tr key={k}><td>{k.replaceAll("_", " ")}</td><td className="mono">{v === null ? "—" : String(v)}</td></tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </Card>
    </div>
  );
}
