// The static site (GitHub Pages) against the live API on the same bundle: same numbers, same text.
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const LIVE = "http://127.0.0.1:8765";
const CASES = [
  "pool=fictional-2023-high-coupon&a=flat&b=p-100&h=120",
  "pool=fictional-2021-low-coupon&a=p200&b=p-300&h=24",
  "pool=fictional-2013-seasoned&a=p-50&b=none&h=360",
  "pool=fictional-2020-15-year&a=p250&b=flat&h=60",
  "pool=fictional-2023-high-coupon&a=flat&b=p300&h=240",
];

async function projected(page: Page) {
  await expect(page.getByTestId("headline")).toBeVisible();
  await expect(page.locator("[aria-busy='true']")).toHaveCount(0);
}

/** Every region that carries numbers: outcome, tables, inspector, drivers, trust, context. */
async function numbers(page: Page): Promise<string[]> {
  for (const id of ["full-table", "ledger"]) await page.locator(`#${id} > summary`).click();
  return page
    .locator("[data-testid='headline'], [data-testid='bells'], [data-testid='consequence'], [data-testid='support-banner'], table, [data-testid='inspector'], .driver-read, [data-testid='trust'], [data-testid='composition-identity'], [data-testid='ledger-identity'], .context")
    .allInnerTexts();
}

for (const query of CASES) {
  test(`static site shows exactly what the live API computes (${query})`, async ({ page, browser }) => {
    await page.goto(`scenario-lab?${query}`);
    await projected(page);
    const live = await browser.newPage();
    await live.goto(`${LIVE}/scenario-lab?${query}`);
    await projected(live);
    const [mine, theirs] = [await numbers(page), await numbers(live)];
    expect(mine.length).toBeGreaterThan(8);
    expect(mine).toEqual(theirs);
    await live.close();
  });
}

test("every precomputed scenario loads, steppers stay on the grid and custom inputs are not offered", async ({ page }) => {
  await page.goto("scenario-lab?pool=fictional-2021-low-coupon&a=flat&b=none&h=12");
  await projected(page);
  const select = page.getByLabel("Scenario A", { exact: true });
  const options = await select.locator("option").evaluateAll((nodes) => nodes.map((n) => (n as HTMLOptionElement).value));
  expect(options).not.toContain("ramp");
  expect(options).toHaveLength(13);
  for (const code of options) {
    await select.selectOption(code);
    await expect(page).toHaveURL(new RegExp(`a=${code}(&|$)`));
    await projected(page);
    await expect(page.getByRole("alert")).toHaveCount(0);
  }
  // The last option is +300 bp: the stepper cannot leave the grid.
  await expect(page.getByRole("button", { name: "Scenario A: raise the rate shock" })).toBeDisabled();
  await page.getByRole("button", { name: "Scenario A: lower the rate shock" }).click();
  await expect(page).toHaveURL(/a=p250/);
  await projected(page);
  await page.getByText("Credit and rate-path assumptions").click();
  await expect(page.getByText(/This public site holds precomputed results only/)).toBeVisible();
  await expect(page.getByLabel(/Credit severity/)).toBeDisabled();
});

test("deep links, navigation and the fictional notice work under the site's path", async ({ page }) => {
  for (const route of ["portfolio", "model-quality", "methodology", "scenario-lab"]) {
    const response = await page.goto(route);
    expect(response?.status(), route).toBe(200);
    await expect(page.getByRole("note").first()).toContainText("Fictional portfolios");
  }
  await page.getByRole("link", { name: "Portfolio" }).click();
  await expect(page).toHaveURL(/\/PrePay\/portfolio$/);
  await page.getByRole("button", { name: /Project this pool/ }).click();
  await expect(page).toHaveURL(/\/PrePay\/scenario-lab\?pool=/);
  await projected(page);
  await page.goto("methodology");
  await expect(page.getByText(/Static site \(precomputed API responses\)/)).toBeVisible();
});

test("fonts are served by the site itself", async ({ page }) => {
  const hosts = new Set<string>();
  page.on("request", (r) => hosts.add(new URL(r.url()).host));
  await page.goto("scenario-lab");
  await projected(page);
  expect(await page.evaluate(() => document.fonts.check('14px "Geist Variable"'))).toBe(true);
  expect([...hosts]).toHaveLength(1);
  const license = await page.request.get("licenses/geist-OFL.txt");
  expect(license.status()).toBe(200);
  expect(await license.text()).toContain("SIL Open Font License");
});

for (const scheme of ["light", "dark"] as const) {
  test(`static scenario lab has no serious accessibility violations (${scheme})`, async ({ browser, baseURL }) => {
    const context = await browser.newContext({ colorScheme: scheme, ...(baseURL ? { baseURL } : {}) });
    const page = await context.newPage();
    await page.goto("scenario-lab");
    await projected(page);
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(serious.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
    await context.close();
  });
}
