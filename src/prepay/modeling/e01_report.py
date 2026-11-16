"""The owner's local E01 report: a deterministic reading of the summary (ADR 0014, E01-D1).

Only the owner interprets private E01 results. This module turns ``e01-summary.json`` into
Markdown with fixed wording for every predefined metric, class, flag and rule result (ADR 0014
§9.6). It uses no model or service, and the same summary always gives the same text: lists
follow the pre-registered orders of :mod:`prepay.modeling.e01` (families, folds, horizons by
length), never the order of keys in the summary. A value the summary doesn't hold reads "n/a".

It reads only the summary, so ``prepay experiment e01 summarize`` can re-render a finished E01
directory without touching a run.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from prepay.evaluation.segments import POOR_BAND
from prepay.modeling.e01 import BLOCKING_D2_FLAGS, COMPARISON_FAMILIES, FAMILIES, S1
from prepay.modeling.probes import ICE_FLAG_SHARE, LEVEL_FLAG_RELATIVE, TAIL_MIN_DECLINE

PRIVATE_BANNER = (
    "**Private.** These results are derived from Freddie Mac loan-level data. Read them locally. "
    "Don't upload them, paste them into a hosted AI service, or publish them (ADR 0013 D1, "
    "ADR 0014 E01-D1)."
)
SYNTHETIC_BANNER = (
    "**Synthetic data.** Every number here comes from a fictional dataset. It shows the "
    "report's format and the pipeline working, nothing about real mortgages."
)

R2_TEXT = {
    "consistent_advantage": "has lower loss than {ref} in {n} of the regime-shift folds, and is "
    "non-inferior (or lower) in both control folds: a consistent advantage in development data",
    "advantage_on_shift_folds_control_loss_not_ruled_out": "has lower loss than {ref} in {n} of "
    "the regime-shift folds, but a loss in a control fold is not ruled out",
    "no_consistent_advantage": "does not show a consistent advantage over {ref} ({n} "
    "regime-shift folds with lower loss)",
    "incomplete": "can't be read yet: not every fold has finished",
}
R3_TEXT = {
    "consistently_lower_loss": "the first bundle has lower loss in at least three of the four "
    "regime-shift folds",
    "consistently_higher_loss": "the first bundle has higher loss in at least three of the four "
    "regime-shift folds",
    "no_consistent_difference": "no consistent difference across the regime-shift folds",
    "incomplete": "can't be read yet: not every regime-shift fold has finished",
}
CAVEATS = (
    "Development evidence only (outcome months up to 2019-12). Nothing here shows how any model "
    "performed or would perform on 2020-2026 or on future months.",
    "The regime classes are analogues. All four regime-shift folds are low-rate shifts; no fold "
    "has rates above its training range, so lock-in (2022+) is only weakly tested.",
    "Folds overlap and are serially dependent. Fold counts describe consistency; no test is "
    "pooled across folds.",
    "Classes come from Bonferroni-simultaneous intervals within each declared family. "
    "'Inconclusive' is not evidence of equivalence or of non-inferiority.",
    "Compared pairs differ in bundles of design choices. Only X2 - X1 isolates one choice. No "
    "difference is attributed to a single cause.",
    "Stability (R6) is a robustness diagnostic, not a test or a gate.",
    "The run-off 'curtailment' line is a recast-convention residual and overstates "
    "curtailments for no-recast loans (R2 defect 1).",
    "A nomination (R7) is a recommendation only. Confirmation can come only from a separate "
    "forward registration judged on months after its own registration.",
)
READING = (
    "**How to read this report.** Everything here is exploratory development evidence (E1): "
    "rolling-origin folds of historical data whose outcome months end by 2019-12. It is not "
    "prospective confirmation, and no figure in it is a validated forecast. Prospective "
    "confirmation can come only from a separately registered forward test, judged on months "
    "after its own registration. Nothing here is admitted retroactively to the sealed forward "
    "registration."
)
#: D2 probe columns (ADR 0009 §6), in a fixed order; flags in ``BLOCKING_D2_FLAGS`` block R7.
D2_COLUMNS = (
    ("incentive_ice_violations", "Incentive ICE"),
    ("burnout_ice_violations", "Burnout ICE"),
    ("level_relative_change_plus_200bp", "Level +200 bp"),
    ("level_raises_payoffs", "Level raises payoffs"),
    ("tail_decline_per_100bp_below_support", "Tail decline"),
    ("flat_extrapolation", "Flat extrapolation"),
)
TOLERANCE_CHECKS = ("T1", "T2", "T3", "T4", "T5", "T6")
RUNOFF_MODES = (("hindsight_rates", "hindsight"), ("as_of_flat_rates", "as-of flat"))
CLASS_ORDER = ("lower_loss", "non_inferior", "inconclusive", "higher_loss")
DEFINITIONS = (
    f"**Incentive ICE**: more than {ICE_FLAG_SHARE:.0%} of the probe's reference rows have a "
    "payoff curve that falls somewhere as the refinancing incentive rises (expected: "
    "non-decreasing). Blocks a nomination (R7).",
    f"**Burnout ICE**: more than {ICE_FLAG_SHARE:.0%} of the reference rows have a payoff curve "
    "that rises somewhere as burnout grows (expected: non-increasing). Blocks a nomination.",
    "**Level +200 bp**: relative change of the mean payoff SMM when the market rate level rises "
    "200 bp with the incentive held fixed.",
    f"**Level raises payoffs**: that change is above +{LEVEL_FLAG_RELATIVE:.0%}. Blocks a "
    "nomination.",
    "**Tail decline**: relative fall of the mean payoff SMM from the lower edge of the training "
    "incentive support to 100 bp below it.",
    f"**Flat extrapolation**: that fall is under {TAIL_MIN_DECLINE:.0%}. Informational; it "
    "doesn't block a nomination.",
    "A flag is reported as computed. This report doesn't explain or waive any flag.",
    "**Fifths**: payoff A/E in the bottom and top fifth of rows by the model's predicted payoff, "
    "with unadjusted two-way intervals.",
    "**Pool-factor error**: model minus observed pool factor of the cohort active at t0, in "
    "percentage points of its t0 balance. **WAL error**: model minus observed truncated "
    "weighted-average life, in years. *Hindsight* rates are the rates later realized; *as-of "
    "flat* rates hold the t0 rates flat.",
    "**T1-T6** (ADR 0010 tolerances): T1 CPR-proxy bias; T2 12-month payoff incidence; T3 "
    "12-month pool factor; T4 24-month truncated WAL (T3 and T4 at hindsight rates, error vs "
    "tolerance); T5 share of poorly served segment cells; T6 payoff A/E, overall and by "
    "quintile. 'Undetermined' means the check can't be read (for T2: censoring bounds wider "
    "than the tolerance).",
    "**Incidence attribution**: total error (as-of minus realized) = behavioral error "
    "(hindsight minus realized) + rate-path error (as-of minus hindsight), in percentage points "
    "of cumulative payoff incidence. Realized incidence is Aalen-Johansen under censoring. "
    "*Material*: the hindsight forecast lies outside both the realized interval and the "
    "censoring bounds (read only at the censoring-bound horizon).",
)


def _num(value: Any, spec: str) -> str:
    if value is None:
        return "n/a"
    return format(float(value), spec)


def _interval(low: Any, high: Any, spec: str) -> str:
    if low is None or high is None:
        return "n/a"
    return f"[{format(float(low), spec)}, {format(float(high), spec)}]"


def _short(name: str) -> str:
    return name.split("_")[0]


def _months(horizon: str) -> int:
    """``"12m"`` -> 12, so horizons sort by length, not as text."""
    return int(horizon.rstrip("m"))


def _yes(value: Any) -> str:
    if value is None:
        return "n/a"
    return "yes" if value else "no"


def _flag(value: Any, *, blocking: bool) -> str:
    """A D2 flag; a raised blocking flag is bold so it can't be overlooked."""
    text = _yes(value)
    return f"**{text}**" if blocking and value is True else text


