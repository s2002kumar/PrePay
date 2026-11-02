// The static site (GitHub Pages) against the live API on the same bundle: same numbers, same text.
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const LIVE = "http://127.0.0.1:8765";
const CASES = [
  "pool=fictional-2023-high-coupon&a=flat&b=p-100&h=120",
  "pool=fictional-2021-low-coupon&a=p200&b=p-300&h=24",
  "pool=fictional-2013-seasoned&a=p-50&b=none&h=360",
  "pool=fictional-2020-15-year&a=p250&b=flat&h=60",
];

async function projected(page: Page) {
  await expect(page.getByText("Cash weighted-average life", { exact: true })).toBeVisible();
  await expect(page.locator("[aria-busy='true']")).toHaveCount(0);
}

async function numbers(page: Page): Promise<string[]> {
  return page.locator(".context, .comparison, .tile, table").allInnerTexts();
}

for (const query of CASES) {
  test(`static site shows exactly what the live API computes (${query})`, async ({ page, browser }) => {
    await page.goto(`scenario-lab?${query}`);
    await projected(page);
    const live = await browser.newPage();
    await live.goto(`${LIVE}/scenario-lab?${query}`);
    await projected(live);
    // Open the assumptions drawer on both so the monthly ledger table is compared too.
    for (const p of [page, live]) await p.getByText("Assumptions and table view").click();
    expect(await numbers(page)).toEqual(await numbers(live));
    await live.close();
  });
}

test("every precomputed scenario loads and custom paths are not offered", async ({ page }) => {
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
  await page.getByText("Assumptions and table view").click();
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

test("static scenario lab has no serious accessibility violations", async ({ page }) => {
  await page.goto("scenario-lab");
  await projected(page);
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
});
