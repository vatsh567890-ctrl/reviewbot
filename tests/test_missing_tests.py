"""Unit tests for missing tests heuristic detector."""

from reviewbot.config import ReviewBotConfig
from reviewbot.missing_tests.detector import detect_missing_tests


def test_missing_tests_detected():
    config = ReviewBotConfig(
        source_paths=["src/"],
        test_patterns=["tests/**/test_*.py", "tests/**/*_test.py"],
    )
    changed = [
        "src/core/auth.py",
        "README.md",
    ]
    untested = detect_missing_tests(changed, config)
    assert untested == ["src/core/auth.py"]


def test_missing_tests_covered_by_test_file():
    config = ReviewBotConfig(
        source_paths=["src/"],
        test_patterns=["tests/**/test_*.py", "tests/**/*_test.py"],
    )
    changed = [
        "src/core/auth.py",
        "tests/core/test_auth.py",
    ]
    untested = detect_missing_tests(changed, config)
    assert untested == []


def test_missing_tests_ignores_non_source_and_init():
    config = ReviewBotConfig(
        source_paths=["src/"],
        test_patterns=["tests/**/test_*.py"],
    )
    changed = [
        "src/__init__.py",
        "src/migrations/0001_initial.py",
        "docs/index.md",
        "pyproject.toml",
    ]
    untested = detect_missing_tests(changed, config)
    assert untested == []


def test_missing_tests_custom_package_path():
    config = ReviewBotConfig(
        source_paths=["reviewbot/"],
        test_patterns=["tests/**/test_*.py"],
    )
    changed = [
        "reviewbot/reviewer.py",
    ]
    untested = detect_missing_tests(changed, config)
    assert untested == ["reviewbot/reviewer.py"]

    # When test is included
    changed_with_test = [
        "reviewbot/reviewer.py",
        "tests/test_reviewer.py",
    ]
    assert detect_missing_tests(changed_with_test, config) == []
