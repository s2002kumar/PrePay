// Every number the Scenario Lab draws, checked against the API response for the same inputs.
// Raw values ride on data attributes; displayed text is checked against the unit-tested formatters.
import { expect, type Locator, type Page, test } from "@playwright/test";

import { pct, signedPp, signedUsd, signedYears, usd, usdFull } from "../src/format";
import type { MonthlyRow } from "../src/types";
import { lab, served, unsupportedCode } from "./served";

const TOL = 1e-9;

async function open(page: Page, url: string) {
  await page.goto(url);
  await expect(page.getByTestId("headline")).toBeVisible();
  await expect(page.locator("[aria-busy='true']")).toHaveCount(0);
}

async function num(locator: Locator, attr: string): Promise<number> {
  const v = await locator.getAttribute(attr);
  expect(v, `${attr} present`).not.toBeNull();
  expect(v, `${attr} non-empty`).not.toBe("");
  return Number(v);
}

const sum = (rows: MonthlyRow[], f: (r: MonthlyRow) => number) => rows.reduce((s, r) => s + f(r), 0);

test("headline, side-by-side dots and the full table equal the served response, with B − A = −(A − B)", async ({ page, request }) => {
  const body = await served(request, "flat", "p-100", 120);
  const d = body.a_minus_b;
  const b = body.b;
  if (!d || !b) throw new Error("expected a comparison");
  await open(page, lab("flat", "p-100", 120));

  // Headline: the served WAL delta, sign flipped, in years.
  const wal = -(d.cash_wal_months ?? 0) / 12;
  const headline = page.getByTestId("headline");
  if (body.a.reliability?.headline !== "range" && b.reliability?.headline !== "range") {
    expect(await num(headline.locator(".big"), "data-raw")).toBeCloseTo(wal, 12);
    expect(wal).toBeCloseTo((b.summary.cash_wal_years ?? 0) - (body.a.summary.cash_wal_years ?? 0), 9);
    await expect(headline.locator(".big")).toHaveText(`${Math.abs(wal).toFixed(2)} years ${wal < 0 ? "sooner" : "later"}`);
  }

  const bells = page.getByTestId("bells");
  const checks: [string, number | null, number | null, number | null, string][] = [
    ["cash_wal", body.a.summary.cash_wal_years, b.summary.cash_wal_years, wal, signedYears(wal)],
    ["returned_24m", body.a.summary.principal_returned_fraction_24m, b.summary.principal_returned_fraction_24m, -(d.principal_returned_24m_pp ?? 0), signedPp(-(d.principal_returned_24m_pp ?? 0))],
    ["ending_upb", body.a.summary.ending_upb_horizon_usd, b.summary.ending_upb_horizon_usd, -(d.ending_upb_horizon_usd ?? 0), signedUsd(-(d.ending_upb_horizon_usd ?? 0))],
    ["interest", body.a.summary.contractual_interest_accrued_horizon_usd, b.summary.contractual_interest_accrued_horizon_usd, -(d.contractual_interest_accrued_horizon_usd ?? 0), signedUsd(-(d.contractual_interest_accrued_horizon_usd ?? 0))],
  ];
  for (const [metric, a, bv, delta, text] of checks) {
    const bell = bells.locator(`[data-metric='${metric}']`);
    expect(await num(bell, "data-a"), `${metric} A`).toBe(a);
    expect(await num(bell, "data-b"), `${metric} B`).toBe(bv);
    expect(await num(bell, "data-delta"), `${metric} B − A`).toBeCloseTo(delta ?? NaN, 12);
    await expect(bell.locator(".bell-delta strong")).toHaveText(text);
    // Same sign as the summaries' own difference: B − A, not A − B.
    if (a !== null && bv !== null && Math.abs(bv - a) > 1e-9) expect(Math.sign(delta ?? 0)).toBe(Math.sign(bv - a));
  }
  await expect(bells.locator("[data-metric='ending_upb']")).toContainText("Still owed at month 120");

  // The full table (A's analytical view).
  await page.locator("#full-table > summary").click();
  const table = page.locator("#full-table table");
  const row = (key: string) => table.locator(`tr[data-key='${key}']`);
  expect(await num(row("ret12"), "data-delta")).toBe(-(d.principal_returned_12m_pp ?? 0));
  expect(await num(row("ret24"), "data-delta")).toBe(-(d.principal_returned_24m_pp ?? 0));
  expect(await num(row("retH"), "data-delta")).toBeCloseTo(
    (b.summary.principal_returned_fraction_horizon - body.a.summary.principal_returned_fraction_horizon) * 100, 12);
  expect(await num(row("exit_wal"), "data-delta")).toBeCloseTo((b.summary.exposure_exit_wal_years ?? 0) - (body.a.summary.exposure_exit_wal_years ?? 0), 12);
  expect(await num(row("exits"), "data-a")).toBeCloseTo(sum(body.a.monthly, (r) => r.credit_exit_principal_usd), 6);
  expect(await num(row("recov"), "data-a")).toBe(body.a.summary.recoveries_received_horizon_usd);
  await expect(row("residual")).toContainText("$0.00");
  for (const [key, range] of [["cash_wal", body.a.model_range?.cash_wal_years], ["owed", body.a.model_range?.ending_upb_horizon_usd]] as const) {
    if (range?.min != null && range.max != null) await expect(row(key)).toContainText("–");
  }

  // Model families are named once each.
  for (const side of [body.a, b]) {
    const models = side.model_range?.models ?? [];
    expect(new Set(models).size, "unique model families").toBe(models.length);
  }
});