def _clean(dirty: Any) -> str:
    """A run's ``git_dirty``: False reads "yes" (a clean tree), True a bold "no"."""
    if dirty is None:
        return "n/a"
    return "yes" if dirty is False else "**no**"


def _verdict(value: Any) -> str:
    if value is None:
        return "undetermined"
    return "pass" if value else "**fail**"


def _ratio_cell(ratio: Mapping[str, Any] | None) -> str:
    if not ratio:
        return "n/a"
    interval = _interval(ratio.get("low"), ratio.get("high"), ".3f")
    return f"{_num(ratio.get('estimate'), '.3f')} {interval}"


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def render_report(summary: Mapping[str, Any]) -> str:
    """Markdown for the owner; deterministic in ``summary``."""
    out: list[str] = ["# E01 local report", ""]
    out += [SYNTHETIC_BANNER if summary.get("synthetic") else PRIVATE_BANNER, ""]
    out += [f"> {summary['label']}", ""]
    out += [READING, ""]
    out += _status(summary)
    rules = summary["rules"]
    out += _findings(rules)
    out += _comparisons(summary)
    out += _folds(summary)
    out += _provenance(summary)
    out += ["## Definitions", ""] + [f"- {d}" for d in DEFINITIONS] + [""]
    out += ["## Caveats", ""] + [f"- {c}" for c in CAVEATS] + [""]
    return "\n".join(out)


