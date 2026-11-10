"""Process resource measurement (peak resident memory) without third-party dependencies."""

from __future__ import annotations

import os
import platform
import sys


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


def host_description() -> dict[str, object]:
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "logical_cpus": os.cpu_count(),
        "python": platform.python_version(),
    }
