"""Evaluate one fixed synthetic fold with whichever prepay is first on sys.path.

Records the process's peak working set and peak private commit with its own ctypes calls, so
the old code (which has no commit measure) is measured the same way as the new code.
"""

import ctypes
import json
import sys
import time
from ctypes import wintypes
from pathlib import Path


class PMC(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def peaks():
    c = PMC()
    c.cb = ctypes.sizeof(PMC)
    k32 = ctypes.WinDLL("kernel32")
    psapi = ctypes.WinDLL("psapi")
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
    psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb)
    return {
        "peak_ws_bytes": int(c.PeakWorkingSetSize),
        "peak_commit_bytes": int(c.PeakPagefileUsage),
        "commit_now_bytes": int(c.PagefileUsage),
    }


run_dir, data_root, lock_path, out = map(Path, sys.argv[1:5])
import prepay  # noqa: E402
from prepay.ingest.lock import read_lock  # noqa: E402
from prepay.modeling.experiment import evaluate_development  # noqa: E402

before = peaks()
t = time.perf_counter()
report = evaluate_development(run_dir, data_root, read_lock(lock_path))
seconds = time.perf_counter() - t
after = peaks()
out.write_text(json.dumps(report, sort_keys=True, default=float), encoding="utf-8")
print(
    json.dumps(
        {
            "prepay_file": prepay.__file__,
            "seconds": round(seconds, 1),
            "before": before,
            "after": after,
        },
        indent=1,
    )
)
