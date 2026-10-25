"""Pytest fixtures and mock payload factories for reviewbot tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reviewbot.config import ReviewBotConfig
from reviewbot.models import Finding, Severity

SAMPLE_DIFF_PATCH = """@@ -10,6 +10,8 @@ def existing_function():
     x = 1
     y = 2
+    api_key = "AKIA1234567890EXAMPLE"
+    result = eval("x + y")
     return result
"""

SAMPLE_SQL_DIFF_PATCH = """@@ -1,4 +1,5 @@
 def query_db(user_id):
-    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
+    cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
     return cursor.fetchall()
"""


@pytest.fixture(autouse=True)
def clean_github_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear GitHub Actions environment variables before each test."""
    vars_to_clear = [
        "GITHUB_TOKEN",
        "GITHUB_REPOSITORY",
        "GITHUB_SHA",
        "GITHUB_EVENT_PATH",
        "INPUT_GITHUB_TOKEN",
        "INPUT_GITHUB-TOKEN",
        "INPUT_CONFIG_PATH",
        "INPUT_FAIL_ON_ERROR",
    ]
    for var in vars_to_clear:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def sample_config() -> ReviewBotConfig:
    return ReviewBotConfig(
        max_comments=10,
        severity_threshold=Severity.INFO,
        source_paths=["src/"],
        test_patterns=["tests/**/test_*.py"],
        request_changes_on_error=False,
    )


@pytest.fixture
def mock_event_payload(tmp_path: Path) -> Path:
    event_file = tmp_path / "event.json"
    event_data = {
        "pull_request": {
            "number": 42,
            "head": {"sha": "abc123def456"},
            "base": {"sha": "base123sha456"},
        },
        "repository": {
            "full_name": "octocat/hello-world",
        },
    }
    event_file.write_text(json.dumps(event_data), encoding="utf-8")
    return event_file


@pytest.fixture
def sample_finding() -> Finding:
    return Finding(
        file_path="src/service.py",
        line=12,
        rule_id="SEC001",
        message="Hardcoded AWS Access Key ID detected.",
        severity=Severity.ERROR,
        suggested_fix="Store AWS credentials in environment variables.",
        rule_url="https://docs.example.com/sec001",
        normalized_snippet='api_key = "AKIA****************"',
    )
