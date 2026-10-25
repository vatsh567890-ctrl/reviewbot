"""Registry and runner for security rules."""

from __future__ import annotations

import logging
from typing import Iterable, Optional

from reviewbot.config import ReviewBotConfig
from reviewbot.models import Finding
from reviewbot.security.base import SecurityRule
from reviewbot.security.rules import (
    DangerousCallsRule,
    HardcodedSecretsRule,
    SQLInjectionRule,
)

logger = logging.getLogger(__name__)


class SecurityRegistry:
    """Registry maintaining active security inspection rules."""

    def __init__(self, rules: Optional[Iterable[SecurityRule]] = None):
        self._rules: dict[str, SecurityRule] = {}
        if rules is None:
            self._register_defaults()
        else:
            for rule in rules:
                self.register(rule)

    def _register_defaults(self) -> None:
        """Register standard out-of-the-box rules."""
        self.register(HardcodedSecretsRule())
        self.register(DangerousCallsRule())
        self.register(SQLInjectionRule())

    def register(self, rule: SecurityRule) -> None:
        """Register a new or custom security rule."""
        self._rules[rule.id] = rule

    def unregister(self, rule_id: str) -> None:
        """Remove a rule by ID."""
        self._rules.pop(rule_id, None)

    def get_rule(self, rule_id: str) -> Optional[SecurityRule]:
        """Retrieve a registered rule by its ID."""
        return self._rules.get(rule_id)

    @property
    def rules(self) -> list[SecurityRule]:
        """List of all registered rules."""
        return list(self._rules.values())

    def run_checks(
        self,
        file_path: str,
        added_lines: set[int],
        content: str,
        config: Optional[ReviewBotConfig] = None,
    ) -> list[Finding]:
        """Run all enabled security rules on added lines and filter by severity threshold."""
        if not added_lines or not content:
            return []

        active_config = config or ReviewBotConfig()
        lines = content.splitlines()
        findings: list[Finding] = []

        for rule in self._rules.values():
            if not active_config.is_rule_enabled(rule.id):
                continue

            raw_findings = rule.check_file(
                file_path=file_path,
                added_lines=added_lines,
                lines=lines,
                full_content=content,
                config=active_config,
            )

            for f in raw_findings:
                # Apply configured severity overrides and threshold
                effective_sev = active_config.get_effective_severity(f.rule_id, f.severity)
                if effective_sev < active_config.severity_threshold:
                    continue

                if effective_sev != f.severity:
                    f = Finding(
                        file_path=f.file_path,
                        line=f.line,
                        rule_id=f.rule_id,
                        message=f.message,
                        severity=effective_sev,
                        suggested_fix=f.suggested_fix,
                        rule_url=f.rule_url or rule.docs_url,
                        normalized_snippet=f.normalized_snippet,
                        extra=f.extra,
                    )
                findings.append(f)

        return findings