def _status(summary: Mapping[str, Any]) -> list[str]:
    done, expected = summary["folds_completed"], summary["folds_expected"]
    lines = ["## Status", ""]
    lines.append(f"- Evidence class: {summary.get('evidence_class') or 'n/a'}.")
    lines.append(f"- Folds finished: {len(done)} of {len(expected)} ({', '.join(done) or 'none'}).")
    lines.append(
        "- Stability S1 finished: " + (", ".join(summary["stability_completed"]) or "none") + "."
    )
    lines.append(
        "- Complete: " + ("yes." if summary["complete"] else "no; rule results may be incomplete.")
    )
    ledger = summary.get("ledger") or {}
    reproduction = ledger.get("reproduction")
    if reproduction:
        verdict = "identical" if reproduction.get("identical") else "**not identical**"
        lines.append(f"- Pilot byte identity against the V1 run: {verdict}.")
    if ledger.get("waiver"):
        lines.append(f"- Recorded waiver: {ledger['waiver']}")
    lines.append("")
    return lines


def _findings(rules: Mapping[str, Any]) -> list[str]:
    lines = ["## What the reading rules found", ""]
    nominated = rules["R7_nomination"]["nominated"]
    if nominated:
        names = ", ".join(_short(n) for n in nominated)
        lines.append(
            f"**R7.** Nominated for a separate forward registration (a recommendation, not "
            f"validation): {names}."
        )
    else:
        lines.append("**R7.** No family is nominated: no development evidence for a change.")
    lines.append("")
    lines.append("R7 reasons, as computed (this report doesn't explain or waive any flag):")
    lines.append("")
    candidates = rules["R7_nomination"].get("candidates") or {}
    for candidate, _ in COMPARISON_FAMILIES["F-M1"]:
        entry = candidates.get(candidate)
        if entry is None:
            continue
        if entry.get("nominated"):
            lines.append(f"- {_short(candidate)}: nominated.")
        else:
            reasons = "; ".join(entry.get("reasons") or ()) or "no reason recorded"
            lines.append(f"- {_short(candidate)}: not nominated. {reasons}.")
    lines.append("")
    lines += _r1(rules.get("R1_description") or {})
    for family, ref in (("F-M1", "M1"), ("F-B2", "B2")):
        lines.append(f"**R2 vs {ref}** (consistency, not proof):")
        lines.append("")
        for candidate, _ in COMPARISON_FAMILIES[family]:
            result = rules["R2_consistency"][family][candidate]
            text = R2_TEXT[result["result"]].format(
                ref=ref,
                n=f"{result['lower_loss_shift_folds']} of {len(result['shift_folds'])}",
            )
            lines.append(f"- {_short(candidate)} {text}.")
        lines.append("")
    lines.append("**R3** (bundled design choices; no single cause attributed):")
    lines.append("")
    for a, b in COMPARISON_FAMILIES["F-DESIGN"]:
        result = rules["R3_design_bundles"][f"{a} - {b}"]
        names = f"{_short(a)} - {_short(b)}"
        single = " This pair is the closest to a single change." if result["single_choice"] else ""
        lines.append(
            f"- {names}: {R3_TEXT[result['result']]}. Differs in: {result['differs_in']}.{single}"
        )
    lines.append("")
    transfer = rules["R4_calibration_transfer"]["models"]
    if transfer:
        ok = sorted(_short(m) for m, v in transfer.items() if v["transfers"])
        not_ok = sorted(
            f"{_short(m)} ({len(v['outside_band'])} cells)"
            for m, v in transfer.items()
            if not v["transfers"]
        )
        lines.append(
            "**R4** (calibration transfer, a diagnostic): transfers for "
            f"{', '.join(ok) or 'no family'}; doesn't for {', '.join(not_ok) or 'no family'}."
        )
        lines.append("")
        outside = [
            f"- {_short(m)}, cells outside {list(POOR_BAND)}: "
            + ", ".join(transfer[m]["outside_band"])
            for m in FAMILIES
            if m in transfer and transfer[m]["outside_band"]
        ]
        if outside:
            lines += [*outside, ""]
    breaches = sorted(
        f"{origin} {_short(model)} {key}"
        for origin, models in rules["R5_financial_materiality"]["folds"].items()
        for model, checks in models.items()
        for key, check in checks.items()
        if check.get("within_tolerance") is False
    )
    lines.append(
        "**R5** (run-off errors beyond the T3/T4 tolerances, hindsight rates): "
        + (", ".join(breaches) if breaches else "none")
        + "."
    )
    lines.append("")
    sds = rules["R6_stability"]["tune_log_loss_sd"]
    measured = {
        kind: ", ".join(
            f"{_short(f)} {sds[kind][f]:.2e}" for f in FAMILIES if sds[kind].get(f) is not None
        )
        for kind in S1
        if kind in sds
    }
    lines.append(
        "**R6** (robustness diagnostic): SD of tune-window log loss across loan samples: "
        f"{measured.get('samples') or 'not measured'}; across seeds: "
        f"{measured.get('seeds') or 'not measured'}."
    )
    lines.append("")
    unstable = rules["R6_stability"].get("unstable_flags") or {}
    flagged = {
        kind: (
            ", ".join(_short(f) for f in FAMILIES if unstable[kind].get(f)) or "none"
            if kind in unstable
            else "not measured"
        )
        for kind in S1
    }
    lines.append(
        "Flagged unstable in S1 (SD above a quarter of the smallest between-family gap, or an "
        "incentive response whose relative SD exceeds 10% at a grid point): across loan samples: "
        f"{flagged.get('samples')}; across seeds: {flagged.get('seeds')}."
    )
    lines.append("")
    return lines


