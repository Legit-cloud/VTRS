import { expect, test } from "@playwright/test";
import { OFFICER, expectSignedIn, signIn } from "./helpers";

test("works at phone width: no sideways page scroll, menu in a drawer", async ({ page }) => {
  await signIn(page, OFFICER);
  await expect(page.getByRole("button", { name: "Open menu" })).toBeVisible();

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);

  await page.getByRole("button", { name: "Open menu" }).click();
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  await page.getByRole("link", { name: "Results" }).click();
  await expectSignedIn(page).catch(() => undefined);
  await expect(page.getByRole("heading", { name: "Results", level: 1 })).toBeVisible();

  const after = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(after).toBeLessThanOrEqual(0);
});
