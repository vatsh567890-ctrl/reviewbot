"""Review generation, fingerprinting, deduplication, and posting logic."""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Iterable, Optional

from reviewbot.config import ReviewBotConfig
from reviewbot.github.client import GitHubClient
from reviewbot.models import Finding, Severity

logger = logging.getLogger(__name__)

FINGERPRINT_RE = re.compile(r"<!--\s*reviewbot-fingerprint:([a-zA-Z0-9_\-]+)\s*-->")


def compute_fingerprint(file_path: str, rule_id: str, normalized_snippet: str) -> str:
    """Compute a deterministic SHA-256 fingerprint for finding deduplication."""
    norm_path = file_path.replace("\\", "/").strip()
    norm_rule = rule_id.strip()
    norm_snippet = " ".join(normalized_snippet.split())
    raw = f"{norm_path}:{norm_rule}:{norm_snippet}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def extract_existing_fingerprints(existing_comments: Iterable[dict[str, Any]]) -> set[str]:
    """Parse existing PR review comments and extract all reviewbot fingerprints."""
    fingerprints: set[str] = set()
    for comment in existing_comments:
        body = comment.get("body", "")
        for match in FINGERPRINT_RE.finditer(body):
            fingerprints.add(match.group(1))
    return fingerprints


def prioritize_findings(findings: list[Finding]) -> list[Finding]:
    """Sort findings by severity descending (error > warning > info), then file and line."""
    return sorted(
        findings,
        key=lambda f: (-f.severity.rank, f.file_path, f.line),
    )


def build_review_body(
    files_checked_count: int,
    findings: list[Finding],
    omitted_count: int,
    missing_test_files: list[str],
    llm_feedback: Optional[list[tuple[str, str]]] = None,
) -> str:
    """Generate the markdown summary text for the top-level PR review body."""
    error_count = sum(1 for f in findings if f.severity == Severity.ERROR)
    warn_count = sum(1 for f in findings if f.severity == Severity.WARNING)
    info_count = sum(1 for f in findings if f.severity == Severity.INFO)
    total_count = len(findings)

    lines = [
        "## 🤖 Automated Code Review Summary",
        "",
        f"- **Files analyzed**: {files_checked_count}",
        f"- **Total findings**: {total_count} (🔴 {error_count} error{'s' if error_count != 1 else ''}, "
        f"⚠️ {warn_count} warning{'s' if warn_count != 1 else ''}, "
        f"ℹ️ {info_count} info)",
        "",
    ]

    if omitted_count > 0:
        lines.extend(
            [
                f"> ⚠️ **Notice:** {omitted_count} lower-priority finding(s) were omitted "
                "because the maximum comment limit was reached.",
                "",
            ]
        )

    if missing_test_files:
        lines.extend(
            [
                "### 🧪 Missing Tests Warning",
                "The following changed source files do not appear to have corresponding test changes:",
                "",
            ]
        )
        for src_file in missing_test_files:
            lines.append(f"- `{src_file}`")
        lines.extend(
            [
                "",
                "_Consider adding unit tests to cover newly introduced or modified logic._",
                "",
            ]
        )

    if llm_feedback:
        lines.extend(
            [
                "### 🧠 High-Level Architecture Feedback",
                "",
            ]
        )
        for fname, ftext in llm_feedback:
            lines.extend(
                [
                    f"**`{fname}`**:",
                    ftext,
                    "",
                ]
            )

    if total_count == 0 and not missing_test_files and not llm_feedback:
        lines.extend(
            [
                "✅ **All checks passed!** No style violations or security patterns were detected on the changed lines.",
                "",
            ]
        )

    return "\n".join(lines).strip()


class ReviewOrchestrator:
    """Coordinates finding collection, deduplication, and GitHub review submission."""

    def __init__(self, client: GitHubClient, config: ReviewBotConfig):
        self.client = client
        self.config = config

    def process_and_post_review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        head_sha: str,
        files_checked_count: int,
        all_findings: list[Finding],
        missing_test_files: list[str],
        dry_run: bool = False,
        llm_feedback: Optional[list[tuple[str, str]]] = None,
    ) -> Optional[dict[str, Any]]:
        """Deduplicate findings against existing comments, cap, and submit PR review."""
        # 1. Fetch existing comments for deduplication
        existing_comments = self.client.get_pull_request_comments(owner, repo, pr_number)
        existing_fingerprints = extract_existing_fingerprints(existing_comments)
        logger.info(
            "Found %d existing review comments (%d reviewbot fingerprints).",
            len(existing_comments),
            len(existing_fingerprints),
        )

        # 2. Filter out already-commented findings
        new_findings: list[Finding] = []
        for f in all_findings:
            fp = compute_fingerprint(f.file_path, f.rule_id, f.normalized_snippet)
            if fp in existing_fingerprints:
                logger.debug(
                    "Skipping duplicate finding %s at %s:%d", f.rule_id, f.file_path, f.line
                )
                continue
            new_findings.append(f)

        # 3. Sort by priority
        prioritized = prioritize_findings(new_findings)

        # 4. Cap comments
        if len(prioritized) > self.config.max_comments:
            omitted_count = len(prioritized) - self.config.max_comments
            to_comment = prioritized[: self.config.max_comments]
        else:
            omitted_count = 0
            to_comment = prioritized

        # 5. Format review body
        review_body = build_review_body(
            files_checked_count=files_checked_count,
            findings=all_findings,
            omitted_count=omitted_count,
            missing_test_files=missing_test_files,
            llm_feedback=llm_feedback,
        )

        # 6. Determine review event
        has_error = any(f.severity == Severity.ERROR for f in all_findings)
        if self.config.request_changes_on_error and has_error:
            event = "REQUEST_CHANGES"
        else:
            event = "COMMENT"

        # 7. Prepare inline comments
        review_comments: list[dict[str, Any]] = []
        for f in to_comment:
            fp = compute_fingerprint(f.file_path, f.rule_id, f.normalized_snippet)
            review_comments.append(
                {
                    "path": f.file_path,
                    "line": f.line,
                    "side": "RIGHT",
                    "body": f.to_comment_body(fp),
                }
            )

        if dry_run:
            logger.info("[DRY RUN] Review payload prepared (not posted to GitHub API).")
            payload: dict[str, Any] = {
                "commit_id": head_sha,
                "body": review_body,
                "event": event,
                "comments": review_comments if review_comments else None,
            }
            return payload

        # Submit review
        logger.info(
            "Submitting review for PR #%d (event: %s, inline comments: %d, omitted: %d)",
            pr_number,
            event,
            len(review_comments),
            omitted_count,
        )

        result = self.client.create_pull_request_review(
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            commit_id=head_sha,
            body=review_body,
            event=event,
            comments=review_comments if review_comments else None,
        )

        return result
