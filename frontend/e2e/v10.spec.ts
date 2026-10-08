// V10 Ask this pack (fake model, recorded data): suggested questions, a cited answer that opens a real
// post, and a plain "no evidence" answer.
import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("ask a featured pack: citations open real posts; no evidence is said plainly", async ({ page }) => {
  await page.goto("/packs");
  await page.getByText("Launching a snack brand in the Netherlands").first().click();
  await page.getByRole("button", { name: "Ask this pack" }).click();
  const panel = page.getByRole("complementary", { name: "Ask this pack" });
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
