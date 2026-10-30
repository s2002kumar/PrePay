"""Public FHFA state HPI (all-transactions) vintages from ALFRED: real-time vs latest HPA.

Research script for docs/research/HPI_EQUITY_PROXY.md (public data only, stdlib only).
Usage: python -I hpi_revisions.py <output-dir>
"""

import csv
import datetime as dt
import json
import sys
import time
import urllib.request
from pathlib import Path

OUT = Path(sys.argv[1])
STATES = ("CA", "FL", "TX", "OH")
vintages = [
    dt.date(y, m, 1)
    for y in range(2008, 2027)
    for m in (6, 12)
    if dt.date(y, m, 1) <= dt.date(2026, 6, 1)
][1:]
final = dt.date(2026, 10, 1)


def fetch(series: str, vintage: dt.date) -> dict[dt.date, float]:
    path = OUT / f"{series}_{vintage}.csv"
    if not path.exists():
        url = f"https://alfred.stlouisfed.org/graph/alfredgraph.csv?id={series}&vintage_date={vintage}"
        with urllib.request.urlopen(url, timeout=60) as r:
            path.write_bytes(r.read())
        time.sleep(0.5)
    rows = list(csv.reader(path.read_text().splitlines()))[1:]
    return {dt.date.fromisoformat(d): float(v) for d, v in rows if v not in ("", ".")}


def hpa(series: dict[dt.date, float], q: dt.date, quarters: int) -> float | None:
    back = dt.date(q.year - (quarters // 4), q.month, 1)
    return series[q] / series[back] - 1 if q in series and back in series else None


report = {}
for st in STATES:
    sid = f"{st}STHPI"
    latest = fetch(sid, final)
    rows = []
    for v in vintages:
        real = fetch(sid, v)
        q_last = max(real)
        lag_days = (
            v - (dt.date(q_last.year + (q_last.month + 2) // 12, (q_last.month + 2) % 12 + 1, 1))
        ).days
        for age, label in ((0, "latest_quarter"), (2, "two_quarters_older")):
            m = q_last.month - 3 * age
            y = q_last.year + (m - 1) // 12
            q = dt.date(y, (m - 1) % 12 + 1, 1)
            a, b = hpa(real, q, 4), hpa(latest, q, 4)
            if a is not None and b is not None:
                rows.append(
                    {
                        "vintage": str(v),
                        "quarter": str(q),
                        "kind": label,
                        "lag_days": lag_days,
                        "realtime_hpa_4q_pct": round(a * 100, 2),
                        "latest_hpa_4q_pct": round(b * 100, 2),
                        "revision_pp": round((b - a) * 100, 2),
                    }
                )
    report[st] = rows


def summary(kind: str) -> dict:
    revs = [abs(r["revision_pp"]) for st in report for r in report[st] if r["kind"] == kind]
    revs.sort()
    return {
        "n": len(revs),
        "mean_abs_pp": round(sum(revs) / len(revs), 2),
        "median_abs_pp": revs[len(revs) // 2],
        "p90_abs_pp": revs[int(0.9 * len(revs))],
        "max_abs_pp": revs[-1],
    }


lags = sorted({r["lag_days"] for st in report for r in report[st]})
out = {
    "states": STATES,
    "vintages": [str(v) for v in vintages],
    "final_vintage": str(final),
    "first_release_lag_days_range": [lags[0], lags[-1]],
    "summary": {k: summary(k) for k in ("latest_quarter", "two_quarters_older")},
    "worst": sorted(
        (r | {"state": st} for st in report for r in report[st]),
        key=lambda r: -abs(r["revision_pp"]),
    )[:6],
}
(OUT / "revisions.json").write_text(json.dumps({"summary": out, "rows": report}, indent=1))
print(json.dumps(out, indent=1))  # noqa: T201 - a research script reports to stdout