test("the balance composition and the ledger add back to today's balance", async ({ page, request }) => {
  const body = await served(request, "flat", "p-100", 120);
  await open(page, lab("flat", "p-100", 120));
  for (const side of ["a", "b"] as const) {
    const s = body[side];
    if (!s) continue;
    const b0 = s.monthly[0]?.beginning_upb_usd ?? 0;
    const comp = page.getByTestId("composition");
    const get = async (key: string) => num(comp.locator(`tr[data-key='${key}']`), `data-${side}`);
    const sched = await get("sched");
    const pay = await get("pay");
    const credit = await get("credit");
    const owed = await get("owed");
    expect(sched).toBe(s.summary.scheduled_principal_horizon_usd);
    expect(pay).toBe(s.summary.voluntary_prepay_principal_horizon_usd);
    expect(owed).toBe(s.summary.ending_upb_horizon_usd);
    expect(credit).toBeCloseTo(sum(s.monthly, (r) => r.credit_exit_principal_usd), 6);
    // Exposure identity: B0 = scheduled + payoffs + credit exits + still owed.
    expect(Math.abs(b0 - sched - pay - credit - owed) / b0).toBeLessThan(TOL);
    // Principal cash = the served cumulative fraction × B0.
    expect((await get("cash")) / b0).toBeCloseTo(s.summary.principal_returned_fraction_horizon, 10);
    // Pending exits × (1 − severity) = the served pending recoveries.
    expect((await get("pending")) * (1 - 0.35)).toBeCloseTo(s.summary.pending_recoveries_horizon_usd, 4);
    // Served monthly sums equal the served summary sums.
    expect(sum(s.monthly, (r) => r.scheduled_principal_usd)).toBeCloseTo(s.summary.scheduled_principal_horizon_usd, 4);
    expect(sum(s.monthly, (r) => r.contractual_interest_accrued_usd)).toBeCloseTo(s.summary.contractual_interest_accrued_horizon_usd, 4);
  }
  await expect(page.getByTestId("composition-identity")).toContainText("A $0.00 · B $0.00");
  const firstA = page.getByTestId("composition").locator("tr[data-key='sched'] td").first();
  await expect(firstA).toHaveText(usd(body.a.summary.scheduled_principal_horizon_usd));

  // Ledger: every served row, totals in whole dollars, and the identity.
  await page.locator("#ledger > summary").click();
  const ledger = page.getByRole("table", { name: /Monthly ledger, scenario A/ });
  await expect(ledger.locator("tbody tr")).toHaveCount(body.a.monthly.length);
  const total = ledger.locator("tfoot tr");
  await expect(total).toContainText(usdFull(sum(body.a.monthly, (r) => r.scheduled_principal_usd)));
  await expect(total).toContainText(usdFull(sum(body.a.monthly, (r) => r.voluntary_prepay_principal_usd)));
  await expect(total).toContainText(usdFull(body.a.summary.ending_upb_horizon_usd));
  const r60 = body.a.monthly[59] as MonthlyRow;
  await expect(ledger.locator("tbody tr").nth(59)).toContainText(usdFull(r60.voluntary_prepay_principal_usd));
  await expect(page.getByTestId("ledger-identity")).toContainText("= $0.00");
  await page.getByRole("button", { name: /^B · / }).click();
  await expect(page.getByRole("table", { name: /Monthly ledger, scenario B/ }).locator("tfoot tr")).toContainText(
    usdFull(body.b?.summary.ending_upb_horizon_usd ?? 0));
});

