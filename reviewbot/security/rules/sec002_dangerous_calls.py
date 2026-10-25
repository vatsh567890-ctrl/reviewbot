"""SEC002: Detection of dangerous runtime function calls."""

from __future__ import annotations

import re
from typing import Optional

from reviewbot.models import Finding, Severity
from reviewbot.security.base import SecurityRule

EVAL_RE = re.compile(r"\beval\s*\(")
EXEC_RE = re.compile(r"\bexec\s*\(")
SHELL_TRUE_RE = re.compile(
    r"""(?:subprocess\.(?:run|call|check_call|check_output|Popen)|os\.system)\s*\(.*?\bshell\s*=\s*True""",
    re.DOTALL,
)
INLINE_SHELL_TRUE_RE = re.compile(r"\bshell\s*=\s*True\b")
YAML_LOAD_RE = re.compile(r"\byaml\.load\s*\(")
YAML_SAFE_LOADER_RE = re.compile(r"\bLoader\s*=\s*(?:yaml\.)?(?:SafeLoader|CSafeLoader|BaseLoader)")
VERIFY_FALSE_RE = re.compile(
    r"""(?:requests|httpx)\.[a-zA-Z_]+\s*\(.*?\bverify\s*=\s*False\b|\bverify\s*=\s*False\b"""
)
PICKLE_LOAD_RE = re.compile(r"\bpickle\.(?:loads|load)\s*\(")


class DangerousCallsRule(SecurityRule):
    """Detects dangerous invocations like eval, exec, shell=True, yaml.load, pickle, verify=False."""

    @property
    def id(self) -> str:
        return "SEC002"

    @property
    def name(self) -> str:
        return "Dangerous Function Call Detection"

    @property
    def description(self) -> str:
        return "Flags usage of functions prone to code injection, MitM attacks, or deserialization exploits."

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

        # Skip comment lines
        if stripped.startswith("#"):
            return []

        # 1. eval()
        if EVAL_RE.search(line_content):
            findings.append(
                Finding(
                    file_path=file_path,
                    line=line_number,
                    rule_id=self.id,
                    message="Use of `eval()` detected. It allows arbitrary code execution on untrusted input.",
                    severity=Severity.ERROR,
                    suggested_fix="Use `ast.literal_eval()` if parsing Python literals, or use safe domain-specific parsers.",
                    normalized_snippet=stripped,
                )
            )

        # 2. exec()
        if EXEC_RE.search(line_content):
            findings.append(
                Finding(
                    file_path=file_path,
                    line=line_number,
                    rule_id=self.id,
                    message="Use of `exec()` detected. Dynamic code execution is unsafe.",
                    severity=Severity.ERROR,
                    suggested_fix="Avoid `exec()`. Refactor dynamic behavior into static dispatch functions or dictionaries.",
                    normalized_snippet=stripped,
                )
            )

        # 3. subprocess with shell=True
        if INLINE_SHELL_TRUE_RE.search(line_content):
            findings.append(
                Finding(
                    file_path=file_path,
                    line=line_number,
                    rule_id=self.id,
                    message="Subprocess call with `shell=True` is susceptible to command injection.",
                    severity=Severity.ERROR,
                    suggested_fix="Pass command arguments as a list (e.g. `['command', 'arg1']`) and use default `shell=False`.",
                    normalized_snippet=stripped,
                )
            )

        # 4. yaml.load without SafeLoader
        if YAML_LOAD_RE.search(line_content):
            # Check if Loader=yaml.SafeLoader is provided on this line or nearby
            has_safe_loader = bool(YAML_SAFE_LOADER_RE.search(line_content))
            if not has_safe_loader and full_content:
                # In case call spans multiple lines
                has_safe_loader = bool(YAML_SAFE_LOADER_RE.search(full_content))

            if not has_safe_loader:
                findings.append(
                    Finding(
                        file_path=file_path,
                        line=line_number,
                        rule_id=self.id,
                        message="`yaml.load()` without SafeLoader can instantiate arbitrary Python objects.",
                        severity=Severity.ERROR,
                        suggested_fix="Use `yaml.safe_load()` instead of `yaml.load()`.",
                        normalized_snippet=stripped,
                    )
                )

        # 5. verify=False (TLS verification disabled)
        if VERIFY_FALSE_RE.search(line_content):
            findings.append(
                Finding(
                    file_path=file_path,
                    line=line_number,
                    rule_id=self.id,
                    message="Disabled TLS verification (`verify=False`) exposes network calls to Man-in-the-Middle attacks.",
                    severity=Severity.WARNING,
                    suggested_fix="Remove `verify=False` and supply trusted CA certificates if necessary.",
                    normalized_snippet=stripped,
                )
            )

        # 6. pickle.loads / pickle.load
        if PICKLE_LOAD_RE.search(line_content):
            findings.append(
                Finding(
                    file_path=file_path,
                    line=line_number,
                    rule_id=self.id,
                    message="`pickle.loads()`/`pickle.load()` on untrusted data can lead to arbitrary code execution.",
                    severity=Severity.ERROR,
                    suggested_fix="Use a safer serialization format such as JSON, Protocol Buffers, or messagepack.",
                    normalized_snippet=stripped,
                )
            )

        return findings
