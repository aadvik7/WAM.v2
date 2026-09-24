"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { bpath, useBusiness } from "@/lib/business";
import { addDays, fmtDate } from "@/lib/format";
import { Card, Empty, ErrorBox, Tile, useLoad } from "@/components/ui";
import { useVocab } from "@/lib/vocab";

interface Report {
  date_from: string;
  date_to: string;
  visits_recovered: { booked: number; came: number };
  attendance: { done: number; missed: number; unmarked: number; no_show_rate: number | null };
  plans: { started: number; completed: number; cancelled: number; active: number; completion_rate: number | null; overdue_now: number };
  messages: {
    patient_messages: number;
    answered_without_staff: number;
    answered_by_ai: number;
    rate_without_staff: number | null;
    sent: number;
    templates_sent: number;
    failed: number;
  };
  bookings_by_source: Record<string, number>;
  daily: { date: string; done: number; missed: number; recovered: number }[];
}

function pct(v: number | null): string {
  return v === null ? "—" : `${v}%`;
}

function todayIn(tz: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}

export default function ReportsPage() {
  const { business } = useBusiness();
  const v = useVocab();
  const today = business ? todayIn(business.timezone) : "";
  const [range, setRange] = useState({ from: addDays(today, -29), to: today });
  const { data, error } = useLoad(
    () => api<Report>(bpath(business, "/reports"), { query: { date_from: range.from, date_to: range.to } }),
    [business?.id, range.from, range.to],
  );

  const preset = (days: number) => setRange({ from: addDays(today, -(days - 1)), to: today });

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Reports</h1>
          <div className="muted">{data ? `${fmtDate(data.date_from)} – ${fmtDate(data.date_to)}` : ""}</div>
        </div>
        <div className="row">
          <button className="btn small" onClick={() => preset(7)}>7 days</button>
          <button className="btn small" onClick={() => preset(30)}>30 days</button>
          <button className="btn small" onClick={() => preset(90)}>90 days</button>
          <input type="date" value={range.from} max={range.to} onChange={(e) => setRange({ ...range, from: e.target.value })} style={{ width: 150 }} aria-label="From" />
          <input type="date" value={range.to} min={range.from} onChange={(e) => setRange({ ...range, to: e.target.value })} style={{ width: 150 }} aria-label="To" />
        </div>
      </div>
      <ErrorBox error={error} />
      {!data ? (
        <Empty>Loading…</Empty>
      ) : (
        <>
          <div className="grid grid-4">
            <Tile
              label="Visits recovered"
              value={data.visits_recovered.booked}
              sub={`overdue or missed ${v.people} who rebooked via WAM · ${data.visits_recovered.came} already came`}
            />
            <Tile
              label="Plan completion rate"
              value={pct(data.plans.completion_rate)}
              sub={`${data.plans.completed} of ${data.plans.started} plans started in this period · ${data.plans.overdue_now} overdue now`}
            />
            <Tile
              label="No-show rate"
              value={pct(data.attendance.no_show_rate)}
              sub={`${data.attendance.missed} missed · ${data.attendance.done} came · ${data.attendance.unmarked} not marked`}
            />
            <Tile
              label="Answered without staff"
              value={pct(data.messages.rate_without_staff)}
              sub={`${data.messages.answered_without_staff} of ${data.messages.patient_messages} ${v.person} messages (${data.messages.answered_by_ai} by AI)`}
            />
          </div>
          <Card title="Visits per day">
            <VisitsChart daily={data.daily} />
          </Card>
          <div className="grid grid-2">
            <Card title="Bookings by source">
              {Object.keys(data.bookings_by_source).length === 0 ? (
                <Empty>No bookings in this period.</Empty>
              ) : (
                <table>
                  <tbody>
                    {Object.entries(data.bookings_by_source).map(([source, n]) => (
                      <tr key={source}>
                        <td>{source === "whatsapp" ? "WhatsApp (WAM)" : source === "admin" ? "Admin / front desk" : source}</td>
                        <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{n}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>
            <Card title="WhatsApp messages">
              <table>
                <tbody>
                  <tr><td>Messages sent</td><td style={{ textAlign: "right" }}>{data.messages.sent}</td></tr>
                  <tr><td>…of which Meta templates (billed)</td><td style={{ textAlign: "right" }}>{data.messages.templates_sent}</td></tr>
                  <tr><td>Failed sends</td><td style={{ textAlign: "right" }}>{data.messages.failed}</td></tr>
                  <tr><td>Plans stopped in this period</td><td style={{ textAlign: "right" }}>{data.plans.cancelled}</td></tr>
                </tbody>
              </table>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

// Stacked bars: came (series 1) + missed (series 2). Validated default palette, both modes.
const CHART_CSS = `
.viz-root { --series-1: #2a78d6; --series-2: #eb6834; --grid: var(--border); }
@media (prefers-color-scheme: dark) {
  .viz-root { --series-1: #3987e5; --series-2: #d95926; }
}
.viz-root .tip { position: absolute; pointer-events: none; background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 6px 9px; font-size: 12px; box-shadow: 0 4px 12px rgba(0,0,0,.12); white-space: nowrap; transform: translate(-50%, -100%); }
`;

function VisitsChart({ daily }: { daily: Report["daily"] }) {
  const [hover, setHover] = useState<number | null>(null);
  const [asTable, setAsTable] = useState(false);
  const max = Math.max(1, ...daily.map((d) => d.done + d.missed));
  const width = 900;
  const height = 180;
  const padLeft = 28;
  const padBottom = 20;
  const plotW = width - padLeft;
  const plotH = height - padBottom - 8;
  const slot = plotW / Math.max(daily.length, 1);
  const barW = Math.max(2, Math.min(28, slot - 2)); // 2px surface gap between adjacent bars
  const y = (v: number) => (v / max) * plotH;
  const ticks = [0, Math.ceil(max / 2), max].filter((v, i, a) => a.indexOf(v) === i);
  const total = daily.reduce((s, d) => s + d.done + d.missed, 0);
  const labelEvery = Math.ceil(daily.length / 10);

  if (total === 0) return <Empty>No visits marked in this period yet.</Empty>;

  return (
    <div className="viz-root" style={{ position: "relative" }}>
      <style>{CHART_CSS}</style>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 6 }}>
        <div className="legend" style={{ marginTop: 0 }}>
          <span><span className="swatch" style={{ background: "var(--series-1)" }} />Came</span>
          <span><span className="swatch" style={{ background: "var(--series-2)" }} />Missed</span>
        </div>
        <button className="btn small" onClick={() => setAsTable(!asTable)}>{asTable ? "Show chart" : "Show table"}</button>
      </div>
      {asTable ? (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Day</th><th>Came</th><th>Missed</th><th>Recovered visits</th></tr></thead>
            <tbody>
              {daily.filter((d) => d.done + d.missed + d.recovered > 0).map((d) => (
                <tr key={d.date}><td>{fmtDate(d.date)}</td><td>{d.done}</td><td>{d.missed}</td><td>{d.recovered}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <>
          <svg viewBox={`0 0 ${width} ${height}`} width="100%" role="img" aria-label={`Visits per day: ${total} marked visits`} onMouseLeave={() => setHover(null)}>
            {ticks.map((t) => (
              <g key={t}>
                <line x1={padLeft} x2={width} y1={8 + plotH - y(t)} y2={8 + plotH - y(t)} stroke="var(--grid)" strokeWidth={1} />
                <text x={padLeft - 6} y={8 + plotH - y(t) + 4} textAnchor="end" fontSize={11} fill="var(--muted)">{t}</text>
              </g>
            ))}
            {daily.map((d, i) => {
              const x = padLeft + i * slot + (slot - barW) / 2;
              const doneH = y(d.done);
              const missedH = y(d.missed);
              const base = 8 + plotH;
              const gap = d.done > 0 && d.missed > 0 ? 2 : 0; // 2px surface gap between stacked segments
              return (
                <g key={d.date}>
                  {d.done > 0 && <Segment x={x} y={base - doneH} w={barW} h={doneH} fill="var(--series-1)" roundTop={d.missed === 0} />}
                  {d.missed > 0 && <Segment x={x} y={base - doneH - missedH - gap} w={barW} h={missedH} fill="var(--series-2)" roundTop />}
                  {/* hit target: the full column, bigger than the mark */}
                  <rect x={padLeft + i * slot} y={0} width={slot} height={height} fill="transparent" onMouseEnter={() => setHover(i)} />
                  {i % labelEvery === 0 && (
                    <text x={x + barW / 2} y={height - 4} textAnchor="middle" fontSize={10} fill="var(--muted)">
                      {Number(d.date.slice(8, 10))}
                    </text>
                  )}
                </g>
              );
            })}
          </svg>
          {hover !== null && daily[hover] && (
            <div
              className="tip"
              style={{
                left: `${((padLeft + hover * slot + slot / 2) / width) * 100}%`,
                top: `${((8 + plotH - y(daily[hover].done + daily[hover].missed)) / height) * 100}%`,
              }}
            >
              <strong>{fmtDate(daily[hover].date)}</strong>
              <div>Came: {daily[hover].done}</div>
              <div>Missed: {daily[hover].missed}</div>
              {daily[hover].recovered > 0 && <div>Recovered visits: {daily[hover].recovered}</div>}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Segment({ x, y, w, h, fill, roundTop }: { x: number; y: number; w: number; h: number; fill: string; roundTop: boolean }) {
  const r = Math.min(4, w / 2, h);
  if (!roundTop || r <= 0) return <rect x={x} y={y} width={w} height={h} fill={fill} />;
  // 4px rounded data-end at the top; square at the baseline / joins
  const path = `M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h} Z`;
  return <path d={path} fill={fill} />;
}
