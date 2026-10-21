import AxeBuilder from "@axe-core/playwright";
import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { ADMIN, OFFICER, confirmIfAsked, expectSignedIn, signIn } from "./helpers";

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
    await expect(nav.getByRole("link", { name: "Elections and contestants" })).toHaveCount(0);
    await expect(nav.getByRole("link", { name: "Parties" })).toHaveCount(0);
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

  test.beforeAll(async ({ browser }) => {
    context = await browser.newContext();
  });
  test.afterAll(async () => {
    await context.close();
  });

  test("needs the code from their email; the password alone is not enough", async () => {
    const page = await context.newPage();
    await page.goto("/login");
    await page.getByLabel("Phone number or email").fill(ADMIN.identifier);
    await page.getByLabel("Password").fill(ADMIN.password);
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByRole("heading", { name: "Check your email" })).toBeVisible();
    await expect(page.getByText(/We sent a 6-digit code to a\*\*\*@demo\.example/)).toBeVisible();
    await expect(page.getByRole("button", { name: /Send a new code in \d+ s/ })).toBeDisabled();
    await accessible(page, "sign-in code");

    await page.getByLabel("Code from the email").fill("000000");
    await page.getByRole("button", { name: "Verify" }).click();
    await expect(page.getByText("That didn't work")).toBeVisible();
    await page.goto("/war-room");
    await expect(page).toHaveURL(/\/login/);
    await page.close();
  });

  test("signs in with the emailed code and sees the whole state", async ({ browser }) => {
    const fresh = await browser.newContext();
    const page = await fresh.newPage();
    await signIn(page, ADMIN);
    await expectSignedIn(page);

    const nav = page.getByRole("navigation", { name: "Main" });
    for (const item of [
      "War Room",
      "Results",
      "Anomalies",
      "Agents",
      "Elections and contestants",
      "Parties",
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

    await page.getByRole("link", { name: "Elections and contestants" }).click();
    await expect(page.getByRole("heading", { name: "Contesting parties" })).toBeVisible();
    await accessible(page, "elections");

    await page.getByRole("link", { name: "Parties", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Parties", level: 1 })).toBeVisible();
    await accessible(page, "parties");

    await page.getByRole("link", { name: "Team and permissions" }).click();
    await expect(
      page.getByRole("heading", { name: "Team and permissions", level: 1 }),
    ).toBeVisible();
    await accessible(page, "team");

    await page.getByRole("link", { name: "Audit log" }).click();
    await expect(page.getByRole("heading", { name: "Audit log", level: 1 })).toBeVisible();
    await page.close();
  });

  // Two parties made for this run, so reruns never collide with an earlier run's list.
  const stamp = String(Date.now()).slice(-5);
  const runParties = [
    { abbreviation: `A${stamp}`, name: `Alpha Party ${stamp}`, candidate: "Ada Obi" },
    { abbreviation: `B${stamp}`, name: `Beta Party ${stamp}`, candidate: "Bola Eze" },
  ];

  test("adds parties to the party list", async () => {
    const page = await context.newPage();
    await page.goto("/parties");
    for (const party of runParties) {
      await page.getByRole("button", { name: "Add a party" }).first().click();
      await page.getByLabel("Abbreviation").fill(party.abbreviation);
      await page.getByLabel("Full name").fill(party.name);
      await page.getByRole("button", { name: "Add party" }).click();
      await expect(page.getByText(party.name)).toBeVisible();
    }
    await accessible(page, "party list");
    await page.close();
  });

  test("sets up an election step by step, with the next step always stated", async () => {
    const page = await context.newPage();
    const name = `E2E election ${Date.now()}`;
    await page.goto("/elections");
    await page.getByRole("button", { name: "New election" }).first().click();

    // The type decides the constituencies; nothing is guessed.
    await page.getByLabel("Type of election").selectOption({ label: "Governorship" });
    await page.getByLabel("Election name").fill(name);
    await page.getByLabel("Election day").fill("2027-02-20");
    await page.getByRole("button", { name: "Create and continue" }).click();
    await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Mark as ready" })).toBeDisabled();

    // Contesting parties, in the order agents will see them.
    for (const party of runParties) {
      await page
        .getByLabel("Add a party")
        .selectOption({ label: `${party.abbreviation} · ${party.name}` });
      await page.getByRole("button", { name: "Add", exact: true }).click();
    }
    await page.getByRole("button", { name: "Save order" }).click();
    await expect(page.getByText("Contesting parties saved")).toBeVisible();

    // One contestant is not enough, and the page says so.
    await page.getByRole("button", { name: "Add contestants" }).first().click();
    await expect(page.getByRole("heading", { name: "Add contestants" })).toBeVisible();
    await page.getByLabel("Candidate's name").fill(runParties[0]!.candidate);
    await page.getByRole("button", { name: "Add contestant" }).last().click();
    await expect(
      page.getByText(`${runParties[0]!.candidate} (${runParties[0]!.abbreviation}) added`),
    ).toBeVisible();
    await page.getByRole("button", { name: "Done" }).click();
    await expect(page.getByText(/has one contestant/).first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Mark as ready" })).toBeDisabled();

    await page.getByRole("button", { name: "Add contestant" }).first().click();
    await page.getByLabel("Candidate's name").fill(runParties[1]!.candidate);
    await page.getByRole("button", { name: "Add contestant" }).last().click();
    await expect(
      page.getByText(`${runParties[1]!.candidate} (${runParties[1]!.abbreviation}) added`),
    ).toBeVisible();
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

    // Never the demo agent: the phone-width tests sign in as them.
    const row = page
      .getByRole("row")
      .filter({ hasText: "Not assigned" })
      .filter({ hasNotText: "Kemi Adebayo" })
      .filter({ has: page.getByRole("button", { name: "Assign", exact: true }) })
      .last();
    const agent = (await row.getByRole("cell").first().innerText()).trim();
    await row.getByRole("button", { name: "Assign" }).click();
    await page.getByRole("radio", { name: /SYN-/ }).check();
    let since = Date.now();
    await page.getByRole("button", { name: "Assign agent" }).click();

    // A recent sign-in is fresh enough; otherwise a code is emailed and asked for.
    await confirmIfAsked(page, ADMIN.identifier, since);
    await expect(page.getByText("Agent assigned")).toBeVisible();
    const assigned = page.getByRole("row").filter({ hasText: agent });
    await expect(assigned.locator(".mono")).toBeVisible();

    // Deactivating says what will happen, and the unit is released.
    await assigned.getByRole("button", { name: "Deactivate" }).click();
    await expect(page.getByText(/removed from 1 polling unit/)).toBeVisible();
    since = Date.now();
    await page.getByRole("button", { name: "Deactivate agent" }).click();
    await confirmIfAsked(page, ADMIN.identifier, since);
    await expect(
      page.getByRole("row").filter({ hasText: agent }).getByText("Deactivated"),
    ).toBeVisible();
    await expect(
      page.getByRole("row").filter({ hasText: agent }).getByText("Not assigned"),
    ).toBeVisible();
    await page.close();
  });

  test("deletes an election that is still being set up", async () => {
    const page = await context.newPage();
    await page.goto("/elections");
    const picker = page.getByLabel("Election", { exact: true });
    const name = (await picker.locator("option:checked").innerText()).replace(/ \(.*\)$/, "");
    expect(name).toMatch(/^E2E election/);

    await page.getByRole("button", { name: "Delete election" }).click();
    await expect(page.getByText(/This cannot be undone/)).toBeVisible();
    const since = Date.now();
    await page.getByRole("dialog").getByRole("button", { name: "Delete election" }).click();
    await confirmIfAsked(page, ADMIN.identifier, since);
    await expect(page.getByText(`${name} was deleted`)).toBeVisible();
    await expect(picker.locator("option", { hasText: name })).toHaveCount(0);

    // With the election gone, the run's parties can leave the list too.
    await page.goto("/parties");
    for (const party of runParties) {
      await page.getByRole("button", { name: `Remove ${party.abbreviation}` }).click();
      await page.getByRole("dialog").getByRole("button", { name: "Remove party" }).click();
      await expect(page.getByText(party.name)).toHaveCount(0);
    }
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
