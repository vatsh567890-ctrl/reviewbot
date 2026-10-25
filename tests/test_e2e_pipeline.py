"""End-to-end pipeline integration test asserting the exact GitHub review payload."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from reviewbot.cli import main
from reviewbot.reviewer import compute_fingerprint


@respx.mock
def test_full_pipeline_e2e_asserts_exact_review_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)

    # 1. Create realistic source file on disk
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    source_file = src_dir / "auth.py"

    file_content = """# Authentication module
import os

def authenticate(user_id, token):
    # Existing safe line
    print("Authenticating...")
    aws_key = "AKIA1234567890EXAMPL"
    query = f"SELECT * FROM users WHERE id = {user_id}"
    return aws_key, query
"""
    source_file.write_text(file_content, encoding="utf-8")

    # Relative path as GitHub reports it
    rel_path = "src/auth.py"

    # Unified diff patch corresponding to lines 7 and 8 additions
    patch_diff = """@@ -4,4 +4,6 @@ def authenticate(user_id, token):
 def authenticate(user_id, token):
     # Existing safe line
     print("Authenticating...")
+    aws_key = "AKIA1234567890EXAMPL"
+    query = f"SELECT * FROM users WHERE id = {user_id}"
     return aws_key, query
"""

    # 2. Mock GitHub API endpoints
    # A. GET /repos/acme/my-service/pulls/101/files
    files_url = "https://api.github.com/repos/acme/my-service/pulls/101/files"
    respx.get(files_url).mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "filename": rel_path,
                    "status": "modified",
                    "patch": patch_diff,
                }
            ],
        )
    )

    # B. GET /repos/acme/my-service/pulls/101/comments
    comments_url = "https://api.github.com/repos/acme/my-service/pulls/101/comments"
    respx.get(comments_url).mock(return_value=httpx.Response(200, json=[]))

    # C. POST /repos/acme/my-service/pulls/101/reviews
    reviews_url = "https://api.github.com/repos/acme/my-service/pulls/101/reviews"
    review_post_route = respx.post(reviews_url).mock(
        return_value=httpx.Response(
            200,
            json={"id": 8888, "state": "COMMENTED"},
        )
    )

    # 3. Create .reviewbot.yml configuration file
    cfg_file = tmp_path / ".reviewbot.yml"
    cfg_file.write_text(
        """
max_comments: 10
severity_threshold: "info"
source_paths:
  - "src/"
test_patterns:
  - "tests/**/test_*.py"
request_changes_on_error: false
""",
        encoding="utf-8",
    )

    # 4. Run main() pointing to our local directory
    exit_code = main(
        [
            "--pr",
            "101",
            "--repo",
            "acme/my-service",
            "--head-sha",
            "c0ffee1234567890abcdef",
            "--token",
            "ghp_mock_token_for_e2e_test",
            "--config-path",
            str(cfg_file),
        ]
    )

    assert exit_code == 0
    assert review_post_route.called
    assert review_post_route.call_count == 1

    # 5. Extract and assert the EXACT JSON review payload sent to GitHub
    raw_body = review_post_route.calls.last.request.read().decode("utf-8")
    payload = json.loads(raw_body)

    # Verify top-level payload attributes
    assert payload["commit_id"] == "c0ffee1234567890abcdef"
    assert payload["event"] == "COMMENT"

    # Verify review summary body structure
    body_text = payload["body"]
    assert "## 🤖 Automated Code Review Summary" in body_text
    assert "- **Files analyzed**: 1" in body_text
    assert "- **Total findings**: 2 (🔴 2 errors, ⚠️ 0 warnings, ℹ️ 0 info)" in body_text
    assert "### 🧪 Missing Tests Warning" in body_text
    assert "- `src/auth.py`" in body_text

    # Verify inline comments array
    comments = payload["comments"]
    assert len(comments) == 2

    # Comment 1: Hardcoded AWS secret on line 7
    comment_1 = comments[0]
    assert comment_1["path"] == "src/auth.py"
    assert comment_1["line"] == 7
    assert comment_1["side"] == "RIGHT"
    assert "🔴 **Error** (`SEC001`)" in comment_1["body"]
    assert "Hardcoded AWS Access Key ID detected" in comment_1["body"]
    # Verify strict secret value redaction (actual key must NEVER be in comment body)
    assert "AKIA1234567890EXAMPL" not in comment_1["body"]
    fp_1 = compute_fingerprint("src/auth.py", "SEC001", 'aws_key = "AKIA****************"')
    assert f"<!-- reviewbot-fingerprint:{fp_1} -->" in comment_1["body"]

    # Comment 2: SQL Injection on line 8
    comment_2 = comments[1]
    assert comment_2["path"] == "src/auth.py"
    assert comment_2["line"] == 8
    assert comment_2["side"] == "RIGHT"
    assert "🔴 **Error** (`SEC003`)" in comment_2["body"]
    assert "Possible SQL injection" in comment_2["body"]
    assert "Use parameterized queries" in comment_2["body"]
    fp_2 = compute_fingerprint(
        "src/auth.py",
        "SEC003",
        'query = f"SELECT * FROM users WHERE id = {user_id}"',
    )
    assert f"<!-- reviewbot-fingerprint:{fp_2} -->" in comment_2["body"]

    # Token must NEVER appear in request body
    assert "ghp_mock_token_for_e2e_test" not in raw_body
