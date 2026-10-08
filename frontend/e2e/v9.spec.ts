// V9 checks on a featured pack: the Summary fits the first screen, no technical words on screen,
// every strength badge explains itself, hand-off options say what they are for, phone width works.
import { expect, test } from "@playwright/test";

const SHOTS = process.env.E2E_SHOTS;   // optional folder for screenshots (never committed)
test.use({ permissions: ["clipboard-read", "clipboard-write"] });

async function openFeatured(page: import("@playwright/test").Page) {
  await page.goto("/packs");
  await page.getByText("Launching a snack brand in the Netherlands").first().click();
  await expect(page.getByRole("heading", { name: "Summary", exact: true })).toBeVisible();
}

test("the first screen on a laptop shows the whole Summary", async ({ page }) => {
  await openFeatured(page);
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/v9-laptop.png` });
  const summary = page.locator("section[aria-labelledby=summary]");
  const box = await summary.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.y + box!.height).toBeLessThanOrEqual(900);               // 1300x900 (playwright.config.ts)
  await expect(summary.getByText("What we heard most clearly")).toBeVisible();
  await expect(summary.getByText("Your plan: do this first")).toBeVisible();
});

test("no technical words on screen; every badge has a plain tooltip", async ({ page }) => {
  await openFeatured(page);
  const text = await page.locator("main").innerText();
  expect(text).not.toMatch(/\btokens?\b/i);
  expect(text).not.toMatch(/JSON schema/i);
  expect(text).not.toMatch(/evidence ids?\b/i);
  const badges = page.locator("[data-badge=confidence]");
  expect(await badges.count()).toBeGreaterThan(5);
  for (const title of await badges.evaluateAll((els) => els.map((e) => e.getAttribute("title") ?? ""))) {
    expect(title).toMatch(/Good enough to:/);
  }
});

test("hand-off options say what they are for, how long, and what is inside", async ({ page }) => {
  await openFeatured(page);
  await page.getByRole("button", { name: "Hand off" }).click();
  const dialog = page.getByRole("dialog");
  for (const name of ["Quick brief", "Brief for your AI writer", "Full report", "Content calendar"]) {
    await expect(dialog.locator("button, a").filter({ hasText: name }).first()).toBeVisible();
  }
  await expect(dialog.getByText("half a page")).toBeVisible();
  await expect(dialog.getByText(/about \d+ pages?/).first()).toBeVisible();
  await dialog.getByRole("button", { name: /Quick brief/ }).click();
  await expect(dialog.getByRole("status")).toHaveText(/Quick brief copied - paste it into your AI tool/);
});

test("phone width: one column, a sections menu, no sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openFeatured(page);
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/v9-phone.png`, fullPage: false });
  await expect(page.getByText("Sections", { exact: true })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});
