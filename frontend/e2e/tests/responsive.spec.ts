import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { AGENT, OFFICER, expectSignedIn, signIn } from "./helpers";

async function noSidewaysScroll(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

async function accessible(page: Page, label: string) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const summary = results.violations.map(
    (v) =>
      `${v.id} (${v.impact}): ${v.nodes.length} node(s), e.g. ${v.nodes[0]?.target.join(" ")} ${
        v.nodes[0]?.html.slice(0, 120) ?? ""
      } ${v.nodes[0]?.failureSummary?.replace(/\s+/g, " ").slice(0, 200) ?? ""}`,
  );
  expect(summary, `Accessibility violations on ${label}`).toEqual([]);
}

/** A textured JPEG made in the page, like a phone photo of a sheet (only smaller). */
async function sheetPhoto(page: Page): Promise<Buffer> {
  const data = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 1200;
    canvas.height = 1600;
    const ctx = canvas.getContext("2d")!;
    ctx.fillStyle = "#fafafa";
    ctx.fillRect(0, 0, 1200, 1600);
    ctx.fillStyle = "#222";
    ctx.font = "48px sans-serif";
    ctx.fillText(`EC8A ${Date.now()}`, 80, 120);
    for (let i = 0; i < 400; i++) {
      ctx.fillStyle = `hsl(${(i * 37) % 360} 40% ${30 + (i % 50)}%)`;
      ctx.fillRect((i * 97) % 1150, 200 + ((i * 53) % 1350), 40, 12);
    }
    return canvas.toDataURL("image/jpeg", 0.92).split(",")[1]!;
  });
  return Buffer.from(data, "base64");
}

test("works at phone width: no sideways page scroll, menu in a drawer", async ({ page }) => {
  await signIn(page, OFFICER);
  await expect(page.getByRole("button", { name: "Open menu" })).toBeVisible();

  await noSidewaysScroll(page);

  await page.getByRole("button", { name: "Open menu" }).click();
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  await page.getByRole("link", { name: "Results" }).click();
  await expectSignedIn(page).catch(() => undefined);
  await expect(page.getByRole("heading", { name: "Results", level: 1 })).toBeVisible();

  await noSidewaysScroll(page);
});

let unitCode = "";

/** The sheet: compressed in the browser, hashed, uploaded straight to storage, confirmed. */
async function attachSheet(page: Page) {
  await expect(page.getByRole("heading", { name: "Attach the result sheet" })).toBeVisible();
  await page
    .locator('input[type=file][accept="image/*,application/pdf"]')
    .setInputFiles({ name: "ec8a.jpg", mimeType: "image/jpeg", buffer: await sheetPhoto(page) });
  await expect(page.getByRole("heading", { name: "Result sheet uploaded" })).toBeVisible({
    timeout: 30_000,
  });
}

test("an agent sends numbers, then the result sheet, from a phone", async ({ page }) => {
  await signIn(page, AGENT);
  // Agents land on their own units, not the War Room.
  await expect(page).toHaveURL(/\/capture/);
  await expect(page.getByRole("heading", { name: /Hello/ })).toBeVisible();
  // The coordinator test verifies this unit next.
  unitCode = (await page.locator("main .mono").first().innerText()).trim();
  expect(unitCode).toMatch(/^SYN-/);
  await noSidewaysScroll(page);
  await accessible(page, "agent home");

  // The simulation sent numbers for their unit without a sheet: attaching it comes first.
  const action = page.getByRole("link", {
    name: /Enter the result|Continue your result|Correct this result|Send a corrected result|Attach the result sheet/,
  });
  if ((await action.innerText()).trim().startsWith("Attach")) {
    await action.click();
    await attachSheet(page);
    await page.getByRole("link", { name: "Back to my polling units" }).click();
    await expect(page.getByText("Sheet uploaded").first()).toBeVisible();
  }

  // Then a correction: a new version, with its own sheet; the first one is kept.
  await page.getByRole("link", { name: /Correct this result|Send a corrected result|Enter the result|Continue your result/ }).click();

  // One row per configured party; blanks are refused with the party named.
  const inputs = page.locator("li input[inputmode=numeric]");
  await expect(page.getByRole("heading", { name: "Votes for each party" })).toBeVisible();
  const parties = (await inputs.count()) - 3;
  expect(parties).toBeGreaterThanOrEqual(2);
  for (let i = 0; i < parties + 3; i++) await inputs.nth(i).fill("");
  await page.getByRole("button", { name: /Send the/ }).click();
  await expect(page.getByText(/Use 0 if they got none/).first()).toBeVisible();

  // Numbers that do not add up are caught before sending.
  for (let i = 0; i < parties; i++) await inputs.nth(i).fill(String(100 + i * 10));
  const sum = Array.from({ length: parties }, (_, i) => 100 + i * 10).reduce((a, b) => a + b, 0);
  await page.getByLabel(/Accredited voters/).fill(String(sum + 50));
  await page.getByLabel(/Total votes cast/).fill(String(sum - 1));
  await page.getByLabel(/Rejected votes/).fill("4");
  await expect(page.getByText(/are more than total votes cast/)).toBeVisible();

  // Fixed: the sums agree, and the reminder that nothing is lost on reload holds.
  await page.getByLabel(/Total votes cast/).fill(String(sum + 4));
  await expect(page.getByText("The numbers add up.")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel(/Total votes cast/)).toHaveValue(String(sum + 4));
  await accessible(page, "result form");
  await noSidewaysScroll(page);

  await page.getByRole("button", { name: /Send the/ }).click();
  await expect(page.getByText("Votes received").first()).toBeVisible();

  await attachSheet(page);
  await page.getByRole("link", { name: "Back to my polling units" }).click();
  await expect(page.getByText("Sheet uploaded").first()).toBeVisible();
});

test("an agent cannot open coordinator pages", async ({ page }) => {
  await signIn(page, AGENT);
  await expect(page).toHaveURL(/\/capture/);
  await page.goto("/war-room");
  await expect(page).toHaveURL(/\/capture/);
  await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(0);
});

test("a ward coordinator verifies that result against its sheet", async ({ page }) => {
  await signIn(page, OFFICER);
  await expect(page).toHaveURL(/\/war-room/);
  await page.goto("/results");
  await page.getByRole("tab", { name: "To verify" }).click();
  expect(unitCode, "runs after the agent test").not.toBe("");
  const row = page.getByRole("row").filter({ hasText: unitCode }).first();
  await expect(row.getByText("Sheet uploaded")).toBeVisible();
  await row.click();

  const panel = page.getByRole("dialog");
  await expect(panel.getByRole("heading", { name: "Verify this result" })).toBeVisible();
  await expect(panel.getByText("Compare every number with the result sheet")).toBeVisible();
  const acknowledge = panel.getByText(/I have looked at the \d+ open/);
  if (await acknowledge.isVisible()) await acknowledge.click();
  await panel.getByRole("button", { name: "Verify result" }).click();
  await expect(page.getByText("Result verified")).toBeVisible();
});
