/** Accept either the whole link from the SMS or just its token. */
export function tokenFrom(input: string): string {
  const text = input.trim();
  const match = /[?&]token=([^&#\s]+)/.exec(text);
  return match ? decodeURIComponent(match[1]!) : text;
}
