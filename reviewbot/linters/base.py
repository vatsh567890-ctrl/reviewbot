"""Base interface for code linters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from reviewbot.config import ReviewBotConfig
from reviewbot.models import Finding


class BaseLinter(ABC):
    """Abstract base class for linter integrations."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the linter (e.g. 'ruff', 'eslint')."""
        pass

    @abstractmethod
    def can_handle(self, file_path: str) -> bool:
        """Return True if this linter handles the given file."""
        pass

    @abstractmethod
    def lint(
        self,
        file_path: str,
        added_lines: set[int],
        content: Optional[str] = None,
        config: Optional[ReviewBotConfig] = None,
    ) -> list[Finding]:
        """Run lint checks on the file and return findings for added lines only."""
        pass