test("the inspector and the chart tooltip read the served month", async ({ page, request }) => {
  const body = await served(request, "flat", "p-100", 120);
  const b = body.b;
  if (!b) throw new Error("expected B");
  await open(page, lab("flat", "p-100", 120));
  const inspector = page.getByTestId("inspector");
  await expect(inspector).toHaveAttribute("data-month", "24");
  const ra = body.a.monthly[23] as MonthlyRow;
  const rb = b.monthly[23] as MonthlyRow;
  const fields: (keyof MonthlyRow)[] = [
    "market_rate_30y_pct", "cpr_model", "beginning_upb_usd", "scheduled_principal_usd", "voluntary_prepay_principal_usd",
    "credit_exit_principal_usd", "recoveries_received_usd", "illustrative_credit_loss_usd", "contractual_interest_accrued_usd",
    "ending_upb_usd", "cumulative_principal_returned_fraction", "out_of_support_share",
  ];
  for (const f of fields) {
    const tr = inspector.locator(`tr[data-key='${f}']`);
    expect(await num(tr, "data-a"), `A ${f}`).toBe(ra[f]);
    expect(await num(tr, "data-b"), `B ${f}`).toBe(rb[f]);
  }
  await expect(inspector.locator("tr[data-key='voluntary_prepay_principal_usd'] td").nth(2)).toHaveText(
    signedUsd(rb.voluntary_prepay_principal_usd - ra.voluntary_prepay_principal_usd));
  await expect(inspector.locator("tr[data-key='cumulative_principal_returned_fraction'] td").nth(2)).toHaveText(
    signedPp((rb.cumulative_principal_returned_fraction - ra.cumulative_principal_returned_fraction) * 100));
  await expect(page.getByTestId("inspector-identity")).toContainText("A $0.00 · B $0.00");
  // Selecting a row shows the served formula.
  await inspector.getByRole("button", { name: "Voluntary payoffs" }).click();
  await expect(page.getByTestId("inspector-definition")).toContainText("PP_t = p_t x (B_t - SP_t)");

  // Pointer on the chart: the tooltip and inspector move to the same month and show served values.
  const svg = page.getByTestId("principal-svg").locator("svg");
  const box = await svg.boundingBox();
  if (!box) throw new Error("no chart box");
  await page.mouse.move(box.x + 52 + (box.width - 52 - 74) * 0.5, box.y + box.height / 2);
  const tip = page.getByTestId("principal-tip");
  await expect(tip).toBeVisible();
  const m = await num(tip, "data-month");
  await expect(inspector).toHaveAttribute("data-month", String(m));
  const row = body.a.monthly[m - 1] as MonthlyRow;
  expect(await num(tip, "data-a")).toBe(row.cumulative_principal_returned_fraction);
  await expect(tip).toContainText(pct(row.cumulative_principal_returned_fraction));

  await page.getByRole("button", { name: "US dollars" }).click();
  await page.mouse.move(box.x + 52 + (box.width - 52 - 74) * 0.5, box.y + box.height / 2 + 1);
  const b0 = body.a.monthly[0]?.beginning_upb_usd ?? 0;
  const cash = sum(body.a.monthly.slice(0, m), (r) => r.scheduled_principal_usd + r.voluntary_prepay_principal_usd + r.recoveries_received_usd);
  expect(await num(tip, "data-a")).toBeCloseTo(cash, 4);
  expect((await num(tip, "data-a")) / b0).toBeCloseTo(row.cumulative_principal_returned_fraction, 10);
});

