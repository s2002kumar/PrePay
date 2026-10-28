import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const ROUTES = ["/scenario-lab", "/portfolio", "/model-quality", "/methodology"];

async function waitForProjection(page: import("@playwright/test").Page) {
  await expect(page.getByText("Cash weighted-average life")).toBeVisible();
  await expect(page.locator("[aria-busy='true']")).toHaveCount(0);
}

test("scenario lab compares two scenarios and keeps state in the URL", async ({ page }) => {
  await page.goto("/scenario-lab");
  await expect(page.getByRole("note").first()).toContainText("Fictional portfolios");
  await waitForProjection(page);
  await expect(page.getByRole("img", { name: /rate path/i })).toBeVisible();
  await expect(page.getByRole("img", { name: /Model CPR/ })).toBeVisible();
  await expect(page.getByRole("img", { name: /Cumulative principal/ })).toBeVisible();

  const before = await page.locator(".tile .value").first().innerText();
  await page.getByLabel("Scenario B", { exact: true }).selectOption("p200");
  await expect(page).toHaveURL(/b=p200/);
  await expect(page.locator(".tile .detail").first()).toContainText("A−B");
  await page.getByLabel("Scenario A", { exact: true }).selectOption("p-200");
  await expect(page).toHaveURL(/a=p-200/);
  await expect.poll(async () => page.locator(".tile .value").first().innerText()).not.toBe(before);

  // The URL alone restores the comparison.
  const shared = page.url();
  const second = await page.context().newPage();
  await second.goto(shared);
  await expect(second.getByLabel("Scenario A", { exact: true })).toHaveValue("p-200");
  await expect(second.getByLabel("Scenario B", { exact: true })).toHaveValue("p200");
});

test("custom ramp scenario and assumptions drawer", async ({ page }) => {
  await page.goto("/scenario-lab?pool=fictional-2021-low-coupon&a=flat&b=none&h=60");
  await waitForProjection(page);
  await page.getByLabel("Scenario A", { exact: true }).selectOption("ramp");
  await page.getByLabel("Scenario A: target 30y rate (%)").fill("4.5");
  await expect(page).toHaveURL(/a=ramp%3A4\.50%3A12/);
  await waitForProjection(page);
  await page.getByText("Assumptions and table view").click();
  await expect(page.getByRole("table", { name: /Monthly ledger/ })).toBeVisible();
  await expect(page.getByText("contract note rates are fixed")).toBeVisible();
});

test("charts are keyboard readable", async ({ page }) => {
  await page.goto("/scenario-lab");
  await waitForProjection(page);
  const chart = page.getByRole("img", { name: /rate path/i });
  await chart.focus();
  await page.keyboard.press("End");
  await page.keyboard.press("ArrowLeft");
  await expect(page.locator(".tooltip")).toBeVisible();
  await expect(page.locator("[aria-live='polite']").filter({ hasText: /Parallel|Flat/ }).first()).toContainText("%");
});

test("portfolio explorer hands a pool to the scenario lab", async ({ page }) => {
  await page.goto("/portfolio");
  await page.getByRole("button", { name: /2013 pool/ }).click();
  await expect(page.getByRole("heading", { name: /Seasoned 2013 pool/ })).toBeVisible();
  await expect(page.getByRole("list", { name: "Coupon distribution" })).toBeVisible();
  await page.getByRole("button", { name: /Project this pool/ }).click();
  await expect(page).toHaveURL(/scenario-lab\?pool=fictional-2013-seasoned/);
  await waitForProjection(page);
});

test("model quality labels synthetic results and shows every model", async ({ page }) => {
  await page.goto("/model-quality");
  await expect(page.getByText("Synthetic results only.")).toBeVisible();
  await expect(page.getByRole("table", { name: /Holdout metrics/ })).toContainText("B2 multinomial logistic");
  await expect(page.getByRole("table", { name: /Cumulative payoff incidence/ })).toBeVisible();
});

test("methodology defines every metric with a unit", async ({ page }) => {
  await page.goto("/methodology");
  const table = page.getByRole("table", { name: /Displayed metrics/ });
  await expect(table).toContainText("Cash weighted-average life");
  await expect(table).toContainText("years");
  await expect(page.getByText(/no real-data result is published here/)).toBeVisible();
});

test("service errors are shown, not hidden", async ({ page }) => {
  await page.route("**/api/project", (route) =>
    route.fulfill({ status: 500, contentType: "application/json",
      body: JSON.stringify({ error: { code: "internal_error", message: "unexpected error", details: [] } }) }),
  );
  await page.goto("/scenario-lab");
  await expect(page.getByRole("alert")).toContainText("unexpected error");
});

test("mobile layout has no horizontal page scroll", async ({ browser }) => {
  const page = await browser.newPage({ viewport: { width: 375, height: 800 } });
  for (const route of ROUTES) {
    await page.goto(route);
    await page.waitForLoadState("networkidle");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, route).toBeLessThanOrEqual(1);
  }
  await page.close();
});

test("dark mode follows the system preference", async ({ browser }) => {
  const page = await browser.newPage({ colorScheme: "dark" });
  await page.goto("/scenario-lab");
  const background = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  expect(background).toBe("rgb(13, 13, 13)");
  await page.close();
});

for (const route of ROUTES) {
  for (const scheme of ["light", "dark"] as const) {
    test(`no serious accessibility violations on ${route} (${scheme})`, async ({ browser }) => {
      const context = await browser.newContext({ colorScheme: scheme });
      const page = await context.newPage();
      await page.goto(route);
      await page.waitForLoadState("networkidle");
      await expect(page.locator("main [aria-busy='true']")).toHaveCount(0);
      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
      const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(serious.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
      await context.close();
    });
  }
}
