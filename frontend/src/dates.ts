/**
 * Tracking dates are calendar days, not instants.  They are sent as UTC
 * midnight and read back by their first ten characters, because SQLite returns
 * them without a zone and `new Date()` would then shift them by the local offset.
 */

/** "2026-10-01T00:00:00" -> "2026-10-01"; null stays null. */
export function toDay(value: string | null | undefined): string | null {
  return value ? value.slice(0, 10) : null;
}

/** "2026-10-01" -> the payload the API expects; "" clears the date. */
export function fromDay(day: string): string | null {
  return day ? `${day}T00:00:00Z` : null;
}

export function today(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

export function addDays(days: number, from: string = today()): string {
  const [year, month, day] = from.split("-").map(Number);
  const date = new Date(year, month - 1, day + days);
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${mm}-${dd}`;
}

/** Due today or earlier. */
export function isDue(value: string | null | undefined): boolean {
  const day = toDay(value);
  return day !== null && day <= today();
}

export function formatDay(value: string | null | undefined): string {
  const day = toDay(value);
  if (!day) return "";
  const [year, month, date] = day.split("-").map(Number);
  return new Date(year, month - 1, date).toLocaleDateString();
}

/** A stored UTC timestamp, which SQLite returns without its zone, in local time. */
export function formatInstant(value: string): string {
  const zoned = /Z$|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`;
  return new Date(zoned).toLocaleString();
}

/** Days since a date, for "applied 12 days ago". */
export function daysSince(value: string | null | undefined): number | null {
  const day = toDay(value);
  if (!day) return null;
  const [year, month, date] = day.split("-").map(Number);
  const then = new Date(year, month - 1, date).getTime();
  const [ty, tm, td] = today().split("-").map(Number);
  return Math.round((new Date(ty, tm - 1, td).getTime() - then) / 86_400_000);
}
