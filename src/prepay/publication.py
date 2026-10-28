"""Publication gate: refuse to publish restricted data, real-data artifacts or secrets.

Scans exactly what would be published, not what ``.gitignore`` intends: the tracked file set
(``git ls-files``), optional build outputs (web bundle, demo bundle, an exported image tree) and
optionally the full Git history for credential patterns. A ``.gitignore`` alone is not a gate.
"""

from __future__ import annotations

import fnmatch
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

MAX_BYTES = 5 * 2**20
TEXT_LIMIT = 2 * 2**20

FORBIDDEN_PATHS = (
    "data/*",
    "artifacts/*",
    "reports/*",
    "notes/*",
    "scratch/*",
    "build/*",
    ".env",
    ".env.*",
    "*.duckdb",
    "*.duckdb.wal",
    "*.parquet",
    "*.zip",
    "*.pkl",
    "*.joblib",
    "*.pem",
    "*.p12",
    "*.pfx",
    "sample_orig_*",
    "sample_perf_*",
    "orig_*.txt",
    "perf_*.txt",
    "historical_data_*",
    ".claude/settings.local.json",
    "*.ipynb",
)
ALLOWED_OVERRIDES = (".env.example",)

#: Files that legitimately contain example loan identifiers (contract and format tests).
LOAN_ID_ALLOWLIST = (
    "src/prepay/contracts/sflld.py",
    "tests/unit/test_contracts.py",
    "tests/unit/test_pmms_and_validation.py",
    "tests/unit/test_models.py",
    "src/prepay/publication.py",
    "tests/unit/test_publication.py",
)

LOAN_ID = re.compile(r"\b[FA]\d{2}Q[1-4]\d{7}\b")
PERFORMANCE_ROW = re.compile(r"\b[FA]\d{2}Q[1-4]\d{7}\|(19|20)\d{4}\|")
WIDE_PIPE_ROW = re.compile(r"^(?:[^|\n]*\|){25,}[^|\n]*$", re.MULTILINE)
SECRETS = {
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "slack_token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    "generic_secret_assignment": re.compile(
        r"(?i)\b(api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*['\"][A-Za-z0-9/+_\-]{20,}['\"]"
    ),
}


@dataclass(frozen=True, slots=True)
class Finding:
    location: str
    rule: str
    detail: str


def _forbidden(relative: str) -> str | None:
    name = relative.split("/")[-1]
    if name in ALLOWED_OVERRIDES:
        return None
    for pattern in FORBIDDEN_PATHS:
        if fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(name, pattern):
            return pattern
    return None


#: Source code (especially minified JS) legitimately has long ``||`` chains; the wide-row rule
#: targets data files only. Loan-ID, row and credential rules still apply to code.
CODE_SUFFIXES = (".js", ".mjs", ".cjs", ".css", ".py", ".ts", ".tsx", ".sql")


def scan_text(location: str, text: str, *, allow_loan_ids: bool = False) -> list[Finding]:
    findings = []
    if PERFORMANCE_ROW.search(text):
        findings.append(Finding(location, "sflld_performance_row", "pipe-delimited loan-month row"))
    if not location.endswith(CODE_SUFFIXES) and WIDE_PIPE_ROW.search(text):
        findings.append(Finding(location, "wide_pipe_row", "line with 25+ pipe-delimited fields"))
    if not allow_loan_ids and LOAN_ID.search(text):
        findings.append(Finding(location, "loan_identifier", "SFLLD-style loan identifier"))
    for rule, pattern in SECRETS.items():
        if pattern.search(text):
            findings.append(Finding(location, rule, "credential-like pattern"))
    return findings


def scan_file(path: Path, relative: str) -> list[Finding]:
    findings = []
    if (pattern := _forbidden(relative)) is not None:
        findings.append(Finding(relative, "forbidden_path", f"matches {pattern}"))
    size = path.stat().st_size
    if size > MAX_BYTES:
        findings.append(Finding(relative, "oversized", f"{size} bytes > {MAX_BYTES}"))
    if size <= TEXT_LIMIT:
        raw = path.read_bytes()
        if b"\x00" not in raw[:4096]:
            text = raw.decode("utf-8", errors="replace")
            findings += scan_text(relative, text, allow_loan_ids=relative in LOAN_ID_ALLOWLIST)
    return findings


def tracked_files(root: Path) -> list[str]:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required to list the tracked file set")
    out = subprocess.run(  # noqa: S603 - resolved git binary, fixed arguments
        [git, "-C", str(root), "ls-files", "-z"], capture_output=True, check=True
    ).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def scan_repository(root: Path) -> list[Finding]:
    findings = []
    for relative in tracked_files(root):
        path = root / relative
        if path.is_file():
            findings += scan_file(path, relative)
    return findings


def scan_tree(tree: Path, label: str) -> list[Finding]:
    """Scan a build output or exported image directory (every file, no allowlist)."""
    findings = []
    for path in sorted(p for p in tree.rglob("*") if p.is_file()):
        relative = path.relative_to(tree).as_posix()
        for finding in scan_file(path, relative):
            if finding.rule == "forbidden_path" and relative.startswith("build/"):
                continue  # the demo bundle lives under build/ inside images by design
            findings.append(Finding(f"{label}:{finding.location}", finding.rule, finding.detail))
    return findings


def scan_history(root: Path) -> list[Finding]:
    """Credential patterns anywhere in Git history (defense in depth, not the primary gate)."""
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required to scan history")
    log = subprocess.run(  # noqa: S603
        [git, "-C", str(root), "log", "--all", "-p", "--no-color", "--format=commit %H"],
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8", errors="replace")
    findings = []
    for rule, pattern in SECRETS.items():
        for match in pattern.finditer(log):
            commit = log.rfind("commit ", 0, match.start())
            sha = log[commit + 7 : commit + 19] if commit >= 0 else "unknown"
            findings.append(Finding(f"history:{sha}", rule, "credential-like pattern"))
    return findings
