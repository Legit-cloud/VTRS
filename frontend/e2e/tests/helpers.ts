import { expect, type Page } from "@playwright/test";

export const ADMIN = {
  identifier: process.env.E2E_ADMIN_ID ?? "admin@demo.example",
  password: process.env.E2E_ADMIN_PASSWORD ?? "Demo-passphrase-2026",
};
export const AGENT = {
  identifier: process.env.E2E_AGENT_ID ?? "agent@demo.example",
  password: process.env.E2E_AGENT_PASSWORD ?? "Demo-passphrase-2026",
};
export const OFFICER = {
  identifier: process.env.E2E_OFFICER_ID ?? "ward@demo.example",
  password: process.env.E2E_OFFICER_PASSWORD ?? "Demo-passphrase-2026",
};

/** The development mailbox (Mailpit), where the API's emails land. */
const MAILBOX = process.env.E2E_MAILBOX_URL ?? "http://localhost:8025";

interface MailSummary {
  Created: string;
  Snippet: string;
  To: { Address: string }[];
}

/**
 * The 6-digit code emailed to `to` for an action started at `since`. Waits for a new email; a
 * second request inside a minute reuses the code already sent, so after a short wait the newest
 * email from that minute is the one.
 */
export async function emailedCode(to: string, since: number): Promise<string> {
  const deadline = Date.now() + 20_000;
  while (Date.now() < deadline) {
    const response = await fetch(
      `${MAILBOX}/api/v1/search?query=${encodeURIComponent(`to:"${to}"`)}&limit=10`,
    );
    const { messages } = (await response.json()) as { messages: MailSummary[] };
    const reusedFrom = Date.now() - since > 3_000 ? since - 61_000 : since - 1_000;
    const fresh = messages
      .filter((m) => Date.parse(m.Created) >= reusedFrom)
      .sort((x, y) => Date.parse(y.Created) - Date.parse(x.Created));
    const code = fresh[0]?.Snippet.match(/\b(\d{6})\b/)?.[1];
    if (code) return code;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`No code emailed to ${to}`);
}

/** Password, then the code from the email, as a person would. */
export async function signIn(page: Page, who: { identifier: string; password: string }) {
  await page.goto("/login");
  await page.getByLabel("Phone number or email").fill(who.identifier);
  await page.getByLabel("Password").fill(who.password);
  const since = Date.now();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "Check your email" })).toBeVisible();
  await page.getByLabel("Code from the email").fill(await emailedCode(who.identifier, since));
  await page.getByRole("button", { name: "Verify" }).click();
}

export async function expectSignedIn(page: Page) {
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
}

/**
 * Sensitive actions may ask for a fresh code (unless the last one is recent enough). Pass the
 * time from just before the action was started.
 */
export async function confirmIfAsked(page: Page, email: string, since: number): Promise<void> {
  const prompt = page.getByRole("dialog").getByLabel("Code from the email");
  const asked = await prompt.waitFor({ state: "visible", timeout: 2_000 }).then(
    () => true,
    () => false,
  );
  if (!asked) return;
  await prompt.fill(await emailedCode(email, since));
  await page.getByRole("button", { name: "Confirm" }).click();
}
