"""ESLint linter integration for JavaScript and TypeScript files."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from reviewbot.config import ReviewBotConfig
from reviewbot.linters.base import BaseLinter
from reviewbot.models import Finding, Severity

logger = logging.getLogger(__name__)

JS_TS_EXTENSIONS = (
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".mts",
    ".cts",
)


def resolve_eslint_executable(custom_binary: Optional[str] = None) -> Optional[str]:
    """Locate the eslint or npx binary in PATH."""
    if custom_binary:
        return custom_binary

    which_eslint = shutil.which("eslint")
    if which_eslint:
        return which_eslint

    which_npx = shutil.which("npx")
    if which_npx:
        return which_npx

    return None


class ESLintLinter(BaseLinter):
    """Executes ESLint via subprocess to lint JavaScript and TypeScript files."""

    def __init__(self, binary_path: Optional[str] = None):
        self.binary_path = resolve_eslint_executable(binary_path)

    @property
    def name(self) -> str:
        return "eslint"

    def can_handle(self, file_path: str) -> bool:
        norm = file_path.lower()
        return any(norm.endswith(ext) for ext in JS_TS_EXTENSIONS)

    def lint(
        self,
        file_path: str,
        added_lines: set[int],
        content: Optional[str] = None,
        config: Optional[ReviewBotConfig] = None,
    ) -> list[Finding]:
        if not added_lines:
            return []

        if not self.binary_path:
            logger.debug("Neither 'eslint' nor 'npx' found in PATH. Skipping ESLint checks.")
            return []

        active_config = config or ReviewBotConfig()

        # Build command: use direct eslint or 'npx --no-install eslint'
        if self.binary_path.endswith("npx") or self.binary_path.endswith("npx.cmd"):
            cmd = [self.binary_path, "--no-install", "eslint", "--format", "json"]
        else:
            cmd = [self.binary_path, "--format", "json"]

        stdin_data: Optional[bytes] = None
        if content is not None:
            cmd.extend(["--stdin", "--stdin-filename", file_path])
            stdin_data = content.encode("utf-8")
        elif Path(file_path).exists():
            cmd.append(file_path)
        else:
            logger.debug("File '%s' not found on disk. Skipping ESLint.", file_path)
            return []

        try:
            res = subprocess.run(
                cmd,
                input=stdin_data,
                capture_output=True,
                check=False,
            )
        except FileNotFoundError:
            logger.warning("ESLint executable not found at '%s'.", self.binary_path)
            return []
        except Exception as exc:
            logger.error("Failed to execute ESLint on '%s': %s", file_path, exc)
            return []

        # ESLint exits 0 on clean, 1 on lint errors
        if res.returncode not in (0, 1):
            stderr_msg = res.stderr.decode("utf-8", errors="replace").strip()
            logger.debug(
                "ESLint non-zero exit %d for '%s': %s", res.returncode, file_path, stderr_msg
            )
            # Some environments exit 2 on config error; try parsing stdout if JSON was produced
            if not res.stdout:
                return []

        stdout_text = res.stdout.decode("utf-8", errors="replace").strip()
        if not stdout_text:
            return []

        try:
            results = json.loads(stdout_text)
        except json.JSONDecodeError as exc:
            logger.debug("Failed to decode ESLint JSON output: %s", exc)
            return []

        findings: list[Finding] = []
        for file_result in results:
            for msg in file_result.get("messages", []):
                line = msg.get("line")
                if line is None or line not in added_lines:
                    continue

                rule_id = msg.get("ruleId") or "eslint"
                if not active_config.is_rule_enabled(rule_id):
                    continue

                # ESLint: severity 1 = warning, 2 = error
                raw_sev = msg.get("severity", 2)
                default_sev = Severity.ERROR if raw_sev == 2 else Severity.WARNING
                severity = active_config.get_effective_severity(rule_id, default_sev)

                if severity < active_config.severity_threshold:
                    continue

                rule_url = (
                    f"https://eslint.org/docs/latest/rules/{rule_id}"
                    if rule_id != "eslint"
                    else None
                )
                message = msg.get("message", "Lint finding")

                findings.append(
                    Finding(
                        file_path=file_path,
                        line=line,
                        rule_id=rule_id,
                        message=message,
                        severity=severity,
                        rule_url=rule_url,
                        normalized_snippet=message.strip(),
                        extra={"linter": "eslint", "column": msg.get("column")},
                    )
                )

        return findings
