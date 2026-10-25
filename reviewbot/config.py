"""Configuration schema and loading for reviewbot."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from reviewbot.models import Severity

logger = logging.getLogger(__name__)

DEFAULT_IGNORE_PATHS = [
    ".git/**",
    ".github/**",
    "node_modules/**",
    ".venv/**",
    "venv/**",
    "dist/**",
    "build/**",
    "*.min.js",
    "*.min.css",
    "*.lock",
    "package-lock.json",
    "uv.lock",
    "poetry.lock",
]

DEFAULT_SOURCE_PATHS = [
    "src/",
    "app/",
    "lib/",
]

DEFAULT_TEST_PATTERNS = [
    "tests/test_*.py",
    "tests/*_test.py",
    "tests/**/test_*.py",
    "tests/**/*_test.py",
    "test/test_*.py",
    "test/**/test_*.py",
    "**/tests/test_*.py",
]


class ReviewBotConfig(BaseModel):
    """Configuration options for the PR code review bot."""

    enabled_rules: Optional[list[str]] = Field(
        default=None,
        description="Explicit list of rule IDs to run. If None, all non-disabled rules run.",
    )
    disabled_rules: list[str] = Field(
        default_factory=list,
        description="List of rule IDs to disable.",
    )
    severity_threshold: Severity = Field(
        default=Severity.INFO,
        description="Minimum severity level required to report a finding (info, warning, error).",
    )
    max_comments: int = Field(
        default=30,
        ge=1,
        description="Maximum number of inline comments posted in a single PR review.",
    )
    ignore_paths: list[str] = Field(
        default_factory=lambda: list(DEFAULT_IGNORE_PATHS),
        description="Glob patterns for files to exclude from analysis.",
    )
    source_paths: list[str] = Field(
        default_factory=lambda: list(DEFAULT_SOURCE_PATHS),
        description="Root paths where application source code resides for test checks.",
    )
    test_patterns: list[str] = Field(
        default_factory=lambda: list(DEFAULT_TEST_PATTERNS),
        description="Glob patterns for test files.",
    )
    request_changes_on_error: bool = Field(
        default=False,
        description="If True and error findings exist, submit review with REQUEST_CHANGES.",
    )
    rule_severities: dict[str, Severity] = Field(
        default_factory=dict,
        description="Rule ID to severity overrides.",
    )

    @field_validator("severity_threshold", mode="before")
    @classmethod
    def parse_severity(cls, value: Any) -> Severity:
        if isinstance(value, Severity):
            return value
        if isinstance(value, str):
            try:
                return Severity(value.lower().strip())
            except ValueError as err:
                raise ValueError(
                    f"Invalid severity '{value}'. Allowed values are: 'info', 'warning', 'error'."
                ) from err
        raise ValueError(f"Invalid severity value: {value}")

    @field_validator("rule_severities", mode="before")
    @classmethod
    def parse_rule_severities(cls, value: Any) -> dict[str, Severity]:
        if not isinstance(value, dict):
            raise ValueError("rule_severities must be a dictionary of rule_id: severity")
        parsed = {}
        for k, v in value.items():
            if isinstance(v, Severity):
                parsed[str(k)] = v
            elif isinstance(v, str):
                try:
                    parsed[str(k)] = Severity(v.lower().strip())
                except ValueError as err:
                    raise ValueError(
                        f"Invalid severity '{v}' for rule '{k}'. Allowed: 'info', 'warning', 'error'."
                    ) from err
            else:
                raise ValueError(f"Invalid severity value '{v}' for rule '{k}'.")
        return parsed

    def is_rule_enabled(self, rule_id: str) -> bool:
        """Check if a given rule ID is active according to the configuration."""
        if rule_id in self.disabled_rules:
            return False
        if self.enabled_rules is not None:
            return rule_id in self.enabled_rules
        return True

    def get_effective_severity(self, rule_id: str, default_severity: Severity) -> Severity:
        """Get the configured severity override for a rule, or default."""
        return self.rule_severities.get(rule_id, default_severity)


def load_config(config_path: Optional[str | Path] = None) -> ReviewBotConfig:
    """Load and validate configuration from YAML file, or return default config.

    Raises:
        ValueError: If YAML is malformed or schema validation fails.
    """
    path = Path(config_path) if config_path else Path(".reviewbot.yml")

    if not path.exists():
        logger.debug("Configuration file '%s' not found. Using default settings.", path)
        return ReviewBotConfig()

    try:
        content = path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        if data is None:
            # Empty file
            return ReviewBotConfig()
        if not isinstance(data, dict):
            raise ValueError(
                f"Configuration file at '{path}' must be a YAML mapping/dictionary, got {type(data).__name__}."
            )
        return ReviewBotConfig(**data)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in configuration file '{path}': {exc}") from exc
    except ValidationError as exc:
        formatted_errors = []
        for error in exc.errors():
            loc = " -> ".join(str(item) for item in error["loc"])
            formatted_errors.append(f"  - {loc}: {error['msg']}")
        errors_summary = "\n".join(formatted_errors)
        raise ValueError(f"Configuration validation error in '{path}':\n{errors_summary}") from exc
