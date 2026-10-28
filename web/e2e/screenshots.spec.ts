// Captures README screenshots from the running build (run with --project=screenshots).
import { expect, test } from "@playwright/test";

const OUT = "../docs/images";

test("capture screenshots", async ({ browser }) => {
  const shots: [string, string, { width: number; height: number }, "light" | "dark"][] = [
    ["scenario-lab", "/scenario-lab?pool=fictional-2023-high-coupon&a=flat&b=p-200&h=120", { width: 1280, height: 1500 }, "light"],
    ["scenario-lab-dark", "/scenario-lab?pool=fictional-2021-low-coupon&a=flat&b=p-200&h=120", { width: 1280, height: 1500 }, "dark"],
    ["portfolio", "/portfolio", { width: 1280, height: 1000 }, "light"],
    ["model-quality", "/model-quality", { width: 1280, height: 1700 }, "light"],
    ["scenario-lab-mobile", "/scenario-lab", { width: 390, height: 1800 }, "light"],
  ];
  for (const [name, url, viewport, colorScheme] of shots) {
    const context = await browser.newContext({ viewport, colorScheme, deviceScaleFactor: 1 });
    const page = await context.newPage();
    await page.goto(url);
    await page.waitForLoadState("networkidle");
    await expect(page.locator("main [aria-busy='true']")).toHaveCount(0);
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: false });
    await context.close();
  }
});
