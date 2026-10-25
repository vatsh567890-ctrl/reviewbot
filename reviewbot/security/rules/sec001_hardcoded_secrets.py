"""SEC001: Detection of hardcoded credentials, API keys, and private keys."""

from __future__ import annotations

import re
from typing import Optional

from reviewbot.models import Finding, Severity
from reviewbot.security.base import SecurityRule

# AWS Access Key Pattern (starts with AKIA and 16 uppercase alphanumeric chars)
AWS_KEY_RE = re.compile(r"\b(AKIA[0-9A-Z]{16})\b")

# Private key headers
PRIVATE_KEY_RE = re.compile(r"-----BEGIN\s+[A-Z0-9 ]*PRIVATE KEY-----")

# Generic credential assignments
GENERIC_SECRET_RE = re.compile(
    r"""(?i)\b(api[_-]?key|secret[_-]?key|secret|password|passwd|auth[_-]?token|access[_-]?token|private[_-]?token)\s*(=|:)\s*(['"])([^'"]+)\3"""
)

# Common non-secret placeholder tokens to avoid false positives
BENIGN_PLACEHOLDERS = {
    "password",
    "pass",
    "test",
    "testing",
    "example",
    "changeme",
    "placeholder",
    "dummy",
    "secret",
    "your_key",
    "your_api_key",
    "your_secret_here",
    "none",
    "null",
    "true",
    "false",
    "default",
}


def redact_line(line: str) -> str:
    """Redact hardcoded secrets from a line snippet."""
    # Redact AWS keys
    redacted = AWS_KEY_RE.sub(r"AKIA****************", line)

    # Redact generic secret assignments
    def _redact_generic(match: re.Match[str]) -> str:
        var_name = match.group(1)
        sep = match.group(2)
        quote = match.group(3)
        return f"{var_name} {sep} {quote}********{quote}"

    redacted = GENERIC_SECRET_RE.sub(_redact_generic, redacted)

    # Redact private key payload if present
    if PRIVATE_KEY_RE.search(redacted):
        redacted = PRIVATE_KEY_RE.sub("-----BEGIN [REDACTED] PRIVATE KEY-----", redacted)

    return redacted


class HardcodedSecretsRule(SecurityRule):
    """Detects hardcoded secrets, AWS keys, and private keys."""

    @property
    def id(self) -> str:
        return "SEC001"

    @property
    def name(self) -> str:
        return "Hardcoded Secret Detection"

    @property
    def description(self) -> str:
        return "Detects hardcoded credentials such as AWS keys, API secrets, and private keys."

    @property
    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check_line(
        self,
        file_path: str,
        line_number: int,
        line_content: str,
        full_content: Optional[str] = None,
    ) -> list[Finding]:
        findings: list[Finding] = []
        stripped = line_content.strip()

        # 1. AWS Key Check
        aws_match = AWS_KEY_RE.search(line_content)
        if aws_match:
            findings.append(
                Finding(
                    file_path=file_path,
                    line=line_number,
                    rule_id=self.id,
                    message="Hardcoded AWS Access Key ID detected. The key has been redacted.",
                    severity=self.default_severity,
                    suggested_fix="Store AWS credentials in environment variables (e.g. `AWS_ACCESS_KEY_ID`) or GitHub Secrets.",
                    normalized_snippet=redact_line(stripped),
                )
            )
            return findings

        # 2. Private Key Header Check
        if PRIVATE_KEY_RE.search(line_content):
            findings.append(
                Finding(
                    file_path=file_path,
                    line=line_number,
                    rule_id=self.id,
                    message="Private key header detected in source file.",
                    severity=self.default_severity,
                    suggested_fix="Never commit private keys to version control. Store keys in a secure secret store or GitHub Secrets.",
                    normalized_snippet=redact_line(stripped),
                )
            )
            return findings

        # 3. Generic Secret Assignment Check
        generic_match = GENERIC_SECRET_RE.search(line_content)
        if generic_match:
            val = generic_match.group(4)
            if len(val) >= 8 and val.lower().strip() not in BENIGN_PLACEHOLDERS:
                findings.append(
                    Finding(
                        file_path=file_path,
                        line=line_number,
                        rule_id=self.id,
                        message="Potential hardcoded secret or credential literal detected. Value has been redacted.",
                        severity=self.default_severity,
                        suggested_fix="Load secrets dynamically from environment variables or a configuration secrets manager.",
                        normalized_snippet=redact_line(stripped),
                    )
                )

        return findings
