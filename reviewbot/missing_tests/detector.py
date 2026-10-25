"""Heuristic detection of PR source changes missing test updates."""

from __future__ import annotations

import fnmatch
from pathlib import PurePath
from typing import Iterable

from reviewbot.config import ReviewBotConfig


def is_matching_pattern(path: str, patterns: Iterable[str]) -> bool:
    """Check if a path matches any glob pattern."""
    normalized = path.replace("\\", "/")
    pure = PurePath(normalized)
    name = pure.name

    for pat in patterns:
        clean_pat = pat.strip().replace("\\", "/")
        if not clean_pat:
            continue
        try:
            if pure.match(clean_pat):
                return True
        except ValueError:
            pass
        if fnmatch.fnmatch(normalized, clean_pat):
            return True
        if fnmatch.fnmatch(name, clean_pat):
            return True
        # Handle /**/ matching 0 directories: tests/**/test_*.py -> tests/test_*.py
        if "/**/" in clean_pat:
            collapsed = clean_pat.replace("/**/", "/")
            if fnmatch.fnmatch(normalized, collapsed):
                return True
            try:
                if pure.match(collapsed):
                    return True
            except ValueError:
                pass
        # Handle **/prefix patterns
        if clean_pat.startswith("**/"):
            tail = clean_pat[3:]
            if fnmatch.fnmatch(normalized, tail):
                return True
            try:
                if pure.match(tail):
                    return True
            except ValueError:
                pass
    return False


def is_source_file(path: str, source_paths: Iterable[str], test_patterns: Iterable[str]) -> bool:
    """Determine whether a file is a source code file subject to test checks."""
    normalized = path.replace("\\", "/")
    pure = PurePath(normalized)

    # Exclude non-python or non-source files
    if pure.suffix not in (".py", ".ts", ".js", ".jsx", ".tsx"):
        return False

    # Exclude init files and migration scripts
    if pure.name in ("__init__.py", "__main__.py"):
        return False
    if "migrations" in pure.parts:
        return False

    # Exclude files that are themselves tests
    if is_matching_pattern(normalized, test_patterns):
        return False

    # Must reside under one of the source paths
    for sp in source_paths:
        clean_sp = sp.strip().replace("\\", "/").rstrip("/") + "/"
        if normalized.startswith(clean_sp) or normalized.startswith(clean_sp.lstrip("/")):
            return True

    return False


def detect_missing_tests(
    changed_files: Iterable[str],
    config: ReviewBotConfig,
) -> list[str]:
    """Identify changed source files that do not have a matching test file in the PR.

    Heuristic:
    - Identifies changed source files under config.source_paths.
    - Identifies changed test files matching config.test_patterns.
    - A source file is considered tested if any changed test file contains its stem
      (e.g., `service.py` -> `test_service.py` or `service_test.py`).
    """
    file_list = [f.replace("\\", "/") for f in changed_files]

    # Partition into test files and candidate source files
    changed_test_files: list[str] = [
        f for f in file_list if is_matching_pattern(f, config.test_patterns)
    ]

    changed_source_files: list[str] = [
        f for f in file_list if is_source_file(f, config.source_paths, config.test_patterns)
    ]

    if not changed_source_files:
        return []

    untested: list[str] = []

    for src in changed_source_files:
        pure_src = PurePath(src)
        stem = pure_src.stem.lower()

        # Check if any changed test file corresponds to this source file
        has_test = False
        for test_file in changed_test_files:
            test_pure = PurePath(test_file)
            test_stem = test_pure.stem.lower()
            # Match standard conventions: test_foo.py or foo_test.py
            if test_stem in (f"test_{stem}", f"{stem}_test") or stem in test_stem:
                has_test = True
                break

        if not has_test:
            untested.append(src)

    return sorted(untested)