test("horizon-dependent numbers follow the horizon; cash WAL is full life", async ({ page, request }) => {
  const at120 = await served(request, "flat", "p-100", 120);
  for (const h of [24, 360]) {
    const body = await served(request, "flat", "p-100", h);
    const months = body.a.summary.horizon_months;
    expect(months).toBe(body.a.monthly.length);
    await open(page, lab("flat", "p-100", h));
    const bells = page.getByTestId("bells");
    await expect(bells.locator("[data-metric='ending_upb']")).toContainText(`Still owed at month ${months}`);
    expect(await num(bells.locator("[data-metric='ending_upb']"), "data-a")).toBe(body.a.summary.ending_upb_horizon_usd);
    expect(await num(bells.locator("[data-metric='interest']"), "data-a")).toBe(body.a.summary.contractual_interest_accrued_horizon_usd);
    await expect(bells.locator("[data-metric='interest']")).toContainText(`months 1–${months}`);
    // Full-life metrics do not move with the horizon.
    expect(body.a.summary.cash_wal_years).toBe(at120.a.summary.cash_wal_years);
    expect(await num(bells.locator("[data-metric='cash_wal']"), "data-a")).toBe(at120.a.summary.cash_wal_years);
    await expect(bells.locator("[data-metric='cash_wal']")).toContainText("full life");
    if (h === 360) await expect(page.getByTestId("horizon-note")).toContainText(`Months 1–${months}: the pool's last scheduled payment`);
  }
});

test("principal cash over time: A and B share one y-axis", async ({ page }) => {
  await open(page, lab("flat", "p-200", 120));
  await page.getByRole("button", { name: "Cash over time" }).click();
  const ya = await num(page.getByTestId("cash-a"), "data-ymax");
  const yb = await num(page.getByTestId("cash-b"), "data-ymax");
  expect(ya).toBe(yb);
  expect(ya).toBeGreaterThan(0);
});

test("an unsupported scenario leads with the model-family range", async ({ page, request }) => {
  const code = await unsupportedCode(request, 120);
  test.skip(code === null, "no grid scenario is unsupported in this bundle");
  const body = await served(request, "flat", code as string, 120);
  await open(page, lab("flat", code as string, 120));
  const headline = page.getByTestId("headline");
  await expect(headline).toHaveAttribute("data-mode", "range");
  const r = body.b?.model_range?.cash_wal_years;
  const big = headline.locator(".big[data-side='b']");
  expect(await num(big, "data-min")).toBe(r?.min);
  expect(await num(big, "data-max")).toBe(r?.max);
  await expect(page.getByTestId("support-banner")).toHaveClass(/crit/);
  await expect(page.getByTestId("bells").locator(".dot.b.hollow").first()).toBeVisible();
  await expect(page.getByTestId("principal-chart")).toContainText("unsupported: dashed");
  await expect(page.getByTestId("consequence")).toHaveCount(0);
  const card = page.getByTestId("trust").locator("[data-side='b']");
  await expect(card).toHaveAttribute("data-verdict", "unsupported");
  expect(await num(card, "data-outside")).toBe(body.b?.reliability?.outside_share);
});

test("the support gauge draws the thresholds the served rule states", async ({ page }) => {
  await open(page, lab("flat", "p-100", 120));
  const rule = await page.getByTestId("served-rule").innerText();
  expect(rule).toContain("outside share >= 25%");
  expect(rule).toContain("outside share >= 5%");
  expect(rule).toContain("outside plus thinly supported share >= 20%");
  await expect(page.locator(".gauge-scale").first()).toContainText("5%20%25%");
});

