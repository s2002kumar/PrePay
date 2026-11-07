"""Bytes per evaluation-window row held by the window phase of evaluate_development (synthetic).

Commit charge (private bytes) after each step, from the OS, so allocator overhead is included.
"""

import ctypes
import gc
import json
import sys
from ctypes import wintypes
from pathlib import Path

import duckdb

from prepay import periods
from prepay.features.derived import augment
from prepay.features.panel import rate_path_from_warehouse
from prepay.modeling import metrics
from prepay.modeling.experiment import REFERENCES, paired_development
from prepay.modeling.registry import load_run
from prepay.modeling.windows import Window, read_window
from prepay.transform import warehouse_path


class PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
        (n, ctypes.c_size_t)
        for n in (
            "PeakWorkingSetSize",
            "WorkingSetSize",
            "QuotaPeakPagedPoolUsage",
            "QuotaPagedPoolUsage",
            "QuotaPeakNonPagedPoolUsage",
            "QuotaNonPagedPoolUsage",
            "PagefileUsage",
            "PeakPagefileUsage",
        )
    ]


def commit():
    c = PMC()
    c.cb = ctypes.sizeof(PMC)
    k32 = ctypes.WinDLL("kernel32")
    psapi = ctypes.WinDLL("psapi")
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
    psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb)
    return int(c.PagefileUsage), int(c.PeakPagefileUsage)


run_dir, data_root = Path(sys.argv[1]), Path(sys.argv[2])
run = load_run(run_dir)
w = run.manifest["windows"]["evaluate"]
first, last = periods.parse_iso(w["first"]), periods.parse_iso(w["last"])
months = int(sys.argv[3]) if len(sys.argv) > 3 else last - first + 1
window = Window("evaluate", "validation", first, first + months - 1)
calibrated = {name: run.calibrated(name) for name in run.models}
with duckdb.connect(str(warehouse_path(data_root)), read_only=True) as con:
    rates = rate_path_from_warehouse(con)
    gc.collect()
    base, _ = commit()
    batch = augment(read_window(con, window), rates)
gc.collect()
after_read, _ = commit()
predictions = {name: m.predict_proba(batch) for name, m in calibrated.items()}
gc.collect()
after_predict, _ = commit()
results = {name: metrics.evaluate(batch, p) for name, p in predictions.items()}
paired = {
    n: {
        r: paired_development(batch, predictions[n], predictions[r])
        for r in REFERENCES
        if r in predictions and r != n
    }
    for n in predictions
}
_, peak = commit()
n = batch.rows
print(
    json.dumps(
        {
            "months": months,
            "base_commit_mib": round(base / 2**20),
            "held_mib": round((after_predict - base) / 2**20),
            "peak_mib": round((peak - base) / 2**20),
            "rows": n,
            "models": len(predictions),
            "window_bytes_per_row": round((after_read - base) / n),
            "predictions_bytes_per_row": round((after_predict - after_read) / n),
            "held_bytes_per_row": round((after_predict - base) / n),
            "peak_through_metrics_bytes_per_row": round((peak - base) / n),
        },
        indent=1,
    )
)
