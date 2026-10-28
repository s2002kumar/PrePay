"""Definitions served by ``GET /api/methodology``: every displayed number has a unit and formula."""

from __future__ import annotations

from typing import Any

from prepay.features.spec import FEATURES

METRICS: dict[str, dict[str, str]] = {
    "scheduled_principal_usd": {
        "label": "Scheduled principal",
        "unit": "USD per month",
        "formula": "SP_t = min(B_t, max(0, A_t - I_t)), level payment A_t on remaining term",
    },
    "voluntary_prepay_principal_usd": {
        "label": "Voluntary payoff principal",
        "unit": "USD per month",
        "formula": "PP_t = p_t x (B_t - SP_t), p_t = modeled full-payoff probability",
    },
    "credit_exit_principal_usd": {
        "label": "Credit-disposition exposure exit",
        "unit": "USD per month",
        "formula": "DC_t = d_t x (B_t - SP_t); an exposure exit, not cash received",
    },
    "recoveries_received_usd": {
        "label": "Illustrative recoveries",
        "unit": "USD per month",
        "formula": "RC_{t+L} = (1 - severity) x DC_t, L = recovery lag",
    },
    "illustrative_credit_loss_usd": {
        "label": "Illustrative credit loss",
        "unit": "USD per month",
        "formula": "severity x DC_t, recognized at t+L; an assumption, not an estimate",
    },
    "contractual_interest_accrued_usd": {
        "label": "Contractual interest accrued",
        "unit": "USD per month",
        "formula": "I_t = B_t x note rate / 12; accrued, not necessarily collected",
    },
    "ending_upb_usd": {
        "label": "Modeled remaining UPB",
        "unit": "USD",
        "formula": "B_{t+1} = B_t - SP_t - PP_t - DC_t",
    },
    "cpr_model": {
        "label": "Model CPR (full payoffs only)",
        "unit": "fraction per year",
        "formula": "1 - (1 - SMM_t)^12, SMM_t = sum(PP_t) / sum(B_t - SP_t); curtailments excluded",
    },
    "cumulative_principal_returned_fraction": {
        "label": "Cumulative principal returned",
        "unit": "fraction of as-of UPB",
        "formula": "sum over months <= t of (SP + PP + RC) / initial UPB",
    },
    "cash_wal_years": {
        "label": "Cash weighted-average life",
        "unit": "years",
        "formula": "sum(t/12 x (SP+PP+RC)) / sum(SP+PP+RC) over the full life",
    },
    "exposure_exit_wal_years": {
        "label": "Exposure-exit WAL",
        "unit": "years",
        "formula": "sum(t/12 x (SP+PP+DC)) / sum(SP+PP+DC); counts credit exits when they leave",
    },
    "out_of_support_share": {
        "label": "Out-of-support share",
        "unit": "fraction of projected balance",
        "formula": "balance-weighted share of loan-months whose incentive, market rate or 6-month "
        "rate change lies outside the 0.5-99.5% training range",
    },
}

LIMITATIONS = (
    "All portfolios are fictional and the model is trained on synthetic data; outputs say nothing "
    "about real mortgages.",
    "Real Freddie Mac data has not been evaluated (blocked pending lawful access).",
    "Rate paths are user hypotheticals, not forecasts; there is no discounting or valuation.",
    "Scheduled payments are assumed before same-month exits; actual timing differs.",
    "Curtailments, delinquency cash timing, servicing and MBS waterfalls are not modeled.",
    "Credit severity and recovery lag are illustrative inputs, not calibrated loss estimates.",
    "Tree models may respond non-monotonically to rate shocks outside their training range.",
    "Not investment, lending or trading advice.",
)


def methodology(model_name: str, run_manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "data_class": "fictional",
        "question": "How much principal could a fixed-rate pool return each month under a "
        "hypothetical mortgage-rate path, and when?",
        "outcomes": {
            "P": "full voluntary early payoff (zero-balance code 01, not within 2 months of "
            "maturity)",
            "C": "terminal credit-related disposition (codes 02, 03, 09)",
            "A": "remains active",
            "censored": "modification, whole-loan sale (15), RPL securitization (16), defect (96)",
        },
        "features": [
            {"name": f.name, "kind": f.kind, "source": f.source, "description": f.description}
            for f in FEATURES
        ],
        "feature_timing": "every feature for month t uses information available at the end of "
        "month t-1",
        "model": {
            "served": model_name,
            "run_id": run_manifest["run_id"],
            "trained_on": "synthetic data (prepay synth)",
            "selection_rule": run_manifest["selection"]["rule"],
        },
        "rates": {
            "source": "synthetic weekly series in FRED PMMS format",
            "real_source_for_research": "FRED MORTGAGE30US / MORTGAGE15US",
            "method_change": "Freddie Mac PMMS switched methodology on 2022-11-17",
        },
        "metrics": METRICS,
        "limitations": list(LIMITATIONS),
        "data_permissions": "No Freddie Mac loan-level data, derived rows or real-trained models "
        "are served. Research on real data runs only privately.",
    }
