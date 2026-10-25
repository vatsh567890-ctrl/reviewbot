"""Base classes and interfaces for security rules."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from reviewbot.config import ReviewBotConfig
from reviewbot.models import Finding, Severity


class SecurityRule(ABC):
    """Abstract base class for a security inspection rule."""

    @property
    @abstractmethod
    def id(self) -> str:
        """Unique identifier for the rule (e.g. 'SEC001')."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of the rule."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Brief summary of what the rule detects."""
        pass

    @property
    def default_severity(self) -> Severity:
        """Default severity level when not overridden by configuration."""
        return Severity.ERROR

    @property
    def docs_url(self) -> Optional[str]:
        """Optional documentation link for the security rule."""
        return None

    @abstractmethod
    def check_line(
        self,
        file_path: str,
        line_number: int,
        line_content: str,
        full_content: Optional[str] = None,
    ) -> list[Finding]:
        """Analyze a single added line and return any security findings."""
        pass

    def check_file(
        self,
        file_path: str,
        added_lines: set[int],
        lines: list[str],
        full_content: str,
        config: Optional[ReviewBotConfig] = None,
    ) -> list[Finding]:
        """Run checks across all added lines in a file."""
        findings: list[Finding] = []
        for line_no in sorted(added_lines):
            if 1 <= line_no <= len(lines):
                line_content = lines[line_no - 1]
                line_findings = self.check_line(
                    file_path=file_path,
                    line_number=line_no,
                    line_content=line_content,
                    full_content=full_content,
                )
                findings.extend(line_findings)
        return findings
