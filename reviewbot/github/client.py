"""GitHub REST API client using httpx with automatic retry and backoff."""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Optional, cast

import httpx

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://api.github.com"
NEXT_LINK_RE = re.compile(r'<([^>]+)>;\s*rel="next"')
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class GitHubAPIError(Exception):
    """Raised when GitHub API returns an unrecoverable non-2xx response."""

    def __init__(self, status_code: int, message: str, response_body: Any = None):
        super().__init__(f"GitHub API error {status_code}: {message}")
        self.status_code = status_code
        self.response_body = response_body


class GitHubClient:
    """Client for interacting with GitHub Pull Request REST APIs with retry and rate-limit handling."""

    def __init__(
        self,
        token: str,
        base_url: str = DEFAULT_API_BASE,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
    ):
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "reviewbot-github-action",
        }
        self.client = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=timeout,
        )

    def __repr__(self) -> str:
        # Never leak authorization token in repr
        return f"<GitHubClient base_url={self.base_url!r}>"

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def _request_with_retry(
        self,
        method: str,
        url: str,
        params: Optional[dict[str, Any]] = None,
        json_data: Optional[dict[str, Any]] = None,
    ) -> httpx.Response:
        """Execute HTTP request with exponential backoff for rate limits (429) and transient 5xx errors."""
        attempt = 0
        while True:
            try:
                resp = self.client.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json_data,
                )

                if resp.status_code in RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                    attempt += 1
                    # Inspect Retry-After header
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after and retry_after.strip().isdigit():
                        delay = max(0.5, float(retry_after.strip()))
                    else:
                        delay = self.backoff_factor * (2 ** (attempt - 1))

                    logger.warning(
                        "GitHub API returned %d (%s). Retrying in %.2fs (attempt %d/%d)...",
                        resp.status_code,
                        resp.reason_phrase,
                        delay,
                        attempt,
                        self.max_retries,
                    )
                    time.sleep(delay)
                    continue

                return resp

            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
                if attempt < self.max_retries:
                    attempt += 1
                    delay = self.backoff_factor * (2 ** (attempt - 1))
                    logger.warning(
                        "Transient network error (%s). Retrying in %.2fs (attempt %d/%d)...",
                        type(exc).__name__,
                        delay,
                        attempt,
                        self.max_retries,
                    )
                    time.sleep(delay)
                    continue
                raise

    def _paginate(self, path: str, params: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
        """Fetch all items from a paginated GitHub endpoint."""
        results: list[dict[str, Any]] = []
        url: Optional[str] = path
        current_params = dict(params or {})
        current_params.setdefault("per_page", 100)

        while url:
            resp = self._request_with_retry("GET", url, params=current_params)
            # Clear params for subsequent paginated URLs because Link headers already contain query params
            current_params = {}

            if resp.status_code >= 400:
                raise GitHubAPIError(
                    resp.status_code,
                    resp.text,
                    resp.json()
                    if resp.headers.get("content-type", "").startswith("application/json")
                    else None,
                )

            data = resp.json()
            if isinstance(data, list):
                results.extend(data)
            else:
                break

            # Check Link header for next page
            link_header = resp.headers.get("Link", "")
            next_match = NEXT_LINK_RE.search(link_header)
            if next_match:
                url = next_match.group(1)
            else:
                url = None

        return results

    def get_pull_request_files(self, owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
        """Fetch all changed files for a pull request (paginated)."""
        path = f"/repos/{owner}/{repo}/pulls/{pr_number}/files"
        return self._paginate(path)

    def get_pull_request_comments(
        self, owner: str, repo: str, pr_number: int
    ) -> list[dict[str, Any]]:
        """Fetch all review comments on a pull request (paginated)."""
        path = f"/repos/{owner}/{repo}/pulls/{pr_number}/comments"
        return self._paginate(path)

    def create_pull_request_review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        commit_id: str,
        body: str,
        event: str = "COMMENT",
        comments: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """Submit a pull request review with a summary body and inline comments."""
        path = f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
        payload: dict[str, Any] = {
            "commit_id": commit_id,
            "body": body,
            "event": event,
        }
        if comments:
            payload["comments"] = comments

        resp = self._request_with_retry("POST", path, json_data=payload)
        if resp.status_code >= 400:
            error_data = None
            try:
                error_data = resp.json()
            except Exception:
                pass
            raise GitHubAPIError(resp.status_code, resp.text, error_data)

        return cast(dict[str, Any], resp.json())
