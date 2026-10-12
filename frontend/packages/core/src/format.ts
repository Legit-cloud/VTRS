/** Thousands separators without Intl, so the output is identical on every JS engine. */
export function formatNumber(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "–";
  const rounded = Math.round(value);
  const sign = rounded < 0 ? "-" : "";
  return sign + String(Math.abs(rounded)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/** One decimal under 100 (`94.3%`), whole number at 100. */
export function formatPercent(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "–";
  if (value >= 100) return "100%";
  return `${(Math.floor(value * 10 + 1e-9) / 10).toFixed(1)}%`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const LAGOS_OFFSET_MS = 60 * 60 * 1000; // Africa/Lagos is UTC+1 all year, no daylight saving.

function lagosParts(input: string | number | Date) {
  const d = new Date(new Date(input).getTime() + LAGOS_OFFSET_MS);
  return {
    day: d.getUTCDate(),
    month: MONTHS[d.getUTCMonth()]!,
    year: d.getUTCFullYear(),
    hh: String(d.getUTCHours()).padStart(2, "0"),
    mm: String(d.getUTCMinutes()).padStart(2, "0"),
  };
}

/** `12 Oct 2026, 14:05` in Africa/Lagos, 24-hour. */
export function formatDateTime(input: string | number | Date | null | undefined): string {
  if (input == null) return "–";
  const p = lagosParts(input);
  return `${p.day} ${p.month} ${p.year}, ${p.hh}:${p.mm}`;
}

export function formatDate(input: string | number | Date | null | undefined): string {
  if (input == null) return "–";
  const p = lagosParts(input);
  return `${p.day} ${p.month} ${p.year}`;
}

export function formatTime(input: string | number | Date | null | undefined): string {
  if (input == null) return "–";
  const p = lagosParts(input);
  return `${p.hh}:${p.mm}`;
}

/** `3 min ago`, falling back to the absolute time after a day. */
export function formatRelative(input: string | number | Date, now: number = Date.now()): string {
  const seconds = Math.round((now - new Date(input).getTime()) / 1000);
  if (seconds < 45) return "just now";
  if (seconds < 90) return "1 min ago";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return formatDateTime(input);
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "–";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export const pluralize = (count: number, one: string, many = `${one}s`): string =>
  `${formatNumber(count)} ${count === 1 ? one : many}`;

/** First letter upper-case, the rest unchanged. Enum values arrive as `REQUIRES_REVIEW`. */
export function sentenceCase(code: string): string {
  const words = code.replace(/_/g, " ").toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}