def _class_counts(counts: Mapping[str, int] | None) -> str:
    if counts is None:
        return "n/a"
    text = ", ".join(f"{c.replace('_', ' ')} {counts[c]}" for c in CLASS_ORDER if counts.get(c))
    return text or "none"


def _r1(r1: Mapping[str, Any]) -> list[str]:
    """R1: ranks by fold log loss and class counts. Point estimates, not tests."""
    mean_rank = r1.get("mean_rank") or {}
    if not mean_rank:
        return ["**R1** (description): no fold has finished.", ""]
    gaps = r1.get("worst_relative_gap_to_fold_best") or {}
    counts = r1.get("class_counts") or {}
    lines = ["**R1** (description; ranks are point estimates, not tests):", ""]
    rows = [
        [
            _short(m),
            _num(mean_rank.get(m), ".2f"),
            _num(gaps.get(m), ".2%"),
            _class_counts((counts.get("F-M1") or {}).get(m)),
            _class_counts((counts.get("F-B2") or {}).get(m)),
        ]
        for m in FAMILIES
        if m in mean_rank
    ]
    lines += _table(
        ("Model", "Mean rank", "Worst gap to fold best", "F-M1 classes", "F-B2 classes"), rows
    )
    lines.append("")
    order = r1.get("order_by_fold") or {}
    for origin in sorted(order):
        ranked = " < ".join(_short(m) for m in order[origin])
        lines.append(f"- {origin}, by log loss (lowest first): {ranked}.")
    lines.append("")
    return lines


def _comparisons(summary: Mapping[str, Any]) -> list[str]:
    lines = ["## Comparisons", ""]
    lines.append(
        "Difference = candidate minus reference mean log loss (nats per loan-month); negative "
        "means lower loss. Relative = difference / reference. Intervals: simultaneous within "
        "each family (Bonferroni)."
    )
    lines.append("")
    for family in ("F-M1", "F-B2", "F-DESIGN"):
        ordered = sorted(
            (c for c in summary["comparisons"] if c["family"] == family),
            key=lambda c: (
                c["origin"],
                COMPARISON_FAMILIES[family].index((c["candidate"], c["reference"])),
            ),
        )
        rows = [
            [
                c["origin"],
                c["regime_class"].replace("_", " "),
                f"{_short(c['candidate'])} - {_short(c['reference'])}",
                _num(c["estimate"], "+.2e"),
                _num(c["relative_to_reference"], "+.2%"),
                _interval(c.get("simultaneous_low"), c.get("simultaneous_high"), "+.2e"),
                c["class"].replace("_", " "),
                c["sampling_fragility"].replace("_", " "),
            ]
            for c in ordered
        ]
        if not rows:
            continue
        lines += [f"### {family}", ""]
        lines += _table(
            (
                "Fold",
                "Class of fold",
                "Pair",
                "Difference",
                "Relative",
                "Simultaneous 95%",
                "Class",
                "Sampling",
            ),
            rows,
        )
        lines.append("")
    return lines


