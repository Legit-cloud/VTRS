// A replaceable source of secure random bytes. Browsers and Node expose
// `crypto.getRandomValues`; React Native does not, so the app injects one at start-up.
type RandomSource = (length: number) => Uint8Array;

let source: RandomSource | null = null;

export function setRandomSource(next: RandomSource): void {
  source = next;
}

export function randomBytes(length: number): Uint8Array {
  if (source) return source(length);
  const webCrypto = (globalThis as { crypto?: Crypto }).crypto;
  if (webCrypto?.getRandomValues) return webCrypto.getRandomValues(new Uint8Array(length));
  throw new Error("No secure random source. Call setRandomSource() at start-up.");
}
