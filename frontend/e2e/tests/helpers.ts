import { createHmac } from "node:crypto";
import { expect, type Page } from "@playwright/test";

export const ADMIN = {
  identifier: process.env.E2E_ADMIN_ID ?? "admin@demo.example",
  password: process.env.E2E_ADMIN_PASSWORD ?? "Demo-passphrase-2026",
};
export const OFFICER = {
  identifier: process.env.E2E_OFFICER_ID ?? "ward@demo.example",
  password: process.env.E2E_OFFICER_PASSWORD ?? "Demo-passphrase-2026",
};

const BASE32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

function base32Decode(input: string): Buffer {
  const clean = input.replace(/[\s=]/g, "").toUpperCase();
  let bits = "";
  for (const ch of clean) bits += BASE32.indexOf(ch).toString(2).padStart(5, "0");
  const bytes: number[] = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(bytes);
}

/** RFC 6238 TOTP, SHA-1, 6 digits, 30 s steps: what every authenticator app computes. */
export function totp(secret: string, at: number = Date.now()): string {
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(at / 1000 / 30)));
  const hmac = createHmac("sha1", base32Decode(secret)).update(counter).digest();
  const offset = hmac[hmac.length - 1]! & 0x0f;
  const binary =
    ((hmac[offset]! & 0x7f) << 24) |
    (hmac[offset + 1]! << 16) |
    (hmac[offset + 2]! << 8) |
    hmac[offset + 3]!;
  return String(binary % 1_000_000).padStart(6, "0");
}

export async function signIn(page: Page, who: { identifier: string; password: string }) {
  await page.goto("/login");
  await page.getByLabel("Phone number or email").fill(who.identifier);
  await page.getByLabel("Password").fill(who.password);
  await page.getByRole("button", { name: "Continue" }).click();
}

export async function expectSignedIn(page: Page) {
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
}

/** Servers accept each authenticator code once, so wait until the 30 s window rolls over. */
export async function nextTotpWindow(): Promise<void> {
  const remaining = 30_000 - (Date.now() % 30_000);
  await new Promise((resolve) => setTimeout(resolve, remaining + 750));
}
