"""Process and host resource measurement (memory, commit, stage timing), stdlib only."""

from __future__ import annotations

import os
import platform
import sys
import time


def peak_rss_bytes() -> int:
    """Peak resident set size of the current process, in bytes.

    Windows: ``PeakWorkingSetSize`` from ``GetProcessMemoryInfo``. Linux: ``VmHWM`` from
    ``/proc/self/status``, which belongs to this process's address space. ``ru_maxrss`` is inherited
    across fork/exec, so a child of a large parent would report the parent's peak. Other POSIX:
    ``ru_maxrss`` (bytes on macOS).
    """
    if sys.platform == "win32":
        return _windows_peak_working_set()
    else:  # noqa: RET505 - a platform branch mypy can type-check per OS
        hwm = _proc_vm_hwm()
        if hwm is not None:
            return hwm
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(peak if sys.platform == "darwin" else peak * 1024)


def peak_commit_bytes() -> int | None:
    """Peak private committed memory of the current process, in bytes; ``None`` off Windows.

    Windows refuses an allocation (``MemoryError``) when the system **commit** limit is reached,
    not when physical memory runs out. On a host under memory pressure the working set is
    trimmed, so peak RSS can understate what a job needed. ``PeakPagefileUsage`` is the peak of
    the process's private commit charge, the quantity that hits that limit. Linux overcommits and
    has no per-process equivalent, so peak RSS (``VmHWM``) is the measure there.
    """
    if sys.platform == "win32":
        return _windows_peak_commit()
    else:  # noqa: RET505 - a platform branch mypy can type-check per OS
        return None


def commit_now_bytes() -> int | None:
    """Current private commit charge of this process (Windows ``PagefileUsage``); else ``None``.

    A current value, not a peak: stage records use it next to the process high-water marks.
    """
    if sys.platform == "win32":
        return int(_windows_counters().PagefileUsage)
    else:  # noqa: RET505 - a platform branch mypy can type-check per OS
        return None


_baseline_commit: int | None = None


def mark_baseline() -> None:
    """Record the commit charge now, once the job's libraries are imported and before any data
    is read: the fixed process cost that E01's resource projection doesn't scale."""
    global _baseline_commit
    _baseline_commit = commit_now_bytes()


def baseline_commit_bytes() -> int | None:
    return _baseline_commit


def free_commit_bytes() -> int | None:
    """Memory the host can still commit, in bytes, for a preflight before a heavy job.

    Windows: ``ullAvailPageFile`` of ``GlobalMemoryStatusEx``, the commit limit minus the commit
    charge. Linux: ``MemAvailable + SwapFree`` from ``/proc/meminfo``, the closest equivalent
    under overcommit. ``None`` where neither is available.
    """
    if sys.platform == "win32":
        return _windows_available_commit()
    else:  # noqa: RET505 - a platform branch mypy can type-check per OS
        return _proc_meminfo_available()


class StageRecorder:
    """Elapsed time and memory after each named stage of a job (ADR 0014 §9.2).

    ``process_peak_*`` are the process's **high-water marks** since it started, read after the
    stage: they never decrease, and a value says only that the peak so far was reached at or
    before that stage. They are not per-stage peaks and must not be added or projected as if
    independent. ``commit_now_bytes`` is the current commit charge, not a peak.
    """

    def __init__(self) -> None:
        self.stages: list[dict[str, str | float | int | None]] = []
        self._clock = time.perf_counter()

    def __call__(self, name: str) -> None:
        now = time.perf_counter()
        self.stages.append(
            {
                "stage": name,
                "seconds": round(now - self._clock, 1),
                "process_peak_rss_bytes": peak_rss_bytes(),
                "process_peak_commit_bytes": peak_commit_bytes(),
                "commit_now_bytes": commit_now_bytes(),
            }
        )
        self._clock = now


def job_peak_bytes(report: dict[str, object]) -> int | None:
    """The memory figure a job is judged by: peak commit where measured, else peak RSS.

    ``None`` when the report has neither: a budget can't be confirmed from it, so it must not pass.
    """
    for key in ("peak_commit_bytes", "peak_rss_bytes"):
        value = report.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return None


def _proc_meminfo_available() -> int | None:
    try:
        with open("/proc/meminfo", encoding="ascii") as meminfo:
            fields = {line.split(":")[0]: line.split()[1] for line in meminfo if ":" in line}
    except OSError:
        return None
    if "MemAvailable" not in fields:
        return None
    return (int(fields["MemAvailable"]) + int(fields.get("SwapFree", "0"))) * 1024


def _proc_vm_hwm() -> int | None:
    try:
        with open("/proc/self/status", encoding="ascii") as status:
            for line in status:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        return None
    return None


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _ProcessMemoryCounters(ctypes.Structure):
        _fields_ = (
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
        )

    def _windows_peak_working_set() -> int:
        return int(_windows_counters().PeakWorkingSetSize)

    def _windows_peak_commit() -> int:
        return int(_windows_counters().PeakPagefileUsage)

    def _windows_counters() -> _ProcessMemoryCounters:
        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(_ProcessMemoryCounters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        if not psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        ):
            raise OSError(ctypes.get_last_error(), "GetProcessMemoryInfo failed")
        return counters

    class _MemoryStatusEx(ctypes.Structure):
        _fields_ = (
            ("dwLength", wintypes.DWORD),
            ("dwMemoryLoad", wintypes.DWORD),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        )

    def _windows_available_commit() -> int:
        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(_MemoryStatusEx)]
        if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise OSError(ctypes.get_last_error(), "GlobalMemoryStatusEx failed")
        return int(status.ullAvailPageFile)


def host_description() -> dict[str, object]:
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "logical_cpus": os.cpu_count(),
        "python": platform.python_version(),
    }
