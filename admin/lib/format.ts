// Dates from WAM core are ISO strings already in the business's local time (e.g. 2026-10-05T17:00:00+05:30),
// so they are formatted from the string itself, never converted to the browser's timezone.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function fmtTime(iso: string | null | undefined): string {
  if (!iso || iso.length < 16) return "";
  const h = Number(iso.slice(11, 13));
  const m = iso.slice(14, 16);
  const suffix = h < 12 ? "AM" : "PM";
  return `${h % 12 || 12}:${m} ${suffix}`;
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const y = Number(iso.slice(0, 4));
  const mo = Number(iso.slice(5, 7));
  const d = Number(iso.slice(8, 10));
  const day = new Date(Date.UTC(y, mo - 1, d)).getUTCDay();
  return `${DAYS[day]} ${d} ${MONTHS[mo - 1]}`;
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  return `${fmtDate(iso)}, ${fmtTime(iso)}`;
}

export function isoDate(iso: string | null | undefined): string {
  return iso ? iso.slice(0, 10) : "";
}

export function addDays(date: string, n: number): string {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export function planProgress(done: number, total: number | null): string {
  return total ? `${done} of ${total}` : `${done} done (ongoing)`;
}

export function cls(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}
