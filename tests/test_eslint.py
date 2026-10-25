"""Unit tests for ESLint linter integration."""

import json
from unittest.mock import MagicMock, patch

from reviewbot.config import ReviewBotConfig
from reviewbot.linters.eslint import ESLintLinter
from reviewbot.models import Severity


def test_eslint_can_handle():
    linter = ESLintLinter()
    assert linter.can_handle("src/index.js") is True
    assert linter.can_handle("src/components/App.tsx") is True
    assert linter.can_handle("src/utils.ts") is True
    assert linter.can_handle("src/app.py") is False


def test_eslint_lint_filters_to_added_lines():
    linter = ESLintLinter(binary_path="eslint")

    mock_eslint_output = json.dumps(
        [
            {
                "filePath": "src/App.tsx",
                "messages": [
                    {
                        "ruleId": "no-unused-vars",
                        "severity": 2,
                        "message": "'unused' is defined but never used.",
                        "line": 4,
                        "column": 7,
                    },
                    {
                        "ruleId": "semi",
                        "severity": 1,
                        "message": "Missing semicolon.",
                        "line": 10,
                        "column": 20,
                    },
                ],
            }
        ]
    )

    mock_res = MagicMock()
    mock_res.returncode = 1
    mock_res.stdout = mock_eslint_output.encode("utf-8")
    mock_res.stderr = b""

    with patch("subprocess.run", return_value=mock_res):
        # Only line 4 is in added_lines; line 10 must be omitted
        findings = linter.lint("src/App.tsx", added_lines={4}, content="const unused = 1;\n")

    assert len(findings) == 1
    f = findings[0]
    assert f.file_path == "src/App.tsx"
    assert f.line == 4
    assert f.rule_id == "no-unused-vars"
    assert f.severity == Severity.ERROR
    assert "https://eslint.org/docs/latest/rules/no-unused-vars" in str(f.rule_url)


def test_eslint_respects_config_overrides():
    linter = ESLintLinter(binary_path="eslint")

    mock_eslint_output = json.dumps(
        [
            {
                "filePath": "src/App.js",
                "messages": [
                    {
                        "ruleId": "no-console",
                        "severity": 1,
                        "message": "Unexpected console statement.",
                        "line": 5,
                    }
                ],
            }
        ]
    )

    mock_res = MagicMock(returncode=1, stdout=mock_eslint_output.encode("utf-8"), stderr=b"")

    # Disabled rule
    cfg_disabled = ReviewBotConfig(disabled_rules=["no-console"])
    with patch("subprocess.run", return_value=mock_res):
        findings = linter.lint(
            "src/App.js", added_lines={5}, content="console.log()", config=cfg_disabled
        )
    assert len(findings) == 0

    # Severity override to ERROR
    cfg_override = ReviewBotConfig(rule_severities={"no-console": Severity.ERROR})
    with patch("subprocess.run", return_value=mock_res):
        findings = linter.lint(
            "src/App.js", added_lines={5}, content="console.log()", config=cfg_override
        )
    assert len(findings) == 1
    assert findings[0].severity == Severity.ERROR
