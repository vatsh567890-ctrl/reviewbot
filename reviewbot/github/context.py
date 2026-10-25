"""GitHub Actions environment and PR context extraction."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class GitHubContext:
    """Encapsulates GitHub Actions pull request execution context."""

    owner: str
    repo: str
    pr_number: int
    head_sha: str
    base_sha: Optional[str]
    token: str
    config_path: str = ".reviewbot.yml"
    fail_on_error: bool = False

    @property
    def repository(self) -> str:
        return f"{self.owner}/{self.repo}"

    @classmethod
    def from_environment(
        cls,
        event_path: Optional[str] = None,
        token: Optional[str] = None,
        repository: Optional[str] = None,
        pr_number: Optional[int] = None,
        head_sha: Optional[str] = None,
        config_path: Optional[str] = None,
        fail_on_error: Optional[bool] = None,
    ) -> GitHubContext:
        """Parse context from GitHub Actions environment variables and event payload.

        Falls back to provided arguments if environment variables are not set.
        """
        # Resolve GitHub Token
        resolved_token = (
            token
            or os.environ.get("INPUT_GITHUB-TOKEN")
            or os.environ.get("INPUT_GITHUB_TOKEN")
            or os.environ.get("GITHUB_TOKEN")
        )
        if not resolved_token:
            raise ValueError(
                "GitHub token is missing. Please set GITHUB_TOKEN or provide github-token input."
            )

        # Resolve Repository
        resolved_repo = repository or os.environ.get("GITHUB_REPOSITORY") or ""

        resolved_event_path = event_path or os.environ.get("GITHUB_EVENT_PATH")
        event_data: dict[str, Any] = {}

        if resolved_event_path and Path(resolved_event_path).exists():
            try:
                content = Path(resolved_event_path).read_text(encoding="utf-8")
                event_data = json.loads(content)
            except Exception as exc:
                logger.warning("Failed to parse GITHUB_EVENT_PATH JSON file: %s", exc)

        # PR Number
        resolved_pr_number = pr_number
        if resolved_pr_number is None:
            if "pull_request" in event_data and "number" in event_data["pull_request"]:
                resolved_pr_number = int(event_data["pull_request"]["number"])
            elif "number" in event_data:
                resolved_pr_number = int(event_data["number"])
            elif "issue" in event_data and "number" in event_data["issue"]:
                resolved_pr_number = int(event_data["issue"]["number"])

        if resolved_pr_number is None:
            raise ValueError(
                "Pull request number could not be determined. "
                "Ensure this action runs on 'pull_request' events or provide --pr."
            )

        # Head SHA
        resolved_head_sha = head_sha
        if not resolved_head_sha and "pull_request" in event_data:
            resolved_head_sha = event_data["pull_request"].get("head", {}).get("sha")

        if not resolved_head_sha:
            resolved_head_sha = os.environ.get("GITHUB_SHA", "")

        if not resolved_head_sha:
            raise ValueError(
                "Head commit SHA could not be determined. "
                "Provide head SHA or ensure action is triggered by pull_request."
            )

        # Base SHA
        base_sha = None
        if "pull_request" in event_data:
            base_sha = event_data["pull_request"].get("base", {}).get("sha")

        # Repository name fallback from event
        if not resolved_repo and "repository" in event_data:
            resolved_repo = event_data["repository"].get("full_name", "")

        if not resolved_repo or "/" not in resolved_repo:
            raise ValueError(
                f"Invalid or missing GITHUB_REPOSITORY '{resolved_repo}'. Expected format 'owner/repo'."
            )

        owner, repo_name = resolved_repo.split("/", 1)

        # Config path
        resolved_config_path = (
            config_path
            or os.environ.get("INPUT_CONFIG-PATH")
            or os.environ.get("INPUT_CONFIG_PATH")
            or ".reviewbot.yml"
        )

        # Fail on error
        if fail_on_error is not None:
            resolved_fail_on_error = fail_on_error
        else:
            foe_env = (
                os.environ.get("INPUT_FAIL-ON-ERROR")
                or os.environ.get("INPUT_FAIL_ON_ERROR")
                or "false"
            )
            resolved_fail_on_error = foe_env.lower() in ("true", "1", "yes")

        return cls(
            owner=owner,
            repo=repo_name,
            pr_number=resolved_pr_number,
            head_sha=resolved_head_sha,
            base_sha=base_sha,
            token=resolved_token,
            config_path=resolved_config_path,
            fail_on_error=resolved_fail_on_error,
        )
