// Mirrors the API's Pydantic contracts (src/prepay/api/schemas.py). Money is USD.

export interface HistogramBin { low_pct: number; high_pct: number; upb_share: number }

export interface PoolSummary {
  pool_id: string;
  name: string;
  description: string;
  fictional: boolean;
  as_of: string;
  loans: number;
  current_upb_usd: number;
  wac_pct: number | null;
  wala_months: number | null;
  wam_months: number | null;
  average_loan_size_usd: number;
  wa_credit_score: number | null;
  wa_original_ltv_pct: number | null;
  term_mix: Record<string, number>;
  purpose_mix: Record<string, number>;
  occupancy_mix: Record<string, number>;
  region_mix: Record<string, number>;
  note_rate_histogram: HistogramBin[];
}

export interface PoolsResponse { data_class: "fictional"; notice: string; pools: PoolSummary[] }

export type ScenarioKind = "flat" | "parallel" | "custom";
export interface ScenarioIn { kind: ScenarioKind; shock_bps?: number; path_30y_pct?: number[] }

export interface MonthlyRow {
  month: string;
  market_rate_30y_pct: number;
  beginning_upb_usd: number;
  scheduled_principal_usd: number;
  voluntary_prepay_principal_usd: number;
  credit_exit_principal_usd: number;
  recoveries_received_usd: number;
  illustrative_credit_loss_usd: number;
  contractual_interest_accrued_usd: number;
  ending_upb_usd: number;
  cpr_model: number | null;
  credit_exit_rate_annualized: number | null;
  cumulative_principal_returned_fraction: number;
  out_of_support_share: number;
}

export interface Summary {
  horizon_months: number;
  cash_wal_years: number | null;
  exposure_exit_wal_years: number | null;
  principal_returned_fraction_12m: number | null;
  principal_returned_fraction_24m: number | null;
  principal_returned_fraction_horizon: number;
  contractual_interest_accrued_horizon_usd: number;
  scheduled_principal_horizon_usd: number;
  voluntary_prepay_principal_horizon_usd: number;
  recoveries_received_horizon_usd: number;
  illustrative_credit_loss_horizon_usd: number;
  ending_upb_horizon_usd: number;
  pending_recoveries_horizon_usd: number;
  max_out_of_support_share_horizon: number;
}

export type Verdict = "supported" | "extrapolating" | "unsupported";

/** ADR 0009 §7 applicability verdict over the horizon, weighted by projected balance. */
export interface Reliability {
  verdict: Verdict;
  outside_share: number;
  sparse_share: number;
  outside_share_by_feature: Record<string, number>;
  reasons: string[];
  headline: "point" | "range";
}

export interface RangeValue { min: number | null; max: number | null }

/** Spread across fitted model families: model disagreement, not a confidence interval. */
export interface ModelRange {
  models: string[];
  principal_returned_fraction_12m: RangeValue;
  principal_returned_fraction_24m: RangeValue;
  cash_wal_years: RangeValue;
  ending_upb_horizon_usd: RangeValue;
  note: string;
}

export interface ScenarioOut {
  kind: ScenarioKind;
  shock_bps: number;
  label: string;
  summary: Summary;
  monthly: MonthlyRow[];
  reliability: Reliability | null;
  model_range: ModelRange | null;
}

export interface Deltas {
  cash_wal_months: number | null;
  principal_returned_12m_pp: number | null;
  principal_returned_24m_pp: number | null;
  contractual_interest_accrued_horizon_usd: number | null;
  ending_upb_horizon_usd: number | null;
}

export interface ProjectionResponse {
  data_class: "fictional";
  notice: string;
  pool_id: string;
  as_of: string;
  model: string;
  assumptions: Record<string, string | number>;
  a: ScenarioOut;
  b: ScenarioOut | null;
  a_minus_b: Deltas | null;
  warnings: string[];
}

export interface ProjectionRequest {
  pool_id: string;
  scenario: ScenarioIn;
  compare_to: ScenarioIn | null;
  horizon_months: number;
  credit: { severity: number; recovery_lag_months: number; annual_cdr_pct: number | null };
}

export interface ScenariosResponse {
  as_of_rate_30y_pct: number;
  as_of_rate_15y_pct: number;
  standard: { kind: ScenarioKind; shock_bps: number; label: string }[];
}

export interface ApiError { error: { code: string; message: string; details: unknown[] } }

export interface Health {
  status: string;
  version: string;
  artifact_class: string;
  data_class: string;
  model: string;
  cache_warm: boolean;
  bundle_digest: string;
  project_latency_ms: { count: number; p50: number; p95: number } | null;
}

export interface MetricDefinition { label: string; unit: string; formula: string }

export interface Methodology {
  question: string;
  outcomes: Record<string, string>;
  features: { name: string; kind: string; source: string; description: string }[];
  feature_timing: string;
  model: { served: string; run_id: string; trained_on: string; selection_rule: string };
  rates: Record<string, string>;
  metrics: Record<string, MetricDefinition>;
  limitations: string[];
  data_permissions: string;
}

export interface Interval { estimate: number; low: number; high: number; kind: string }

export interface ModelMetrics {
  rows: number;
  events: { prepay: number; credit: number };
  log_loss: number;
  log_loss_interval: Interval | null;
  brier: number;
  prepay_auroc: number | null;
  prepay_ece: number;
  prepay_reliability: { mean_predicted: number; observed_rate: number; count: number }[];
  credit_average_precision: number | null;
  credit_prevalence: number;
  cpr_proxy_bias_pp: number | null;
  cpr_proxy_mae_pp: number | null;
  cpr_proxy_monthly: { month: number; cpr_model: number; cpr_observed: number }[];
}

export interface CohortHorizon {
  realized_aalen_johansen_prepay: number;
  realized_prepay_interval: { low: number; high: number; kind: string };
  raw_observed_prepay_ignoring_censoring: number;
  censored_share: number;
  models: Record<string, Record<string, { prepay: number; credit: number; prepay_error_pp: number }>>;
}

export interface ModelQuality {
  synthetic: boolean;
  notice: string;
  run_id: string;
  real_data_status: string;
  windows: Record<string, { role: string; first: string; last: string }>;
  selection: {
    rule: string;
    validation_a_log_loss: Record<string, number>;
    best: string;
    selected: string;
    calibration: { adopted: boolean; temperature?: number };
  };
  validation: Record<string, Record<string, ModelMetrics>>;
  truth_recovery: Record<string, unknown> | null;
  holdout: Record<string, {
    label: string;
    models: Record<string, ModelMetrics>;
    flags: Record<string, boolean>;
    gbm_vs_baselines: Record<string, Interval>;
  }>;
  cohort_backtests: Record<string, {
    t0: string;
    cohort_loans?: number;
    note?: string;
    horizons?: Record<string, CohortHorizon>;
  }>;
}
