// Every displayed number carries a unit. Values are rounded only here, at display time.

const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

export function usd(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "n/a";
  const sign = value < 0 ? "-" : "";
  return `${sign}$${compact.format(Math.abs(value))}`;
}

export function usdFull(value: number): string {
  return value.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

export function pct(fraction: number | null | undefined, digits = 1): string {
  if (fraction === null || fraction === undefined || !Number.isFinite(fraction)) return "n/a";
  return `${(fraction * 100).toFixed(digits)}%`;
}

export function ratePct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "n/a";
  return `${value.toFixed(digits)}%`;
}

export function years(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "n/a";
  return `${value.toFixed(2)} yr`;
}

export function months(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "n/a";
  return `${value.toFixed(digits)} mo`;
}

export function signed(value: number | null | undefined, unit: string, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "n/a";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "±";
  return `${sign}${Math.abs(value).toFixed(digits)} ${unit}`;
}

export function signedUsd(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "n/a";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "±";
  return `${sign}$${compact.format(Math.abs(value))}`;
}

export function num(value: number | null | undefined, digits = 4): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "n/a";
  return value.toFixed(digits);
}

/** Display names of the model families (keys are the API's family names). */
export const MODEL_NAMES: Record<string, string> = {
  B0_psa: "B0 PSA benchmark",
  B1_lookup: "B1 age × incentive lookup",
  B2_logistic: "B2 multinomial logistic",
  M1_lightgbm: "M1 LightGBM",
  selected: "Selected (as sealed)",
};

export function modelName(family: string): string {
  return MODEL_NAMES[family] ?? family;
}
