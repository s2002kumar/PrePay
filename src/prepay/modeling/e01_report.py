"""The owner's local E01 report: a deterministic reading of the summary (ADR 0014, E01-D1).

Only the owner interprets private E01 results. This module turns ``e01-summary.json`` into
Markdown with fixed wording for every predefined metric, class and rule result. It uses no
model or service, and the same summary always gives the same text: lists follow the
pre-registered orders of :mod:`prepay.modeling.e01`, never the order of keys in the summary.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from prepay.modeling.e01 import COMPARISON_FAMILIES, FAMILIES, S1

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


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def render_report(summary: Mapping[str, Any]) -> str:
    """Markdown for the owner; deterministic in ``summary``."""
    out: list[str] = ["# E01 local report", ""]
    out += [SYNTHETIC_BANNER if summary.get("synthetic") else PRIVATE_BANNER, ""]
    out += [f"> {summary['label']}", ""]
    out += _status(summary)
    rules = summary["rules"]
    out += _findings(rules)
    out += _comparisons(summary)
    out += _folds(summary)
    out += ["## Caveats", ""] + [f"- {c}" for c in CAVEATS] + [""]
    return "\n".join(out)


def _status(summary: Mapping[str, Any]) -> list[str]:
    done, expected = summary["folds_completed"], summary["folds_expected"]
    lines = ["## Status", ""]
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
    return lines
