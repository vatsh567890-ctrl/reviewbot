"""Core data models and enums for reviewbot."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Severity(str, Enum):
    """Finding severity levels, ordered by priority."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"

    @property
    def rank(self) -> int:
        """Numerical rank for sorting and threshold comparison."""
        ranks = {
            Severity.INFO: 1,
            Severity.WARNING: 2,
            Severity.ERROR: 3,
        }
        return ranks[self]

    def __ge__(self, other: Any) -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        return self.rank >= other.rank

    def __gt__(self, other: Any) -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        return self.rank > other.rank

    def __le__(self, other: Any) -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        return self.rank <= other.rank

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        return self.rank < other.rank


@dataclass(frozen=True)
class Finding:
    """Represents a code review finding on a specific file and line."""

    file_path: str
    line: int
    rule_id: str
    message: str
    severity: Severity
    suggested_fix: Optional[str] = None
    rule_url: Optional[str] = None
    normalized_snippet: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_comment_body(self, fingerprint: str) -> str:
        """Format the finding as a GitHub pull request inline review comment."""
        severity_badges = {
            Severity.ERROR: "🔴 **Error**",
            Severity.WARNING: "⚠️ **Warning**",
            Severity.INFO: "ℹ️ **Info**",
        }

        badge = severity_badges.get(self.severity, "⚠️ **Notice**")
        rule_display = (
            f"[`{self.rule_id}`]({self.rule_url})" if self.rule_url else f"`{self.rule_id}`"
        )

        lines = [
            f"{badge} ({rule_display}): {self.message}",
            "",
        ]

        if self.suggested_fix:
            lines.extend(
                [
                    "**Suggested fix:**",
                    f"{self.suggested_fix}",
                    "",
                ]
            )

        lines.append(f"<!-- reviewbot-fingerprint:{fingerprint} -->")
        return "\n".join(lines)


@dataclass
class DiffFile:
    """Metadata and added line numbers for a changed file in a pull request."""

    filename: str
    status: str  # e.g., 'added', 'modified', 'removed', 'renamed'
    patch: Optional[str] = None
    added_lines: set[int] = field(default_factory=set)
    is_binary: bool = False
    previous_filename: Optional[str] = None

    @property
    def is_deleted(self) -> bool:
        return self.status == "removed"
