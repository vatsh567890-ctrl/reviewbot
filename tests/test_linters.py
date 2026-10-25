"""Unit tests for linter integrations and Ruff subprocess execution."""

from reviewbot.config import ReviewBotConfig
from reviewbot.linters.base import BaseLinter
from reviewbot.linters.ruff import RuffLinter, default_ruff_severity
from reviewbot.models import Finding, Severity


def test_ruff_can_handle():
    linter = RuffLinter()
    assert linter.can_handle("src/app.py") is True
    assert linter.can_handle("stubs/types.pyi") is True
    assert linter.can_handle("frontend/app.ts") is False
    assert linter.can_handle("README.md") is False


def test_default_ruff_severity():
    assert default_ruff_severity("F401") == Severity.ERROR
    assert default_ruff_severity("B006") == Severity.ERROR
    assert default_ruff_severity("E501") == Severity.WARNING
    assert default_ruff_severity("W291") == Severity.WARNING
    assert default_ruff_severity("I001") == Severity.INFO


def test_ruff_lint_filters_strictly_to_added_lines():
    linter = RuffLinter()
    # Lines:
    # 1: import sys  (unused import -> F401)
    # 2: import os   (unused import -> F401)
    # 3: x = 1
    content = "import sys\nimport os\nx = 1\n"

    # Suppose only line 2 was added in the PR diff
    added_lines = {2}
    findings = linter.lint("dummy.py", added_lines=added_lines, content=content)

    # Must only report line 2, never line 1
    assert len(findings) == 1
    assert findings[0].line == 2
    assert findings[0].rule_id == "F401"
    assert "os" in findings[0].message
    assert findings[0].rule_url is not None


def test_ruff_handles_subprocess_error():
    linter = RuffLinter(binary_path="non_existent_binary_xyz_123")
    findings = linter.lint("test.py", added_lines={1}, content="x = 1\n")
    assert findings == []


def test_ruff_respects_config_disabled_rules():
    linter = RuffLinter()
    content = "import sys\n"
    config = ReviewBotConfig(disabled_rules=["F401"])
    findings = linter.lint("dummy.py", added_lines={1}, content=content, config=config)
    assert len(findings) == 0


def test_base_linter_subclass_extensibility():
    """Demonstrate how an ESLint or custom linter implements BaseLinter."""

    class ESLintLinter(BaseLinter):
        @property
        def name(self) -> str:
            return "eslint"

        def can_handle(self, file_path: str) -> bool:
            return file_path.endswith((".js", ".jsx", ".ts", ".tsx"))

        def lint(self, file_path, added_lines, content=None, config=None):
            findings = []
            if 5 in added_lines:
                findings.append(
                    Finding(
                        file_path=file_path,
                        line=5,
                        rule_id="no-unused-vars",
                        message="'foo' is defined but never used.",
                        severity=Severity.WARNING,
                    )
                )
            return findings

    eslint = ESLintLinter()
    assert eslint.can_handle("src/app.tsx") is True
    assert eslint.can_handle("src/app.py") is False

    findings = eslint.lint("src/app.tsx", added_lines={5})
    assert len(findings) == 1
    assert findings[0].rule_id == "no-unused-vars"
