import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";

/**
 * Canonical JSON, byte for byte what the server computes (`apps/core/domain/canonical.py`):
 * keys sorted at every level, no whitespace, UTF-8, values exactly as sent. Floats are
 * refused on purpose: JavaScript and Python print them differently, so decimals travel as
 * strings and counts as integers.
 */
export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };

export function canonicalJson(value: Json): string {
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value)) {
      throw new Error("Canonical JSON accepts integers only; send decimals as strings.");
    }
    return String(value);
  }
  if (typeof value === "string") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  const keys = Object.keys(value).sort(compareCodePoints);
  const parts: string[] = [];
  for (const key of keys) {
    const item = value[key];
    if (item === undefined) continue;
    parts.push(`${JSON.stringify(key)}:${canonicalJson(item)}`);
  }
  return `{${parts.join(",")}}`;
}

// Python sorts str keys by code point; JS `<` compares UTF-16 units. Equal for BMP text.
function compareCodePoints(a: string, b: string): number {
  const ca = Array.from(a);
  const cb = Array.from(b);
  const n = Math.min(ca.length, cb.length);
  for (let i = 0; i < n; i++) {
    const d = ca[i]!.codePointAt(0)! - cb[i]!.codePointAt(0)!;
    if (d !== 0) return d;
  }
  return ca.length - cb.length;
}

const encoder = new TextEncoder();

export function sha256Hex(data: Uint8Array | string): string {
  return bytesToHex(sha256(typeof data === "string" ? encoder.encode(data) : data));
}

/** SHA-256 of an item without its own `payload_hash`, as the server verifies it. */
export function payloadHash(item: { [key: string]: Json }): string {
  const { payload_hash: _omit, ...rest } = item;
  return sha256Hex(canonicalJson(rest));
}
