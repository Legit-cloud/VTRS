const SEPARATORS = /[\s\-().]/g;

/** Mirrors `normalize_phone` on the server: local Nigerian numbers get +234. */
export function normalizePhone(raw: string): string | null {
  const value = raw.trim().replace(SEPARATORS, "");
  let digits: string;
  if (value.startsWith("+")) digits = value.slice(1);
  else if (value.startsWith("00")) digits = value.slice(2);
  else if (value.startsWith("0")) digits = `234${value.slice(1)}`;
  else digits = value;
  if (!/^\d+$/.test(digits) || digits.length < 8 || digits.length > 15) return null;
  if (digits.startsWith("234") && digits.length !== 13) return null;
  return `+${digits}`;
}

/** `08031234567` -> `0803 123 4567` as the agent types. Leaves anything unexpected alone. */
export function formatLocalPhone(raw: string): string {
  const digits = raw.replace(/\D/g, "").slice(0, 11);
  if (digits.length <= 4) return digits;
  if (digits.length <= 7) return `${digits.slice(0, 4)} ${digits.slice(4)}`;
  return `${digits.slice(0, 4)} ${digits.slice(4, 7)} ${digits.slice(7)}`;
}

export const looksLikeEmail = (identifier: string): boolean => identifier.includes("@");

/** Turn what the agent typed into the identifier the API wants (E.164 phone, or email as typed). */
export function loginIdentifier(raw: string): string | null {
  const value = raw.trim();
  if (looksLikeEmail(value)) return value.toLowerCase();
  return normalizePhone(value);
}
