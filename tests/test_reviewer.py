"""Unit tests for review orchestrator, deduplication, capping, and review payload construction."""

import httpx
import respx

from reviewbot.config import ReviewBotConfig
from reviewbot.github.client import GitHubClient
from reviewbot.models import Finding, Severity
from reviewbot.reviewer import (
    ReviewOrchestrator,
    build_review_body,
    compute_fingerprint,
    extract_existing_fingerprints,
    prioritize_findings,
)


def test_compute_fingerprint_deterministic():
    fp1 = compute_fingerprint("src/app.py", "SEC001", "api_key = '***'")
    fp2 = compute_fingerprint("src/app.py", "SEC001", "api_key   =   '***'")
    fp3 = compute_fingerprint("src/other.py", "SEC001", "api_key = '***'")

    assert fp1 == fp2  # normalized whitespace
    assert fp1 != fp3


def test_extract_existing_fingerprints():
    comments = [
        {"body": "Hello world\n<!-- reviewbot-fingerprint:12345abcde -->"},
        {"body": "Another comment without marker"},
        {"body": "Third comment <!-- reviewbot-fingerprint:67890fghij -->"},
    ]
    fps = extract_existing_fingerprints(comments)
    assert fps == {"12345abcde", "67890fghij"}


def test_prioritize_findings():
    f_info = Finding("a.py", 1, "INFO1", "msg", Severity.INFO)
    f_warn = Finding("b.py", 2, "WARN1", "msg", Severity.WARNING)
    f_err = Finding("c.py", 3, "ERR1", "msg", Severity.ERROR)

    sorted_findings = prioritize_findings([f_info, f_err, f_warn])
    assert sorted_findings == [f_err, f_warn, f_info]


def test_build_review_body_with_findings_and_missing_tests():
    findings = [
        Finding("a.py", 1, "SEC001", "msg", Severity.ERROR),
        Finding("b.py", 2, "W291", "msg", Severity.WARNING),
    ]
    body = build_review_body(
        files_checked_count=5,
        findings=findings,
        omitted_count=2,
        missing_test_files=["src/service.py"],
    )
    assert "**Files analyzed**: 5" in body
    assert "**Total findings**: 2" in body
    assert "🔴 1 error" in body
    assert "⚠️ 1 warning" in body
    assert "2 lower-priority finding(s) were omitted" in body
    assert "Missing Tests Warning" in body
    assert "`src/service.py`" in body


def test_build_review_body_clean_pass():
    body = build_review_body(
        files_checked_count=3,
        findings=[],
        omitted_count=0,
        missing_test_files=[],
    )
    assert "All checks passed!" in body


@respx.mock
def test_review_orchestrator_deduplication_and_capping():
    client = GitHubClient(token="mock-token", base_url="https://api.github.com")
    config = ReviewBotConfig(max_comments=1)  # Cap at 1 comment

    f1 = Finding(
        "src/foo.py", 10, "SEC001", "Hardcoded key", Severity.ERROR, normalized_snippet="key1"
    )
    f2 = Finding(
        "src/bar.py", 20, "W001", "Trailing space", Severity.WARNING, normalized_snippet="space"
    )
    f_existing = Finding(
        "src/dup.py", 5, "SEC002", "eval call", Severity.ERROR, normalized_snippet="eval()"
    )
    existing_fp = compute_fingerprint("src/dup.py", "SEC002", "eval()")

    # Mock comments endpoint returning an existing comment
    comments_url = "https://api.github.com/repos/octocat/repo/pulls/1/comments?per_page=100"
    respx.get(comments_url).mock(
        return_value=httpx.Response(
            200,
            json=[{"body": f"Old comment\n<!-- reviewbot-fingerprint:{existing_fp} -->"}],
        )
    )

    # Mock review creation endpoint
    reviews_url = "https://api.github.com/repos/octocat/repo/pulls/1/reviews"
    review_route = respx.post(reviews_url).mock(return_value=httpx.Response(200, json={"id": 123}))

    orchestrator = ReviewOrchestrator(client=client, config=config)
    orchestrator.process_and_post_review(
        owner="octocat",
        repo="repo",
        pr_number=1,
        head_sha="commit-sha",
        files_checked_count=3,
        all_findings=[f_existing, f2, f1],  # f_existing should be skipped; f1 prioritized over f2
        missing_test_files=[],
    )

    assert review_route.called
    payload = review_route.calls.last.request.read().decode("utf-8")
    # f1 (ERROR) should be the single posted comment
    assert "SEC001" in payload
    # f2 should be omitted due to max_comments=1 cap
    assert "W001" not in payload
    assert "1 lower-priority finding(s) were omitted" in payload


@respx.mock
def test_review_orchestrator_request_changes_on_error():
    client = GitHubClient(token="mock-token", base_url="https://api.github.com")
    config = ReviewBotConfig(request_changes_on_error=True)

    f_err = Finding("src/foo.py", 10, "SEC001", "Key", Severity.ERROR, normalized_snippet="k")

    comments_url = "https://api.github.com/repos/octocat/repo/pulls/1/comments?per_page=100"
    respx.get(comments_url).mock(return_value=httpx.Response(200, json=[]))

    reviews_url = "https://api.github.com/repos/octocat/repo/pulls/1/reviews"
    review_route = respx.post(reviews_url).mock(return_value=httpx.Response(200, json={"id": 123}))

    orchestrator = ReviewOrchestrator(client=client, config=config)
    orchestrator.process_and_post_review(
        owner="octocat",
        repo="repo",
        pr_number=1,
        head_sha="commit-sha",
        files_checked_count=1,
        all_findings=[f_err],
        missing_test_files=[],
    )

    assert review_route.called
    payload = review_route.calls.last.request.read().decode("utf-8")
    assert '"event":"REQUEST_CHANGES"' in payload.replace(" ", "")


@respx.mock
def test_review_orchestrator_dry_run():
    client = GitHubClient(token="mock-token", base_url="https://api.github.com")
    config = ReviewBotConfig()

    f_err = Finding("src/foo.py", 10, "SEC001", "Key", Severity.ERROR, normalized_snippet="k")

    comments_url = "https://api.github.com/repos/octocat/repo/pulls/1/comments?per_page=100"
    respx.get(comments_url).mock(return_value=httpx.Response(200, json=[]))

    reviews_url = "https://api.github.com/repos/octocat/repo/pulls/1/reviews"
    review_route = respx.post(reviews_url).mock(return_value=httpx.Response(200, json={"id": 123}))

    orchestrator = ReviewOrchestrator(client=client, config=config)
    result = orchestrator.process_and_post_review(
        owner="octocat",
        repo="repo",
        pr_number=1,
        head_sha="commit-sha",
        files_checked_count=1,
        all_findings=[f_err],
        missing_test_files=[],
        dry_run=True,
    )

    # In dry-run mode, review_route must NOT be called
    assert not review_route.called
    assert result is not None
    assert result["commit_id"] == "commit-sha"
    assert result["event"] == "COMMENT"
    assert len(result["comments"]) == 1
    assert result["comments"][0]["path"] == "src/foo.py"