def _folds(summary: Mapping[str, Any]) -> list[str]:
    lines = ["## Folds", ""]
    for origin in sorted(summary["folds"]):
        fold = summary["folds"][origin]
        lines += [f"### {origin} ({fold['regime_class'].replace('_', ' ')}, {fold['window']})", ""]
        support = fold["support"].get("balance", {})
        lines.append(
            f"Support of the evaluation window (by balance): {support.get('verdict') or 'n/a'}; "
            f"outside {_num(support.get('outside_share'), '.1%')}, "
            f"thin {_num(support.get('sparse_share'), '.1%')}."
        )
        lines.append("")
        rows = []
        for model in (m for m in FAMILIES if m in fold["log_loss"]):
            loss = fold["log_loss"][model]
            ae = fold["payoff_ae"][model]
            cpr = fold["cpr_bias_pp"][model]
            rows.append(
                [
                    _short(model),
                    _num(loss, ".5f"),
                    _num(fold["brier"][model], ".5f"),
                    f"{_num(ae['estimate'], '.3f')} {_interval(ae['low'], ae['high'], '.3f')}",
                    f"{_num(cpr['estimate'], '+.2f')} {_interval(cpr['low'], cpr['high'], '+.2f')}",
                    _num(fold["cpr_mae_pp"][model], ".2f"),
                ]
            )
        lines += _table(
            ("Model", "Log loss", "Brier", "Payoff A/E", "CPR bias, pp", "CPR MAE, pp"),
            rows,
        )
        lines.append("")
        r5 = (summary["rules"]["R5_financial_materiality"].get("folds") or {}).get(origin) or {}
        lines += _fifths(fold)
        lines += _d2(fold)
        lines += _runoff(fold)
        lines += _tolerances(fold, r5)
        lines += _attribution(fold)
    return lines


def _fifths(fold: Mapping[str, Any]) -> list[str]:
    fifths = fold.get("fifth_ae") or {}
    rows = [
        [_short(m), _ratio_cell(fifths[m].get("bottom")), _ratio_cell(fifths[m].get("top"))]
        for m in FAMILIES
        if m in fifths
    ]
    if not rows:
        return ["#### Calibration by predicted payoff", "", "n/a.", ""]
    lines = ["#### Calibration by predicted payoff", ""]
    lines += _table(("Model", "Bottom-fifth A/E", "Top-fifth A/E"), rows)
    return [*lines, ""]


def _d2(fold: Mapping[str, Any]) -> list[str]:
    flags = fold.get("d2_flags") or {}
    lines = ["#### Economic diagnostics (D2 probes)", ""]
    rows = []
    for m in (m for m in FAMILIES if m in flags):
        row = [_short(m)]
        for key, _ in D2_COLUMNS:
            value = flags[m].get(key)
            if key == "level_relative_change_plus_200bp":
                row.append(_num(value, "+.1%"))
            elif key == "tail_decline_per_100bp_below_support":
                row.append(_num(value, ".1%"))
            else:
                row.append(_flag(value, blocking=key in BLOCKING_D2_FLAGS))
        rows.append(row)
    if not rows:
        return [*lines, "n/a.", ""]
    lines += _table(("Model", *(label for _, label in D2_COLUMNS)), rows)
    return [*lines, ""]


