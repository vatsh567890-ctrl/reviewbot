"""Main command line interface and GitHub Action entrypoint."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from reviewbot.config import ReviewBotConfig, load_config
from reviewbot.github.client import GitHubClient
from reviewbot.github.context import GitHubContext
from reviewbot.github.diff_parser import parse_pull_request_file
from reviewbot.linters.base import BaseLinter
from reviewbot.linters.eslint import ESLintLinter
from reviewbot.linters.ruff import RuffLinter
from reviewbot.llm.reviewer import LLMReviewer
from reviewbot.missing_tests.detector import detect_missing_tests
from reviewbot.models import Finding, Severity
from reviewbot.reviewer import ReviewOrchestrator
from reviewbot.security.registry import SecurityRegistry

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("reviewbot")


def parse_args(args: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse CLI options and flags."""
    parser = argparse.ArgumentParser(description="Automated PR Code Review Bot for GitHub Actions.")
    parser.add_argument(
        "--config-path",
        dest="config_path",
        default=None,
        help="Path to .reviewbot.yml configuration file.",
    )
    parser.add_argument(
        "--pr",
        dest="pr_number",
        type=int,
        default=None,
        help="Pull request number (defaults to GitHub Actions environment).",
    )
    parser.add_argument(
        "--repo",
        dest="repository",
        default=None,
        help="Repository full name 'owner/repo' (defaults to GitHub Actions environment).",
    )
    parser.add_argument(
        "--head-sha",
        dest="head_sha",
        default=None,
        help="PR Head commit SHA (defaults to GitHub Actions environment).",
    )
    parser.add_argument(
        "--token",
        dest="token",
        default=None,
        help="GitHub Personal Access Token or Actions GITHUB_TOKEN.",
    )
    parser.add_argument(
        "--fail-on-error",
        dest="fail_on_error",
        action="store_true",
        default=None,
        help="Exit with non-zero status if any error-level finding is detected.",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=False,
        help="Print the review payload to stdout instead of posting to GitHub API.",
    )
    parser.add_argument(
        "--llm-review",
        dest="llm_review",
        action="store_true",
        default=False,
        help="Enable optional LLM-assisted higher-level architectural review (requires API key).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging output.",
    )
    return parser.parse_args(args)


def run_review(
    context: GitHubContext,
    config: ReviewBotConfig,
    dry_run: bool = False,
    llm_review: bool = False,
) -> int:
    """Execute review pipeline on pull request files."""
    logger.info(
        "Starting review on %s#%d (head: %s)",
        context.repository,
        context.pr_number,
        context.head_sha[:8] if context.head_sha else "",
    )

    with GitHubClient(token=context.token) as client:
        # 1. Fetch changed files
        logger.info("Fetching changed files from GitHub...")
        raw_files = client.get_pull_request_files(context.owner, context.repo, context.pr_number)
        logger.info("Retrieved %d changed file(s).", len(raw_files))

        # 2. Check for missing tests
        all_changed_paths = [rf.get("filename", "") for rf in raw_files if "filename" in rf]
        missing_test_files = detect_missing_tests(all_changed_paths, config)
        if missing_test_files:
            logger.warning("Missing test coverage suspected for: %s", ", ".join(missing_test_files))

        # 3. Parse diff patches & filter files
        diff_files = []
        for raw_f in raw_files:
            parsed = parse_pull_request_file(raw_f, ignore_patterns=config.ignore_paths)
            if parsed is not None and parsed.added_lines:
                diff_files.append(parsed)

        logger.info("%d file(s) qualify for inspection after filtering.", len(diff_files))

        # 4. Initialize analyzers
        linters: list[BaseLinter] = [RuffLinter(), ESLintLinter()]
        security_registry = SecurityRegistry()
        llm_reviewer = LLMReviewer() if llm_review else None

        all_findings: list[Finding] = []
        llm_feedback: list[tuple[str, str]] = []

        # 5. Analyze each file
        for df in diff_files:
            file_path = df.filename
            content: Optional[str] = None
            local_path = Path(file_path)

            if local_path.is_file():
                try:
                    content = local_path.read_text(encoding="utf-8", errors="replace")
                except Exception as exc:
                    logger.warning("Could not read local file '%s': %s", file_path, exc)

            # A. Linting (Ruff for Python, ESLint for JS/TS)
            for linter in linters:
                if linter.can_handle(file_path):
                    lint_findings = linter.lint(
                        file_path=file_path,
                        added_lines=df.added_lines,
                        content=content,
                        config=config,
                    )
                    all_findings.extend(lint_findings)

            # B. Security Rules
            if content:
                sec_findings = security_registry.run_checks(
                    file_path=file_path,
                    added_lines=df.added_lines,
                    content=content,
                    config=config,
                )
                all_findings.extend(sec_findings)

            # C. Optional LLM Architectural Review
            if llm_reviewer and df.patch:
                feedback = llm_reviewer.review_diff(file_path, df.patch)
                if feedback:
                    llm_feedback.append((file_path, feedback))

        logger.info("Analysis complete: %d total finding(s) detected.", len(all_findings))

        # 6. Post review to GitHub
        orchestrator = ReviewOrchestrator(client=client, config=config)
        orchestrator.process_and_post_review(
            owner=context.owner,
            repo=context.repo,
            pr_number=context.pr_number,
            head_sha=context.head_sha,
            files_checked_count=len(diff_files),
            all_findings=all_findings,
            missing_test_files=missing_test_files,
            dry_run=dry_run,
            llm_feedback=llm_feedback if llm_feedback else None,
        )

        # 7. Determine exit code
        has_error = any(f.severity == Severity.ERROR for f in all_findings)
        should_fail = (context.fail_on_error is True) and has_error

        if should_fail:
            logger.error(
                "Error-level findings detected and fail-on-error is enabled. Exiting with 1."
            )
            return 1

        logger.info("Review completed successfully.")
        return 0


def main(args: Optional[list[str]] = None) -> int:
    """Entrypoint function for CLI and GitHub Action."""
    parsed_args = parse_args(args)

    if parsed_args.verbose:
        logger.setLevel(logging.DEBUG)

    try:
        # Load GitHub environment context
        context = GitHubContext.from_environment(
            token=parsed_args.token,
            repository=parsed_args.repository,
            pr_number=parsed_args.pr_number,
            head_sha=parsed_args.head_sha,
            config_path=parsed_args.config_path,
            fail_on_error=parsed_args.fail_on_error,
        )

        # Load configuration
        config = load_config(context.config_path)

        return run_review(
            context=context,
            config=config,
            dry_run=parsed_args.dry_run,
            llm_review=parsed_args.llm_review,
        )

    except Exception as exc:
        logger.error("Reviewbot execution failed: %s", exc, exc_info=parsed_args.verbose)
        return 1


if __name__ == "__main__":
    sys.exit(main())
