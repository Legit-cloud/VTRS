import AxeBuilder from "@axe-core/playwright";
import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { OFFICER, nextTotpWindow, signIn, totp } from "./helpers";

const OPS = {
  identifier: process.env.E2E_OPS_ID ?? "ops@demo.example",
  password: process.env.E2E_OPS_PASSWORD ?? "Demo-passphrase-2026-ops",
};

async function accessible(page: Page, label: string) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const summary = results.violations.map(
    (v) => `${v.id} (${v.impact}): ${v.nodes.length} node(s), e.g. ${v.nodes[0]?.target.join(" ")}`,
  );
  expect(summary, `Accessibility violations on ${label}`).toEqual([]);
}

test.describe("platform operator", () => {
  test.describe.configure({ mode: "serial" });

  let context: BrowserContext;
  let secret = "";

  test.beforeAll(async ({ browser }) => {
    context = await browser.newContext();
  });
  test.afterAll(async () => {
    await context.close();
  });

  test("enrols an authenticator before seeing anything else", async () => {
    const page = await context.newPage();
    await signIn(page, OPS);
    await expect(page).toHaveURL(/\/settings/);
    await page.getByRole("button", { name: "Set up authenticator" }).click();
    const box = page.locator("code.mono").first();
    await expect(box).toBeVisible();
    secret = (await box.innerText()).trim();
    await page.getByLabel("6-digit code from the app").fill(totp(secret));
    await page.getByRole("button", { name: "Turn on authenticator" }).click();
    await expect(page.getByText("Save your recovery codes")).toBeVisible();
    await page.close();
  });

  test("signs in to chrome that is unmistakably the platform's", async ({ browser }) => {
    await nextTotpWindow();
    const fresh = await browser.newContext();
    const page = await fresh.newPage();
    await signIn(page, OPS);
    await page.getByLabel("Authenticator code").fill(totp(secret));
    await page.getByRole("button", { name: "Verify" }).click();

    await expect(page).toHaveURL(/\/platform/);
    const nav = page.getByRole("navigation", { name: "Main" });
    for (const item of [
      "Overview",
      "Organisations",
      "Verification queue",
      "Elections",
      "Master data",
      "System health",
      "Messaging providers",
      "Audit log",
    ]) {
      await expect(nav.getByRole("link", { name: item })).toBeVisible();
    }
    // None of the party portal's pages are offered.
    await expect(nav.getByRole("link", { name: "War Room" })).toHaveCount(0);
    await expect(nav.getByRole("link", { name: "Agents" })).toHaveCount(0);

    await context.addCookies((await fresh.storageState()).cookies);
    await fresh.close();
  });

  test("overview answers 'is it healthy and who needs attention'", async () => {
    const page = await context.newPage();
    await page.goto("/platform");
    await expect(page.getByRole("heading", { name: "Overview", level: 1 })).toBeVisible();
    await expect(page.getByText("Active organisations")).toBeVisible();
    await expect(
      page
        .getByText("organisations waiting for approval")
        .or(page.getByText("Nothing is waiting on you.")),
    ).toBeVisible();
    await accessible(page, "platform overview");
    await page.close();
  });

  test("approves a registration after typing its name", async () => {
    const page = await context.newPage();
    await page.goto("/platform/verification");
    await page.getByRole("row", { name: /Pending Party 1/ }).click();
    await page.getByRole("button", { name: "Approve" }).click();

    const confirm = page.getByRole("button", { name: "Approve organisation" });
    await expect(confirm).toBeDisabled();
    await page.getByLabel(/Type .* to confirm/).fill("Pending Party 1");
    await confirm.click();

    await expect(page.getByText("Decision recorded")).toBeVisible();
    await expect(page.getByText("Active", { exact: true }).first()).toBeVisible();
    await page.close();
  });

  test("rejecting needs a reason that is kept", async () => {
    const page = await context.newPage();
    await page.goto("/platform/verification");
    await page.getByRole("row", { name: /Pending Party 2/ }).click();
    await page.getByRole("button", { name: "Reject", exact: true }).click();

    const confirm = page.getByRole("button", { name: "Reject organisation" });
    await page.getByLabel(/Type .* to confirm/).fill("Pending Party 2");
    await expect(confirm).toBeDisabled(); // a name alone is not enough
    await page.getByLabel("Why is it rejected?").fill("Registration papers do not match.");
    await confirm.click();
    await expect(page.getByText("Decision recorded")).toBeVisible();
    await page.close();
  });

  test("lists organisations by state and suspends one", async () => {
    const page = await context.newPage();
    await page.goto("/platform/organizations");
    await expect(page.getByRole("heading", { name: "Organisations", level: 1 })).toBeVisible();
    await accessible(page, "organisations");

    await page.getByLabel("Status").selectOption("ACTIVE");
    await page.getByRole("row", { name: /Pending Party 1/ }).click();
    await page.getByRole("button", { name: "Suspend" }).click();
    await page.getByLabel("Why is it suspended?").fill("Testing the suspension flow.");
    await page.getByLabel(/Type .* to confirm/).fill("Pending Party 1");
    await page.getByRole("button", { name: "Suspend organisation" }).click();
    await expect(page.getByText("Decision recorded")).toBeVisible();
    await expect(page.getByText("Testing the suspension flow.")).toBeVisible();
    await page.close();
  });

  test("previews a master-data import without writing it", async () => {
    const page = await context.newPage();
    await page.goto("/platform/master-data");
    await expect(page.getByRole("heading", { name: "Master data", level: 1 })).toBeVisible();

    const header =
      "state_code,state_name,lga_code,lga_name,ward_code,ward_name,pu_code,pu_name,latitude,longitude,registered_voters";
    const rows = [
      "ZZ,Preview State,ZZ-01,Preview LGA,ZZ-01-01,Preview Ward,ZZ-01-01-001,Preview School A,7.38,3.94,600",
      "ZZ,Preview State,ZZ-01,Preview LGA,ZZ-01-01,Preview Ward,ZZ-01-01-002,Preview School B,7.39,3.95,450",
    ];
    await page.getByLabel("Choose a CSV file").setInputFiles({
      name: "preview.csv",
      mimeType: "text/csv",
      buffer: Buffer.from([header, ...rows].join("\n")),
    });
    await expect(page.getByRole("heading", { name: "What would change" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Import this file" })).toBeVisible();

    // A broken file is explained, and cannot be imported.
    await page.getByLabel("Choose a CSV file").setInputFiles({
      name: "broken.csv",
      mimeType: "text/csv",
      buffer: Buffer.from("state_code\nZZ\n"),
    });
    await expect(page.getByText(/problems stop this import/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Import this file" })).toHaveCount(0);
    await accessible(page, "master data");
    await page.close();
  });

  test("health, messaging and audit pages work", async () => {
    const page = await context.newPage();
    await page.goto("/platform/health");
    await expect(page.getByRole("heading", { name: "System health", level: 1 })).toBeVisible();
    await expect(page.getByText("Database")).toBeVisible();
    await accessible(page, "system health");

    await page.goto("/platform/messaging");
    await expect(
      page.getByRole("heading", { name: "Messaging providers", level: 1 }),
    ).toBeVisible();
    await expect(page.getByRole("row", { name: /SMS/ })).toBeVisible();
    await accessible(page, "messaging");

    await page.goto("/platform/audit");
    await expect(page.getByRole("heading", { name: "Audit log", level: 1 })).toBeVisible();
    await expect(
      page.getByText(/organization suspended|organization approved/i).first(),
    ).toBeVisible();
    await page.close();
  });

  test("operators cannot reach party pages and parties cannot reach the platform", async ({
    browser,
  }) => {
    const page = await context.newPage();
    await page.goto("/war-room");
    await expect(page).toHaveURL(/\/platform/);
    await page.close();

    const party = await browser.newContext();
    const officer = await party.newPage();
    await signIn(officer, OFFICER);
    await expect(officer.getByRole("navigation", { name: "Main" })).toBeVisible();
    await officer.goto("/platform/organizations");
    await expect(officer).toHaveURL(/\/war-room/);
    await party.close();
  });
});
