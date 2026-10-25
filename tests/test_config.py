"""Tests for configuration loading, schema validation, and severity filtering."""

from pathlib import Path

import pytest

from reviewbot.config import ReviewBotConfig, load_config
from reviewbot.models import Severity


def test_default_config():
    cfg = ReviewBotConfig()
    assert cfg.max_comments == 30
    assert cfg.severity_threshold == Severity.INFO
    assert cfg.request_changes_on_error is False
    assert cfg.is_rule_enabled("SEC001") is True
    assert cfg.is_rule_enabled("RUFF") is True


def test_rule_enabling_and_disabling():
    cfg = ReviewBotConfig(
        enabled_rules=["SEC001", "SEC002"],
        disabled_rules=["SEC002"],
    )
    # Disabled takes precedence
    assert cfg.is_rule_enabled("SEC001") is True
    assert cfg.is_rule_enabled("SEC002") is False
    assert cfg.is_rule_enabled("SEC003") is False


def test_effective_severity_override():
    cfg = ReviewBotConfig(rule_severities={"SEC002": Severity.WARNING, "F401": Severity.INFO})
    assert cfg.get_effective_severity("SEC002", Severity.ERROR) == Severity.WARNING
    assert cfg.get_effective_severity("F401", Severity.ERROR) == Severity.INFO
    assert cfg.get_effective_severity("SEC001", Severity.ERROR) == Severity.ERROR


def test_severity_ordering():
    assert Severity.ERROR > Severity.WARNING
    assert Severity.WARNING > Severity.INFO
    assert Severity.INFO < Severity.ERROR
    assert Severity.ERROR >= Severity.ERROR


def test_load_config_missing_file_returns_defaults(tmp_path: Path):
    non_existent = tmp_path / ".reviewbot.yml"
    cfg = load_config(non_existent)
    assert cfg.max_comments == 30
    assert cfg.severity_threshold == Severity.INFO


def test_load_config_valid_yaml(tmp_path: Path):
    cfg_file = tmp_path / ".reviewbot.yml"
    cfg_file.write_text(
        """
max_comments: 15
severity_threshold: "warning"
request_changes_on_error: true
disabled_rules:
  - "E501"
rule_severities:
  SEC002: "error"
""",
        encoding="utf-8",
    )
    cfg = load_config(cfg_file)
    assert cfg.max_comments == 15
    assert cfg.severity_threshold == Severity.WARNING
    assert cfg.request_changes_on_error is True
    assert cfg.is_rule_enabled("E501") is False
    assert cfg.get_effective_severity("SEC002", Severity.INFO) == Severity.ERROR


def test_load_config_invalid_yaml_syntax(tmp_path: Path):
    cfg_file = tmp_path / ".reviewbot.yml"
    cfg_file.write_text("invalid: [yaml: unclosed", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid YAML in configuration"):
        load_config(cfg_file)


def test_load_config_invalid_schema_field(tmp_path: Path):
    cfg_file = tmp_path / ".reviewbot.yml"
    cfg_file.write_text("severity_threshold: 'super_critical'", encoding="utf-8")
    with pytest.raises(ValueError, match="Configuration validation error"):
        load_config(cfg_file)


def test_load_config_non_dict_yaml(tmp_path: Path):
    cfg_file = tmp_path / ".reviewbot.yml"
    cfg_file.write_text("- item1\n- item2", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a YAML mapping/dictionary"):
        load_config(cfg_file)
