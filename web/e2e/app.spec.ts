import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import { lab, unsupportedCode } from "./served";

const ROUTES = ["/scenario-lab", "/portfolio", "/model-quality", "/methodology"];

async function waitForProjection(page: Page) {
  await expect(page.getByTestId("headline")).toBeVisible();
  await expect(page.locator("[aria-busy='true']")).toHaveCount(0);
}

test("scenario lab compares two scenarios and keeps state in the URL", async ({ page }) => {
  await page.goto("/scenario-lab");
  await expect(page.getByRole("note").first()).toContainText("Fictional portfolios");
  await waitForProjection(page);
  await expect(page.getByRole("img", { name: /rate path/i })).toBeVisible();
  await expect(page.getByRole("img", { name: /payoff speed/i })).toBeVisible();
  await expect(page.getByRole("img", { name: /Cumulative principal returned/ })).toBeVisible();
  await expect(page.getByRole("img", { name: /remaining balance/ })).toBeVisible();

  const before = await page.getByTestId("headline").innerText();
  await page.getByLabel("Scenario B", { exact: true }).selectOption("p200");
  await expect(page).toHaveURL(/b=p200/);
  await page.getByLabel("Scenario A", { exact: true }).selectOption("p-200");
  await expect(page).toHaveURL(/a=p-200/);
  await waitForProjection(page);
  await expect.poll(async () => page.getByTestId("headline").innerText()).not.toBe(before);

  // The URL alone restores the comparison.
  const second = await page.context().newPage();
  await second.goto(page.url());
  await expect(second.getByLabel("Scenario A", { exact: true })).toHaveValue("p-200");
  await expect(second.getByLabel("Scenario B", { exact: true })).toHaveValue("p200");
});

test("steppers walk the scenario grid and swap exchanges A and B", async ({ page }) => {
  await page.goto("/scenario-lab?pool=fictional-2023-high-coupon&a=flat&b=p-100&h=120");
  await waitForProjection(page);
  await page.getByRole("button", { name: "Scenario B: raise the rate shock" }).click();
  await expect(page).toHaveURL(/b=p-50/);
  await page.getByRole("button", { name: "Scenario A: lower the rate shock" }).click();
  await expect(page).toHaveURL(/a=p-50/);
  await page.getByRole("button", { name: "Scenario A: raise the rate shock" }).click();
  await page.getByRole("button", { name: "Swap scenarios A and B" }).click();
  await expect(page).toHaveURL(/a=p-50&b=flat/);
  await page.getByLabel("Scenario A", { exact: true }).selectOption("p300");
  await expect(page.getByRole("button", { name: "Scenario A: raise the rate shock" })).toBeDisabled();
  await page.getByRole("button", { name: "1 yr" }).click();
  await expect(page).toHaveURL(/h=12/);
  await expect(page.getByRole("button", { name: "1 yr" })).toHaveAttribute("aria-pressed", "true");
});

test("the active model, its assumptions and each scenario's applicability are visible", async ({ page }) => {
  await page.goto("/scenario-lab?pool=fictional-2023-high-coupon&a=flat&b=p-200&h=120");
  await waitForProjection(page);
  const context = page.getByRole("region", { name: "Active model and assumptions" });
  await expect(context).toContainText(/Active model\s*(B[0-2]|M1) /);
  await expect(context).toContainText("trained on synthetic data");
  await expect(context).toContainText("Credit exits");
  await expect(context).toContainText("rates act from month 2");
  await expect(page.getByTestId("support-banner")).toBeVisible();
  const trust = page.getByTestId("trust");
  await expect(trust).toContainText("Flat at last observed");
  await expect(trust).toContainText("Parallel −200 bp");
  await expect(trust.locator("[data-verdict]").first()).toBeVisible();
  await expect(page.getByTestId("served-rule")).toContainText("outside plus thinly supported share");
  await expect(page.getByTestId("bells")).toContainText("not a confidence interval");
});

test("custom ramp scenario and assumptions drawer (live app only)", async ({ page }) => {
  await page.goto("/scenario-lab?pool=fictional-2021-low-coupon&a=flat&b=none&h=60");
  await waitForProjection(page);
  await expect(page.getByTestId("headline")).toHaveAttribute("data-mode", /single|range/);
  await page.getByLabel("Scenario A", { exact: true }).selectOption("ramp");
  await page.getByLabel("Scenario A: target 30y rate (%)").fill("4.5");
  await expect(page).toHaveURL(/a=ramp%3A4\.50%3A12/);
  await waitForProjection(page);
  await page.getByText("Credit and rate-path assumptions").click();
  await expect(page.getByLabel(/Credit severity/)).toBeEnabled();
  await page.locator("#ledger > summary").click();
  await expect(page.getByRole("table", { name: /Monthly ledger/ })).toBeVisible();
  await page.getByText("Every served assumption").click();
  await expect(page.getByText("contract note rates are fixed")).toBeVisible();
});

