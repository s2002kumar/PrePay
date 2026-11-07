"""B2 and H1 scoring of one cohort-backtest chunk (20,000 loans x 24 months), synthetic fold.

Old path = ``_predict_block`` on the whole chunk (what predict_proba did for <= 2^19 rows).
New path = ``predict_proba`` (design blocks). Allocation peaks from tracemalloc; time without it.
"""

import json
import sys
import time
import tracemalloc
from pathlib import Path

import duckdb
import numpy as np

from prepay import periods
from prepay.evaluation.cohort import CHUNK_LOANS
from prepay.features.batch import PanelBatch
from prepay.features.derived import augment
from prepay.features.machine import compute_features
from prepay.features.panel import load_statics, rate_path_from_bronze
from prepay.modeling.registry import load_run
from prepay.transform import warehouse_path

run_dir, data_root = Path(sys.argv[1]), Path(sys.argv[2])
run = load_run(run_dir)
with duckdb.connect(str(warehouse_path(data_root)), read_only=True) as con:
    _, statics = load_statics(con)
history = rate_path_from_bronze(data_root / "bronze")
t0, horizon = periods.month(2009, 12), 24
active = np.nonzero((statics.first_payment_month <= t0) & (statics.maturity_month > t0 + horizon))[
    0
]
loans = np.resize(active, CHUNK_LOANS)  # repeat loans to the real chunk size
rows = np.repeat(loans, horizon)
target = np.tile(np.arange(t0 + 1, t0 + horizon + 1), loans.shape[0])
path = history.truncated(t0 + horizon - 1)
batch = augment(
    PanelBatch(
        rows.astype(object),
        target,
        np.zeros(target.size, np.int64),
        np.zeros(target.size),
        compute_features(statics, path, rows, target),
        loan_code=rows,
    ),
    path,
)


def peak(fn):
    tracemalloc.start()
    tracemalloc.reset_peak()
    base = tracemalloc.get_traced_memory()[0]
    out = fn()
    p = tracemalloc.get_traced_memory()[1] - base
    tracemalloc.stop()
    return out, p


def best_time(fn, n=3):
    times = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t)
    return min(times)


result = {"chunk_rows": batch.rows}
for name in ("B2_logistic", "H1_constrained_hazard"):
    model = run.models[name]
    old, old_peak = peak(lambda: model._predict_block(batch))
    new, new_peak = peak(lambda: model.predict_proba(batch))
    result[name] = {
        "old_peak_mib": round(old_peak / 2**20, 1),
        "new_peak_mib": round(new_peak / 2**20, 1),
        "old_seconds": round(best_time(lambda: model._predict_block(batch)), 2),
        "new_seconds": round(best_time(lambda: model.predict_proba(batch)), 2),
        "max_abs_difference": float(np.max(np.abs(old - new))),
        "bit_identical": bool(np.array_equal(old, new)),
    }
print(json.dumps(result, indent=1))