def _runoff(fold: Mapping[str, Any]) -> list[str]:
    runoff = fold.get("runoff") or {}
    lines = ["#### Run-off (cohort active at t0)", ""]
    horizons = sorted(
        {
            h
            for modes in runoff.values()
            for mode, _ in RUNOFF_MODES
            for h in ((modes or {}).get(mode) or {}).get("pool_factor_error_pp", {})
        },
        key=_months,
    )
    rows = []
    for m in FAMILIES:
        for mode, label in RUNOFF_MODES:
            entry = (runoff.get(m) or {}).get(mode)
            if not entry:
                continue
            errors = entry.get("pool_factor_error_pp") or {}
            rows.append(
                [
                    _short(m),
                    label,
                    *(_num(errors.get(h), "+.2f") for h in horizons),
                    _num(entry.get("wal_error_years"), "+.3f"),
                ]
            )
    if not rows:
        return [*lines, "n/a: the fold has no run-off backtest.", ""]
    header = ("Model", "Rates", *(f"Pool-factor error {h}, pp" for h in horizons))
    lines += _table((*header, "Truncated WAL error, years"), rows)
    return [*lines, ""]


def _check(checks: Mapping[str, Any], key: str) -> str:
    return _verdict(checks[key]) if key in checks else "n/a"


def _measured(detail: Mapping[str, Any] | None, fallback: str, spec: str, unit: str) -> str:
    """T3/T4 as ``error vs +/-tolerance unit: verdict`` (R5); else the bare verdict."""
    if not detail:
        return fallback
    error = _num(detail.get("error"), spec)
    tolerance = _num(detail.get("tolerance"), spec.lstrip("+"))
    return f"{error} vs +/-{tolerance} {unit}: {_verdict(detail.get('within_tolerance'))}"


def _tolerances(fold: Mapping[str, Any], r5: Mapping[str, Any]) -> list[str]:
    tolerances = fold.get("tolerances") or {}
    lines = ["#### Tolerances", ""]
    rows = []
    for m in (m for m in FAMILIES if m in tolerances):
        checks, detail = tolerances[m], r5.get(m) or {}
        rows.append(
            [
                _short(m),
                _check(checks, "T1"),
                _check(checks, "T2"),
                _measured(detail.get("T3"), _check(checks, "T3"), "+.2f", "pp"),
                _measured(detail.get("T4"), _check(checks, "T4"), "+.3f", "years"),
                _check(checks, "T5"),
                _check(checks, "T6"),
            ]
        )
    if not rows:
        return [*lines, "n/a.", ""]
    lines += _table(("Model", *TOLERANCE_CHECKS), rows)
    return [*lines, ""]


def _attribution(fold: Mapping[str, Any]) -> list[str]:
    attribution = fold.get("cohort_attribution") or {}
    lines = ["#### Payoff incidence attribution", ""]
    horizons = attribution.get("horizons") or {}
    if not horizons:
        return [*lines, f"n/a: {attribution.get('note') or 'no mature horizon'}.", ""]
    ordered = sorted(horizons, key=_months)
    realized = ", ".join(f"{h} {_num(horizons[h].get('realized_prepay'), '.2%')}" for h in ordered)
    lines += [f"Realized payoff incidence (Aalen-Johansen): {realized}.", ""]
    rows = []
    for h in ordered:
        models = horizons[h].get("models") or {}
        for m in (m for m in FAMILIES if m in models):
            row = models[m]
            rows.append(
                [
                    h,
                    _short(m),
                    _num(row.get("behavioral_error_pp"), "+.2f"),
                    _num(row.get("rate_path_error_pp"), "+.2f"),
                    _num(row.get("total_error_pp"), "+.2f"),
                    _yes(row.get("behavioral_outside_realized_interval")),
                    _yes(row.get("behavioral_error_material")),
                ]
            )
    lines += _table(
        (
            "Horizon",
            "Model",
            "Behavioral, pp",
            "Rate path, pp",
            "Total, pp",
            "Outside realized interval",
            "Material",
        ),
        rows,
    )
    return [*lines, ""]


def _provenance(summary: Mapping[str, Any]) -> list[str]:
    ledger = summary.get("ledger") or {}
    lines = ["## Provenance", ""]
    lines += [f"- Execution identity digest: `{ledger.get('identity_digest') or 'n/a'}`.", ""]
    provenance = summary.get("provenance") or {}
    rows = [
        [
            origin,
            f"`{provenance[origin].get('run_id') or 'n/a'}`",
            f"`{str(provenance[origin].get('git_sha') or 'n/a')[:12]}`",
            _clean(provenance[origin].get("git_dirty")),
        ]
        for origin in sorted(provenance)
    ]
    if rows:
        lines += _table(("Fold", "Run", "Commit", "Clean tree"), rows)
        lines.append("")
    return lines
