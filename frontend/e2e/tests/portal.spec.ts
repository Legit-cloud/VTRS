import AxeBuilder from "@axe-core/playwright";
import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { ADMIN, OFFICER, expectSignedIn, nextTotpWindow, signIn, totp } from "./helpers";

async function accessible(page: Page, label: string) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const summary = results.violations.map(
    (v) => `${v.id} (${v.impact}): ${v.nodes.length} node(s), e.g. ${v.nodes[0]?.target.join(" ")}`,
  );
  expect(summary, `Accessibility violations on ${label}`).toEqual([]);
}

test.describe("ward officer", () => {
  test("signs in and sees only their own area", async ({ page }) => {
    await signIn(page, OFFICER);
    await expectSignedIn(page);
    await expect(page).toHaveURL(/\/war-room/);

    // The scope bar makes the server's geographic limit visible, with a lock.
    const scope = page.getByRole("navigation", { name: "Your geographic scope" }).first();
    await expect(scope).toBeVisible();
    await expect(scope.getByLabel("Limited to this area")).toBeVisible();

    // Officers cannot manage people, so the item is not offered.
    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(nav.getByRole("link", { name: "War Room" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Team and permissions" })).toHaveCount(0);
    await expect(nav.getByRole("link", { name: "Elections and candidates" })).toHaveCount(0);
  });

  test("never shows a leader without the provisional badge", async ({ page }) => {
    await signIn(page, OFFICER);
    await expectSignedIn(page);
    await expect(page.getByText("Leading", { exact: true })).toBeVisible();
    await expect(page.getByText("Provisional").first()).toBeVisible();
    await expect(page.getByText(/\b(winner|won|declared)\b/i)).toHaveCount(0);
  });

  test("drills from the War Room into results", async ({ page }) => {
    await signIn(page, OFFICER);
    await page.getByRole("link", { name: "Results" }).click();
    await expect(page.getByRole("heading", { name: "Results", level: 1 })).toBeVisible();
    const rows = page.getByRole("row");
    await expect(rows.nth(1)).toBeVisible();
    await accessible(page, "results");
  });
});

test.describe("party admin", () => {
  test.describe.configure({ mode: "serial" });

  let context: BrowserContext;
  let secret = "";

  test.beforeAll(async ({ browser }) => {
    context = await browser.newContext();
  });
  test.afterAll(async () => {
    await context.close();
  });

  test("is held to a second factor, then enrols one", async () => {
    const page = await context.newPage();
    await signIn(page, ADMIN);
    // Admins cannot get past setup until an authenticator is on the account.
    await expect(page).toHaveURL(/\/settings/);
    await expect(page.getByText("Set up your authenticator to continue")).toBeVisible();

    // Every other page sends them back here.
    await page.goto("/war-room");
    await expect(page).toHaveURL(/\/settings/);

    await page.getByRole("button", { name: "Set up authenticator" }).click();
    const secretBox = page.locator("code.mono").first();
    await expect(secretBox).toBeVisible();
    secret = (await secretBox.innerText()).trim();
    await page.getByLabel("6-digit code from the app").fill(totp(secret));
    await page.getByRole("button", { name: "Turn on authenticator" }).click();

    await expect(page.getByText("Save your recovery codes")).toBeVisible();
    await page.getByRole("button", { name: "I have saved them" }).click();
    await expect(page.getByText("Authenticator on")).toBeVisible();
    await page.close();
  });

  test("signs in with the second factor and sees the whole state", async ({ browser }) => {
    // A code is good once: the one used to enrol cannot sign in, so wait for the next window.
    await nextTotpWindow();
    const fresh = await browser.newContext();
    const page = await fresh.newPage();
    await signIn(page, ADMIN);
    await expect(page.getByRole("heading", { name: "Enter your code" })).toBeVisible();
    await page.getByLabel("Authenticator code").fill(totp(secret));
    await page.getByRole("button", { name: "Verify" }).click();
    await expectSignedIn(page);

    const nav = page.getByRole("navigation", { name: "Main" });
    for (const item of [
      "War Room",
      "Results",
      "Anomalies",
      "Agents",
      "Elections and candidates",
      "Evidence",
      "Reports",
      "Team and permissions",
      "Audit log",
      "Settings",
    ]) {
      await expect(nav.getByRole("link", { name: item })).toBeVisible();
    }

    // Keep this signed-in session for the rest of the group.
    const state = await fresh.storageState();
    await context.addCookies(state.cookies);
    await fresh.close();
  });

  test("works an anomaly from the queue", async () => {
    const page = await context.newPage();
    await page.goto("/anomalies");
    await expect(page.getByRole("heading", { name: "Anomalies", level: 1 })).toBeVisible();

    await accessible(page, "anomalies");

    // Work the first flag nobody has touched yet.
    await page.getByLabel("Status").selectOption("OPEN");
    const first = page.locator("button[aria-pressed]").first();
    await expect(first).toBeVisible();
    await first.click();
    await page.getByRole("button", { name: "Acknowledge" }).click();
    await expect(page.getByText("Flag acknowledged")).toBeVisible();
    await expect(page.getByRole("heading", { name: "History" })).toBeVisible();
    await page.getByLabel("Note").first().fill("Checked the sheet against the photo.");
    await page.getByRole("button", { name: "Add note" }).click();
    await expect(page.getByText("Checked the sheet against the photo.")).toBeVisible();
    await page.close();
  });

  test("lists agents, elections, team and the audit trail", async () => {
    const page = await context.newPage();
    await page.goto("/agents");
    await expect(page.getByRole("heading", { name: "Agents", level: 1 })).toBeVisible();
    await expect(page.getByRole("row").nth(1)).toBeVisible();
    await accessible(page, "agents");

    await page.getByRole("link", { name: "Elections and candidates" }).click();
    await expect(page.getByRole("heading", { name: "Contests and candidates" })).toBeVisible();
    await accessible(page, "elections");

    await page.getByRole("link", { name: "Team and permissions" }).click();
    await expect(
      page.getByRole("heading", { name: "Team and permissions", level: 1 }),
    ).toBeVisible();
    await accessible(page, "team");

    await page.getByRole("link", { name: "Audit log" }).click();
    await expect(page.getByRole("heading", { name: "Audit log", level: 1 })).toBeVisible();
    await page.close();
  });

  test("sets up an election step by step, with the next step always stated", async () => {
    const page = await context.newPage();
    const name = `E2E election ${Date.now()}`;
    await page.goto("/elections");
    await page.getByRole("button", { name: "New election" }).first().click();

    // The state is chosen explicitly, never guessed.
    await page.getByLabel("Election name").fill(name);
    const option = page.getByLabel("State").locator("option", { hasText: "Test state" });
    await page.getByLabel("State").selectOption(await option.getAttribute("value"));
    await page.getByLabel("Election day").fill("2027-02-20");
    await page.getByRole("button", { name: "Create and continue" }).click();

    // Straight into the first contest.
    await expect(page.getByRole("heading", { name: "Add a contest" })).toBeVisible();
    await page.getByRole("button", { name: "Add contest" }).click();

    // Then its candidates; one is not enough and the page says so.
    await expect(page.getByRole("heading", { name: "Add a candidate" })).toBeVisible();
    await page.getByLabel("Candidate's name").fill("Ada Obi");
    await page.getByLabel("Party", { exact: true }).fill("Alpha Party");
    await page.getByLabel("Party acronym").fill("ALP");
    await page.getByRole("button", { name: "Add candidate" }).last().click();
    await page.getByRole("button", { name: "Done" }).click();
    await expect(page.getByText("Needs 2 candidates")).toBeVisible();
    await expect(page.getByRole("button", { name: "Mark as ready" })).toBeDisabled();

    await page.getByRole("button", { name: "Add candidate" }).first().click();
    await page.getByLabel("Candidate's name").fill("Bola Eze");
    await page.getByLabel("Party", { exact: true }).fill("Beta Party");
    await page.getByLabel("Party acronym").fill("BET");
    await page.getByRole("button", { name: "Add candidate" }).last().click();
    await page.getByRole("button", { name: "Done" }).click();

    await expect(page.getByRole("button", { name: "Mark as ready" })).toBeEnabled();
    await accessible(page, "election workflow");
    await page.getByRole("button", { name: "Mark as ready" }).click();
    await expect(page.getByRole("heading", { name: "Ready to lock" })).toBeVisible();
    await page.close();
  });

  test("assigns an agent from their authorised units, then deactivation frees the unit", async () => {
    const page = await context.newPage();
    await page.goto("/agents");
    await expect(page.getByText(/Assigning for E2E election/)).toBeVisible();

    const row = page.getByRole("row").filter({ hasText: "Not assigned" }).last();
    const agent = (await row.getByRole("cell").first().innerText()).trim();
    await row.getByRole("button", { name: "Assign" }).click();
    await page.getByRole("radio", { name: /SYN-/ }).check();
    await page.getByRole("button", { name: "Assign agent" }).click();

    // A recent sign-in is fresh enough; otherwise a code is asked for.
    const prompt = page.getByLabel("Authenticator code");
    if (
      await prompt.waitFor({ state: "visible", timeout: 2_000 }).then(
        () => true,
        () => false,
      )
    ) {
      await nextTotpWindow();
      await prompt.fill(totp(secret));
      await page.getByRole("button", { name: "Confirm" }).click();
    }
    await expect(page.getByText("Agent assigned")).toBeVisible();
    const assigned = page.getByRole("row").filter({ hasText: agent });
    await expect(assigned.locator(".mono")).toBeVisible();

    // Deactivating says what will happen, and the unit is released.
    await assigned.getByRole("button", { name: "Deactivate" }).click();
    await expect(page.getByText(/removed from 1 polling unit/)).toBeVisible();
    await page.getByRole("button", { name: "Deactivate agent" }).click();
    const again = page.getByLabel("Authenticator code");
    if (
      await again.waitFor({ state: "visible", timeout: 2_000 }).then(
        () => true,
        () => false,
      )
    ) {
      await nextTotpWindow();
      await again.fill(totp(secret));
      await page.getByRole("button", { name: "Confirm" }).click();
    }
    await expect(
      page.getByRole("row").filter({ hasText: agent }).getByText("Deactivated"),
    ).toBeVisible();
    await expect(
      page.getByRole("row").filter({ hasText: agent }).getByText("Not assigned"),
    ).toBeVisible();
    await page.close();
  });

  test("war room is accessible", async () => {
    const page = await context.newPage();
    await page.goto("/war-room");
    await expect(page.getByText("Leading", { exact: true })).toBeVisible();
    await accessible(page, "war room");
    await page.close();
  });
});

test("login screen is accessible and explains failures plainly", async ({ page }) => {
  await page.goto("/login");
  await accessible(page, "login");
  await page.getByLabel("Phone number or email").fill("nobody@demo.example");
  await page.getByLabel("Password").fill("not-the-password");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page).toHaveURL(/\/login/);
});
