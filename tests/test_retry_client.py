"""Unit tests for GitHubClient retry, backoff, and rate limit handling."""

import httpx
import pytest
import respx

from reviewbot.github.client import GitHubAPIError, GitHubClient


def test_client_repr_never_leaks_token():
    client = GitHubClient(token="ghp_super_secret_token_123456789")
    repr_str = repr(client)
    assert "ghp_super_secret_token" not in repr_str
    assert "GitHubClient" in repr_str


@respx.mock
def test_client_retries_on_429_rate_limit(monkeypatch):
    # Shorten sleep during tests so execution is immediate
    monkeypatch.setattr("time.sleep", lambda s: None)

    client = GitHubClient(
        token="mock-token",
        base_url="https://api.github.com",
        max_retries=2,
        backoff_factor=0.01,
    )

    route = respx.get("https://api.github.com/repos/owner/repo/pulls/1/files")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "1"}, json={"message": "rate limited"}),
        httpx.Response(200, json=[{"filename": "src/app.py", "status": "modified"}]),
    ]

    files = client.get_pull_request_files("owner", "repo", 1)
    assert len(files) == 1
    assert files[0]["filename"] == "src/app.py"
    assert route.call_count == 2


@respx.mock
def test_client_retries_on_503_transient_error(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)

    client = GitHubClient(
        token="mock-token",
        base_url="https://api.github.com",
        max_retries=3,
        backoff_factor=0.01,
    )

    route = respx.get("https://api.github.com/repos/owner/repo/pulls/1/comments")
    route.side_effect = [
        httpx.Response(503, text="Service Unavailable"),
        httpx.Response(200, json=[]),
    ]

    comments = client.get_pull_request_comments("owner", "repo", 1)
    assert comments == []
    assert route.call_count == 2


@respx.mock
def test_client_exhausts_retries_on_persistent_500(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)

    client = GitHubClient(
        token="mock-token",
        base_url="https://api.github.com",
        max_retries=2,
        backoff_factor=0.01,
    )

    route = respx.get("https://api.github.com/repos/owner/repo/pulls/1/files")
    route.side_effect = [
        httpx.Response(500, text="Internal Server Error"),
        httpx.Response(500, text="Internal Server Error"),
        httpx.Response(500, text="Internal Server Error"),
    ]

    with pytest.raises(GitHubAPIError) as exc_info:
        client.get_pull_request_files("owner", "repo", 1)

    assert exc_info.value.status_code == 500
    assert route.call_count == 3  # initial + 2 retries
