"""Run a command while asking Windows not to idle into standby (released on exit)."""
import ctypes
import subprocess
import sys

ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
kernel32 = ctypes.windll.kernel32
kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
try:
    code = subprocess.call(sys.argv[1:])
finally:
    kernel32.SetThreadExecutionState(ES_CONTINUOUS)
sys.exit(code)