test("charts are keyboard readable and drive one shared cursor", async ({ page }) => {
  await page.goto("/scenario-lab?pool=fictional-2023-high-coupon&a=flat&b=p-100&h=120");
  await waitForProjection(page);
  const chart = page.getByRole("img", { name: /Cumulative principal returned/ });
  await chart.focus();
  await page.keyboard.press("End");
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByTestId("cursor-label")).toContainText("Month 119");
  await expect(page.getByTestId("inspector-month")).toContainText("Month 119");
  await expect(page.getByTestId("principal-tip")).toBeVisible();
  await expect(page.locator("[aria-live='polite']").filter({ hasText: /Month 119/ }).first()).toContainText("%");
  await page.keyboard.press("PageDown");
  await expect(page.getByTestId("rate-read")).toContainText("Month 107");
  await page.getByLabel("Month", { exact: true }).fill("12");
  await expect(page.getByTestId("balance-read")).toContainText("Month 12");
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

test("model quality labels synthetic results, shows every model and keeps the real-data qualification", async ({ page }) => {
  await page.goto("/model-quality");
  await expect(page.getByText("Synthetic results only.")).toBeVisible();
  await expect(page.getByRole("table", { name: /Holdout metrics/ })).toContainText("B2 multinomial logistic");
  await expect(page.getByRole("table", { name: /Cumulative payoff incidence/ })).toBeVisible();
  await expect(page.getByText(/not approved as a reliable forecaster across rate regimes/)).toBeVisible();
});

test("methodology defines every metric with a unit and states the implemented applicability rule", async ({ page }) => {
  await page.goto("/methodology");
  const table = page.getByRole("table", { name: /Displayed metrics/ });
  await expect(table).toContainText("Cash weighted-average life");
  await expect(table).toContainText("years");
  await expect(table).toContainText("outside plus thinly supported share >= 20%");
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
  for (const width of [375, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 800 } });
    for (const route of ROUTES) {
      await page.goto(route);
      await page.waitForLoadState("networkidle");
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow, `${route} at ${width}px`).toBeLessThanOrEqual(1);
    }
    // Expanded tables scroll inside their own region, never the page.
    await page.goto("/scenario-lab");
    await waitForProjection(page);
    await page.locator("#full-table > summary").click();
    await page.locator("#ledger > summary").click();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, `expanded tables at ${width}px`).toBeLessThanOrEqual(1);
    await page.close();
  }
});

test("dark mode follows the system preference and the theme control overrides it", async ({ browser }) => {
  const page = await browser.newPage({ colorScheme: "dark" });
  await page.goto("/scenario-lab");
  const background = () => page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  expect(await background()).toBe("rgb(15, 19, 24)");
  await page.getByRole("button", { name: "Light", exact: true }).click();
  expect(await background()).toBe("rgb(243, 244, 246)");
  await page.getByRole("button", { name: "Auto", exact: true }).click();
  expect(await background()).toBe("rgb(15, 19, 24)");
  await page.close();
});

test("fonts are self-hosted: no third-party requests", async ({ page }) => {
  const external: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.hostname !== "127.0.0.1" && url.protocol.startsWith("http")) external.push(request.url());
  });
  await page.goto("/scenario-lab");
  await waitForProjection(page);
  expect(await page.evaluate(() => document.fonts.check('14px "Geist Variable"'))).toBe(true);
  expect(external).toEqual([]);
});

for (const route of ROUTES) {
  for (const scheme of ["light", "dark"] as const) {
    test(`no serious accessibility violations on ${route} (${scheme})`, async ({ browser }) => {
      const context = await browser.newContext({ colorScheme: scheme });
      const page = await context.newPage();
      await page.goto(route);
      await page.waitForLoadState("networkidle");
      await expect(page.locator("main [aria-busy='true']")).toHaveCount(0);
      if (route === "/scenario-lab") {
        // Audit the expanded analytical views and an open definition too.
        await page.locator("#full-table > summary").click();
        await page.locator("#ledger > summary").click();
        await page.getByRole("button", { name: /Definition: Cash weighted-average life/ }).first().click();
      }
      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
      const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(serious.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
      await context.close();
    });
  }
}

test("an unsupported scenario is range-first in both themes, with no serious accessibility violations", async ({ browser, request }) => {
  const code = await unsupportedCode(request, 120);
  test.skip(code === null, "no grid scenario is unsupported in this bundle");
  for (const scheme of ["light", "dark"] as const) {
    const context = await browser.newContext({ colorScheme: scheme });
    const page = await context.newPage();
    await page.goto(lab("flat", code as string, 120));
    await waitForProjection(page);
    await expect(page.getByTestId("headline")).toHaveAttribute("data-mode", "range");
    await expect(page.getByTestId("support-banner")).toContainText("B is unsupported");
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    expect(results.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id)).toEqual([]);
    await context.close();
  }
});
