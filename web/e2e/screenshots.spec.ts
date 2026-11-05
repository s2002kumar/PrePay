// Captures README and review screenshots from the running build (run with --project=screenshots).
import { expect, type Page, test } from "@playwright/test";

const OUT = "../docs/images";
const REVIEW = "../docs/reviews/visual-milestone";
const DEFAULT = "/scenario-lab?pool=fictional-2023-high-coupon&a=flat&b=p-100&h=120";

async function settle(page: Page) {
  await page.waitForLoadState("networkidle");
  await expect(page.locator("main [aria-busy='true']")).toHaveCount(0);
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(300);
}

test("capture README screenshots", async ({ browser }) => {
  const shots: [string, string, { width: number; height: number }, "light" | "dark"][] = [
    ["scenario-lab", DEFAULT, { width: 1440, height: 1000 }, "light"],
    ["scenario-lab-dark", DEFAULT, { width: 1440, height: 1000 }, "dark"],
    ["scenario-lab-mobile", DEFAULT, { width: 390, height: 1600 }, "light"],
    ["portfolio", "/portfolio", { width: 1440, height: 1000 }, "light"],
    ["model-quality", "/model-quality", { width: 1440, height: 1700 }, "light"],
  ];
  for (const [name, url, viewport, colorScheme] of shots) {
    const context = await browser.newContext({ viewport, colorScheme, deviceScaleFactor: 1 });
    const page = await context.newPage();
    await page.goto(url);
    await settle(page);
    await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: false });
    await context.close();
  }
});

test("capture the visual-milestone review set", async ({ browser }) => {
  test.skip(!process.env.PREPAY_REVIEW_SHOTS, "set PREPAY_REVIEW_SHOTS=1 to refresh docs/reviews/visual-milestone");
  const shots: [string, string, number, "light" | "dark", ((p: Page) => Promise<void>)?][] = [
    ["after-desktop-light", DEFAULT, 1440, "light"],
    ["after-desktop-dark", DEFAULT, 1440, "dark"],
    ["after-mobile-light", DEFAULT, 390, "light"],
    ["after-mobile-dark", DEFAULT, 390, "dark"],
    ["after-range-first-desktop-light", "/scenario-lab?pool=fictional-2023-high-coupon&a=flat&b=p300&h=120", 1440, "light"],
    [
      "after-analysis-open-desktop-dark",
      DEFAULT,
      1440,
      "dark",
      async (page) => {
        await page.locator("#full-table > summary").click();
        await page.locator("#ledger > summary").click();
        await page.getByRole("button", { name: "Voluntary payoffs" }).click();
      },
    ],
  ];
  for (const [name, url, width, colorScheme, act] of shots) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, colorScheme, deviceScaleFactor: 1 });
    const page = await context.newPage();
    await page.goto(url);
    await settle(page);
    if (act) await act(page);
    await page.screenshot({ path: `${REVIEW}/${name}.jpg`, fullPage: true, type: "jpeg", quality: 74 });
    await context.close();
  }
});
