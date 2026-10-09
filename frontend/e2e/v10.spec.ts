// V10 Ask this pack (fake model, recorded data): suggested questions, a cited answer that opens a real
// post, and a plain "no evidence" answer.
import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const KEY = process.env.E2E_RUN_KEY!;

test("ask a featured pack: citations open real posts; no evidence is said plainly", async ({ page }) => {
  // Without a key: the panel says it needs a run key (never "guest") and offers no question box (2026-10-09)
  await page.goto("/packs");
  await page.getByText("Launching a snack brand in the Netherlands").first().click();
  await page.getByRole("button", { name: "Ask this pack" }).click();
  let panel = page.getByRole("complementary", { name: "Ask this pack" });
  await expect(panel.getByText("Asking needs a run key: add it on the start page.")).toBeVisible();
  await expect(panel.getByLabel("Your question about this pack")).toHaveCount(0);
  expect(await panel.innerText()).not.toMatch(/guest/i);

  // The key typed on the start page is kept for this tab (no brief needed), then asking works
  await panel.getByRole("link", { name: "Go to the start page" }).click();
  await page.getByLabel("Run key").fill(KEY);
  expect(await page.content()).not.toContain(KEY);                     // never on the page
  await page.goto("/packs");
  await page.getByText("Launching a snack brand in the Netherlands").first().click();
  await page.getByRole("button", { name: "Ask this pack" }).click();
  panel = page.getByRole("complementary", { name: "Ask this pack" });
  await expect(panel.getByRole("list", { name: "Suggested questions" }).getByRole("button")).toHaveCount(4);

  await panel.getByLabel("Your question about this pack").fill("uitverkocht");
  await panel.getByRole("button", { name: "Ask" }).click();
  const cite = panel.locator("p a[href^='http']").first();          // a numbered citation in the answer
  await expect(cite).toBeVisible();
  await expect(cite).toHaveText(/^\d+$/);
  expect(await panel.innerText()).not.toMatch(/TEN-99|EV-\d{4}/);    // invented id stripped, no raw ids

  await panel.getByLabel("Your question about this pack").fill("zzyzxqwv");
  await panel.getByRole("button", { name: "Ask" }).click();
  await expect(panel.getByText("This pack has no evidence on that.")).toBeVisible();
  const result = await new AxeBuilder({ page }).include("aside").analyze();
  expect(result.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
});
