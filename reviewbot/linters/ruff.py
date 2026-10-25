"""Ruff linter integration for Python files."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from reviewbot.config import ReviewBotConfig
from reviewbot.linters.base import BaseLinter
from reviewbot.models import Finding, Severity

logger = logging.getLogger(__name__)


def resolve_ruff_executable(custom_binary: Optional[str] = None) -> str:
    """Find the ruff binary in PATH or active Python environment."""
    if custom_binary:
        return custom_binary

    which_ruff = shutil.which("ruff")
    if which_ruff:
        return which_ruff

    # Check next to current python interpreter (e.g. in venv or container)
    py_dir = Path(sys.executable).parent
    candidate = py_dir / ("ruff.exe" if sys.platform == "win32" else "ruff")
    if candidate.exists():
        return str(candidate)

    return "ruff"


def default_ruff_severity(code: str) -> Severity:
    """Infer finding severity from standard Ruff / Flake8 rule code prefixes."""
    upper = code.upper()
    if upper.startswith(("F", "E9", "B")):
        # Pyflakes runtime errors, syntax errors, bugbear logic bugs
        return Severity.ERROR
    if upper.startswith(("E", "W")):
        # pycodestyle errors and warnings
        return Severity.WARNING
    if upper.startswith(("I", "D", "N", "C", "Q", "UP")):
        # isort, docstrings, naming, pyupgrade
        return Severity.INFO
    return Severity.WARNING


class RuffLinter(BaseLinter):
    """Executes Ruff as a subprocess to lint Python files."""

    def __init__(self, binary_path: Optional[str] = None):
        self.binary_path = resolve_ruff_executable(binary_path)

    @property
    def name(self) -> str:
        return "ruff"

    def can_handle(self, file_path: str) -> bool:
        norm = file_path.lower()
        return norm.endswith(".py") or norm.endswith(".pyi")

    def lint(
        self,
        file_path: str,
        added_lines: set[int],
        content: Optional[str] = None,
        config: Optional[ReviewBotConfig] = None,
    ) -> list[Finding]:
        if not added_lines:
            return []

        active_config = config or ReviewBotConfig()

        # Build command line
        cmd = [self.binary_path, "check", "--output-format", "json"]

        stdin_data: Optional[bytes] = None
        if content is not None:
            cmd.extend(["--stdin-filename", file_path, "-"])
            stdin_data = content.encode("utf-8")
        elif Path(file_path).exists():
            cmd.append(file_path)
        else:
            logger.debug(
                "File '%s' does not exist on disk and no content provided. Skipping ruff.",
                file_path,
            )
            return []

        try:
            res = subprocess.run(
                cmd,
                input=stdin_data,
                capture_output=True,
                check=False,
            )
        except FileNotFoundError:
            logger.warning(
                "Ruff executable not found at '%s'. Style checks skipped.", self.binary_path
            )
            return []
        except Exception as exc:
            logger.error("Failed to execute ruff on '%s': %s", file_path, exc)
            return []

        # Ruff returns 0 on clean, 1 on lint violations, >= 2 on fatal errors
        if res.returncode not in (0, 1):
            stderr_msg = res.stderr.decode("utf-8", errors="replace").strip()
            logger.warning(
                "Ruff exited with code %d for '%s': %s", res.returncode, file_path, stderr_msg
            )
            return []

        stdout_text = res.stdout.decode("utf-8", errors="replace")
        if not stdout_text.strip():
            return []

        try:
            raw_findings = json.loads(stdout_text)
        except json.JSONDecodeError as exc:
            logger.warning("Failed to decode Ruff JSON output for '%s': %s", file_path, exc)
            return []

        findings: list[Finding] = []
        for item in raw_findings:
            loc = item.get("location", {})
            row = loc.get("row")
            if row is None or row not in added_lines:
                # Crucial requirement: only keep findings on added lines!
                continue

            rule_code = item.get("code") or "RUFF"
            if not active_config.is_rule_enabled(rule_code):
                continue

            default_sev = default_ruff_severity(rule_code)
            severity = active_config.get_effective_severity(rule_code, default_sev)

            if severity < active_config.severity_threshold:
                continue

            rule_url = item.get("url")
            if not rule_url and rule_code:
                # Fallback URL for ruff documentation
                rule_url = f"https://docs.astral.sh/ruff/rules/{rule_code.lower()}/"

            message = item.get("message", "Lint finding")
            fix_dict = item.get("fix")
            suggested_fix = fix_dict.get("message") if isinstance(fix_dict, dict) else None

            findings.append(
                Finding(
                    file_path=file_path,
                    line=row,
                    rule_id=rule_code,
                    message=message,
                    severity=severity,
                    suggested_fix=suggested_fix,
                    rule_url=rule_url,
                    normalized_snippet=message.strip(),
                    extra={"linter": "ruff", "col": loc.get("column")},
                )
            )

        return findings
