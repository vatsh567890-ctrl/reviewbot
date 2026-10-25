"""Integration and CLI tests for reviewbot."""

import json
from pathlib import Path

import httpx
import pytest
import respx

from reviewbot.cli import main, parse_args
from reviewbot.github.context import GitHubContext


def test_parse_args():
    args = parse_args(
        [
            "--config-path",
            "custom.yml",
            "--pr",
            "42",
            "--repo",
            "octocat/hello",
            "--head-sha",
            "sha123",
            "--token",
            "gh-tok",
            "--fail-on-error",
            "--verbose",
        ]
    )
    assert args.config_path == "custom.yml"
    assert args.pr_number == 42
    assert args.repository == "octocat/hello"
    assert args.head_sha == "sha123"
    assert args.token == "gh-tok"
    assert args.fail_on_error is True
    assert args.verbose is True


def test_github_context_from_event(tmp_path: Path):
    event_file = tmp_path / "event.json"
    event_data = {
        "pull_request": {
            "number": 99,
            "head": {"sha": "headsha99"},
        },
        "repository": {"full_name": "owner/repo"},
    }
    event_file.write_text(json.dumps(event_data), encoding="utf-8")

    ctx = GitHubContext.from_environment(
        event_path=str(event_file),
        token="tok123",
    )
    assert ctx.owner == "owner"
    assert ctx.repo == "repo"
    assert ctx.pr_number == 99
    assert ctx.head_sha == "headsha99"
    assert ctx.token == "tok123"


def test_github_context_missing_token():
    with pytest.raises(ValueError, match="GitHub token is missing"):
        GitHubContext.from_environment(
            token="",
            repository="owner/repo",
            pr_number=1,
            head_sha="sha",
        )


@respx.mock
def test_cli_end_to_end_clean_run(tmp_path: Path, monkeypatch):
    # Set up dummy clean python file
    clean_py = tmp_path / "clean.py"
    clean_py.write_text("def hello():\n    return 'world'\n", encoding="utf-8")

    # Mock GitHub Files endpoint
    files_url = "https://api.github.com/repos/owner/repo/pulls/1/files?per_page=100"
    respx.get(files_url).mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "filename": str(clean_py),
                    "status": "modified",
                    "patch": "@@ -1,2 +1,2 @@\n def hello():\n+    return 'world'\n",
                }
            ],
        )
    )

    # Mock Comments endpoint
    comments_url = "https://api.github.com/repos/owner/repo/pulls/1/comments?per_page=100"
    respx.get(comments_url).mock(return_value=httpx.Response(200, json=[]))

    # Mock Review creation endpoint
    reviews_url = "https://api.github.com/repos/owner/repo/pulls/1/reviews"
    review_mock = respx.post(reviews_url).mock(return_value=httpx.Response(200, json={"id": 100}))

    exit_code = main(
        [
            "--pr",
            "1",
            "--repo",
            "owner/repo",
            "--head-sha",
            "sha123",
            "--token",
            "mock-token",
        ]
    )

    assert exit_code == 0
    assert review_mock.called


@respx.mock
def test_cli_end_to_end_fail_on_error(tmp_path: Path):
    # Set up dirty file with hardcoded secret
    dirty_py = tmp_path / "dirty.py"
    dirty_py.write_text('api_key = "AKIA1234567890EXAMPLE"\n', encoding="utf-8")

    files_url = "https://api.github.com/repos/owner/repo/pulls/1/files?per_page=100"
    respx.get(files_url).mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "filename": str(dirty_py),
                    "status": "added",
                    "patch": '@@ -0,0 +1,1 @@\n+api_key = "AKIA1234567890EXAMPLE"\n',
                }
            ],
        )
    )

    comments_url = "https://api.github.com/repos/owner/repo/pulls/1/comments?per_page=100"
    respx.get(comments_url).mock(return_value=httpx.Response(200, json=[]))

    reviews_url = "https://api.github.com/repos/owner/repo/pulls/1/reviews"
    respx.post(reviews_url).mock(return_value=httpx.Response(200, json={"id": 101}))

    # 1. With --fail-on-error, should exit with 1
    exit_code = main(
        [
            "--pr",
            "1",
            "--repo",
            "owner/repo",
            "--head-sha",
            "sha123",
            "--token",
            "mock-token",
            "--fail-on-error",
        ]
    )
    assert exit_code == 1

    # 2. Without --fail-on-error, should exit with 0 (non-blocking default)
    exit_code_default = main(
        [
            "--pr",
            "1",
            "--repo",
            "owner/repo",
            "--head-sha",
            "sha123",
            "--token",
            "mock-token",
        ]
    )
    assert exit_code_default == 0


@respx.mock
def test_cli_dry_run_does_not_post_review(tmp_path: Path):
    clean_py = tmp_path / "clean.py"
    clean_py.write_text("x = 1\n", encoding="utf-8")

    files_url = "https://api.github.com/repos/owner/repo/pulls/1/files?per_page=100"
    respx.get(files_url).mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "filename": str(clean_py),
                    "status": "modified",
                    "patch": "@@ -0,0 +1,1 @@\n+x = 1\n",
                }
            ],
        )
    )

    comments_url = "https://api.github.com/repos/owner/repo/pulls/1/comments?per_page=100"
    respx.get(comments_url).mock(return_value=httpx.Response(200, json=[]))

    reviews_url = "https://api.github.com/repos/owner/repo/pulls/1/reviews"
    reviews_route = respx.post(reviews_url).mock(return_value=httpx.Response(200, json={}))

    exit_code = main(
        [
            "--pr",
            "1",
            "--repo",
            "owner/repo",
            "--head-sha",
            "sha123",
            "--token",
            "mock-token",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    # reviews_route must NOT be called in dry-run mode
    assert not reviews_route.called
