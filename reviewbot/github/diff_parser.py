"""Unified diff patch parser and added-line tracker."""

from __future__ import annotations

import fnmatch
import re
from pathlib import PurePath
from typing import Any, Iterable, Optional

from reviewbot.models import DiffFile

HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def parse_patch_added_lines(patch: Optional[str]) -> set[int]:
    """Parse a unified diff patch and return the 1-indexed line numbers of added/modified lines in the new file.

    Lines marked with '+' (added lines) belong to the new file at the current new-file line counter.
    Lines marked with ' ' (context) advance the new-file line counter.
    Lines marked with '-' (deleted) are not in the new file and do not advance the counter.
    """
    if not patch:
        return set()

    added_lines: set[int] = set()
    current_new_line: Optional[int] = None

    for raw_line in patch.splitlines():
        if raw_line.startswith("@@"):
            match = HUNK_HEADER_RE.match(raw_line)
            if match:
                current_new_line = int(match.group(3))
            else:
                current_new_line = None
            continue

        if current_new_line is None:
            continue

        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            added_lines.add(current_new_line)
            current_new_line += 1
        elif raw_line.startswith("-") and not raw_line.startswith("---"):
            # Deletion does not advance new line count
            continue
        elif raw_line.startswith(" ") or raw_line == "":
            current_new_line += 1
        elif raw_line.startswith("\\"):
            # "\ No newline at end of file"
            continue

    return added_lines


def is_path_ignored(file_path: str, ignore_patterns: Iterable[str]) -> bool:
    """Determine whether a file path matches any of the glob ignore patterns."""
    normalized = PurePath(file_path.replace("\\", "/"))
    normalized_str = str(normalized).replace("\\", "/")

    for pattern in ignore_patterns:
        clean_pattern = pattern.strip()
        if not clean_pattern:
            continue

        # Direct pattern match on full path or filename
        if fnmatch.fnmatch(normalized_str, clean_pattern):
            return True
        if fnmatch.fnmatch(normalized.name, clean_pattern):
            return True

        # Match wildcard paths like 'node_modules/**'
        if clean_pattern.endswith("/**"):
            prefix = clean_pattern[:-3]
            if normalized_str == prefix or normalized_str.startswith(f"{prefix}/"):
                return True

    return False


def parse_pull_request_file(
    raw_file_data: dict[str, Any],
    ignore_patterns: Iterable[str] = (),
) -> Optional[DiffFile]:
    """Convert raw GitHub pull request file payload into a structured DiffFile.

    Returns None if the file is deleted, binary, or matches ignore patterns.
    """
    filename = str(raw_file_data.get("filename", ""))
    status = str(raw_file_data.get("status", ""))
    patch = raw_file_data.get("patch")
    previous_filename = raw_file_data.get("previous_filename")

    # Skip deleted files
    if status == "removed":
        return None

    # Skip binary files (GitHub does not provide patches for binaries, or flags them)
    if raw_file_data.get("binary") is True:
        return None

    # Skip files matching ignore patterns
    if is_path_ignored(filename, ignore_patterns):
        return None

    added_lines = parse_patch_added_lines(patch)

    return DiffFile(
        filename=filename,
        status=status,
        patch=patch,
        added_lines=added_lines,
        is_binary=False,
        previous_filename=previous_filename,
    )
