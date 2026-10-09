// The whole journey in fixtures mode: Ask -> plan -> Start -> theatre -> pack -> drawer, with axe checks.
import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const KEY = process.env.E2E_RUN_KEY!; // random per test run (playwright.config.ts)

async function noSeriousA11yIssues(page: Page, where: string) {
  const result = await new AxeBuilder({ page }).analyze();
  const serious = result.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  const summary = serious.map((v) => `${v.id}: ${v.help} (${v.nodes.length}) e.g. ${v.nodes[0]?.target}`).join("\n");
  expect(serious, `${where}:\n${summary}`).toEqual([]);
}

test("brief to pack, with the evidence drawer and accessibility checks", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "See an example pack" })).toBeVisible();
  await expect(page.getByText("See the pack").first()).toBeVisible();
  await noSeriousA11yIssues(page, "Ask page");

  await page.getByLabel("Your brief").fill("Gen Z and meal prep");   // enough recorded posts for a pack
  await page.getByLabel("Run key").fill(KEY);
  await page.getByRole("button", { name: "Plan the research" }).click();
  await expect(page.getByRole("heading", { name: "Here's what I understood" })).toBeVisible();
  expect(await page.content()).not.toContain(KEY); // never in the page

  await page.getByRole("button", { name: "Start research" }).click();
  await expect(page).toHaveURL(/\/runs\/run_/);
  await expect(page.getByRole("link", { name: "Open the pack" })).toBeVisible({ timeout: 90_000 });
  // every move shows its tool and reason (a Quick run may end at its 15-call limit, without "finish")
  await expect(page.getByText("#1", { exact: true })).toBeVisible();
  expect(await page.locator("main ol > li").count()).toBeGreaterThanOrEqual(3);
  await noSeriousA11yIssues(page, "Research Theatre");

  await page.getByRole("link", { name: "Open the pack" }).click();
  await expect(page.getByRole("heading", { name: "Summary", exact: true })).toBeVisible();
  await noSeriousA11yIssues(page, "Pack page");

  await page.getByTitle("Open the evidence").first().click();
  const drawer = page.getByRole("dialog");
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole("heading").first()).toBeVisible();   // the item it opened (the fixture pack is thin)
  await noSeriousA11yIssues(page, "Evidence drawer");
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();

  await page.getByRole("button", { name: "Hand off" }).click();
  await expect(page.getByRole("button", { name: /Quick brief/ })).toBeVisible();
  await page.getByText("More: Claude and developers").click();
  await expect(page.getByRole("link", { name: /Teach Claude this research/ })).toHaveAttribute("href", /\/export\/skill$/);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();
});

test("a featured pack: summary, drawer with real posts, agent view, handoff, replay", async ({ page }) => {
  await page.goto("/packs");
  await page.getByText("Launching a snack brand in the Netherlands").first().click();
  await expect(page.getByRole("heading", { name: "Summary", exact: true })).toBeVisible();
  await noSeriousA11yIssues(page, "Featured pack page");

  await page.getByRole("button", { name: "THM-01" }).first().click();
  const drawer = page.getByRole("dialog");
  await expect(drawer.getByText(/The posts behind it/)).toBeVisible();
  await expect(drawer.getByRole("button", { name: /Copy with citation/ }).first()).toBeVisible();
  await expect(drawer.getByRole("link", { name: /source/ }).first()).toHaveAttribute("href", /^https?:\/\//);
  await noSeriousA11yIssues(page, "Drawer with real posts");
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "View as agent" }).click();
  await expect(page.getByText(/context_pack\.json · schema 1\.1/).first()).toBeVisible();
  await page.getByRole("button", { name: "View as agent" }).click();

  await page.getByRole("button", { name: "Strong only" }).click();
  await expect(page.getByText(/shown/).first()).toBeVisible();

  await page.locator("details.research > summary").click();               // V9: collapsed by default
  await page.getByRole("link", { name: "Watch how this pack was made" }).first().click();
  await page.getByRole("button", { name: /Skip to the end/ }).click();
  await expect(page.getByText(/of \d+ events · done/)).toBeVisible();   // the public copy has no cost events
  await noSeriousA11yIssues(page, "Replay");
});


test("too few posts ends on the thin screen with one-click re-plans (V1)", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Your brief").fill("Launching a snack brand in the Netherlands");  // 0 recorded posts
  await page.getByLabel("Run key").fill(KEY);
  await page.getByRole("button", { name: "Plan the research" }).click();
  await page.getByRole("button", { name: "Start research" }).click();
  await expect(page.getByRole("heading", { name: "Not enough to build a pack this time" })).toBeVisible({ timeout: 90_000 });
  await expect(page.getByRole("link", { name: "Run Standard (more sources)" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Run again with these inputs" })).toBeVisible();
  await noSeriousA11yIssues(page, "Thin screen");
  await page.getByRole("link", { name: "Run Standard (more sources)" }).click();
  await expect(page.getByLabel("Your brief")).toHaveValue("Launching a snack brand in the Netherlands");
});

test("a vague brief gets brief-specific questions with chips, then an editable plan (V3)", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Your brief").fill("snacks");
  await page.getByLabel("Run key").fill(KEY);
  await page.getByRole("button", { name: "Plan the research" }).click();
  const cards = page.locator("section[aria-labelledby=clarify] fieldset");
  await expect(cards).toHaveCount(2);
  await noSeriousA11yIssues(page, "Clarifying questions");
  await cards.nth(0).getByRole("button", { name: "Netherlands" }).click();
  await cards.nth(1).getByRole("button", { name: "Skip - let the agent decide" }).click();
  await page.getByRole("button", { name: "Plan with my answers" }).click();
  await expect(page.getByRole("heading", { name: "Adjust before you start" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Remove NL" })).toBeVisible();
  await noSeriousA11yIssues(page, "Plan with editable chips");
});

test("the brief guide opens from the info button and the template fills an empty box", async ({ page }) => {
  await page.goto("/");
  const info = page.getByRole("button", { name: "How to write a brief" });
  await expect(info).toHaveAttribute("aria-expanded", "false");
  await info.click();
  await expect(page.getByRole("heading", { name: "How to write a brief" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Key question/ })).toBeVisible();
  await noSeriousA11yIssues(page, "Brief guide");
  await page.getByRole("button", { name: "Close the guide" }).click();
  await expect(page.getByRole("heading", { name: "How to write a brief" })).toHaveCount(0);

  const brief = page.getByLabel("Your brief");
  await brief.fill("");
  await page.getByRole("button", { name: "Use the template" }).click();
  await expect(brief).toHaveValue(/^GOALS \(main first\): /);
  await expect(page.getByRole("button", { name: "Use the template" })).toBeDisabled();  // never overwrites a brief
});
