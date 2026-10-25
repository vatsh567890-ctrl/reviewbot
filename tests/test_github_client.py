"""Unit tests for GitHub REST API client using respx mocks."""

import httpx
import pytest
import respx

from reviewbot.github.client import GitHubAPIError, GitHubClient


@respx.mock
def test_get_pull_request_files_paginated():
    client = GitHubClient(token="mock-token", base_url="https://api.github.com")

    files_route = respx.get("https://api.github.com/repos/octocat/hello-world/pulls/10/files")
    files_route.side_effect = [
        httpx.Response(
            200,
            json=[{"filename": "src/file1.py", "status": "added"}],
            headers={
                "Link": '<https://api.github.com/repos/octocat/hello-world/pulls/10/files?page=2>; rel="next"'
            },
        ),
        httpx.Response(
            200,
            json=[{"filename": "src/file2.py", "status": "modified"}],
        ),
    ]

    files = client.get_pull_request_files("octocat", "hello-world", 10)
    assert len(files) == 2
    assert files[0]["filename"] == "src/file1.py"
    assert files[1]["filename"] == "src/file2.py"


@respx.mock
def test_get_pull_request_comments():
    client = GitHubClient(token="mock-token", base_url="https://api.github.com")
    url = "https://api.github.com/repos/octocat/hello-world/pulls/10/comments?per_page=100"

    respx.get(url).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 1, "body": "Existing comment <!-- reviewbot-fingerprint:abc12345 -->"}],
        )
    )

    comments = client.get_pull_request_comments("octocat", "hello-world", 10)
    assert len(comments) == 1
    assert "abc12345" in comments[0]["body"]


@respx.mock
def test_create_pull_request_review():
    client = GitHubClient(token="mock-token", base_url="https://api.github.com")
    url = "https://api.github.com/repos/octocat/hello-world/pulls/10/reviews"

    mock_route = respx.post(url).mock(
        return_value=httpx.Response(
            200,
            json={"id": 999, "state": "COMMENTED"},
        )
    )

    resp = client.create_pull_request_review(
        owner="octocat",
        repo="hello-world",
        pr_number=10,
        commit_id="head-sha-123",
        body="## Review Summary",
        event="COMMENT",
        comments=[{"path": "src/foo.py", "line": 5, "side": "RIGHT", "body": "Test comment"}],
    )

    assert resp["id"] == 999
    assert mock_route.called
    sent_payload = mock_route.calls.last.request.read().decode("utf-8")
    assert "head-sha-123" in sent_payload
    assert "src/foo.py" in sent_payload


@respx.mock
def test_github_api_error_handling():
    client = GitHubClient(token="mock-token", base_url="https://api.github.com")
    url = "https://api.github.com/repos/octocat/hello-world/pulls/10/files?per_page=100"

    respx.get(url).mock(
        return_value=httpx.Response(
            401,
            json={"message": "Bad credentials"},
        )
    )

    with pytest.raises(GitHubAPIError) as exc_info:
        client.get_pull_request_files("octocat", "hello-world", 10)

    assert exc_info.value.status_code == 401
