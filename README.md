# Automated Code Review Bot 🤖

A production-grade, containerized GitHub Action that analyzes Pull Requests in real time, inspecting **only the lines added or changed in the unified diff**. It posts review comments for code style and lint issues, missing test coverage, and common security anti-patterns.

Designed to be safe, performant, non-blocking by default, and easy for any repository to adopt.

---

## ✨ Features

- **Diff-Aware Line Matching**: Parses unified diffs to identify exact newly added lines (`side: RIGHT`). Never comments on unchanged, deleted, or binary lines.
- **Python Style & Linting via Ruff**: Subprocess-driven analysis using [Ruff](https://docs.astral.sh/ruff/), mapping findings to added lines with rule documentation links.
- **Pluggable Security Rule Set**:
  - `SEC001`: Hardcoded secrets (AWS Access Keys, generic API keys/passwords with **automatic value redaction**, and private keys).
  - `SEC002`: Dangerous function invocations (`eval`, `exec`, `subprocess(shell=True)`, `yaml.load` without `SafeLoader`, `verify=False`, and `pickle.loads`).
  - `SEC003`: SQL built with string formatting (f-strings, `%`, `+` concatenation, `.format()`).
- **Heuristic Missing Tests Check**: Flags modified source files that lack corresponding test updates in the PR diff via a top-level review summary notice.
- **Duplicate Prevention & Fingerprinting**: Comment bodies include hidden cryptographic fingerprints (`<!-- reviewbot-fingerprint:... -->`), preventing repetitive comments on PR synchronizations and new commits.
- **Configurable Capping & Prioritization**: Caps inline comments per run (default: 30) while prioritizing errors over warnings and info.
- **Production-Ready Container Action**: Packaged as a Docker container action requiring no local toolchain installation.

---

## 🚀 Quickstart & Adoption

### 1. Add Workflow File

Create `.github/workflows/review.yml` in your repository:

```yaml
name: "Automated Code Review"

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write

jobs:
  review:
    name: "Analyze PR Changes"
    runs-on: ubuntu-latest
    steps:
      - name: "Checkout repository"
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: "Run Review Bot"
        uses: ./  # Or point to release tag: owner/reviewbot-action@v1
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
          config-path: ".reviewbot.yml"
          fail-on-error: "false"
```

### 2. (Optional) Configure `.reviewbot.yml`

Create `.reviewbot.yml` in the root of your repository:

```yaml
# Severity threshold: "info", "warning", or "error"
severity_threshold: "info"

# Maximum inline comments per review run
max_comments: 30

# File patterns to exclude
ignore_paths:
  - ".git/**"
  - "node_modules/**"
  - ".venv/**"
  - "dist/**"
  - "build/**"
  - "*.min.js"

# Source directories and test patterns for missing-test checks
source_paths:
  - "src/"
  - "app/"

test_patterns:
  - "tests/**/test_*.py"
  - "tests/**/*_test.py"

# If true, requests changes on PR when error-severity findings exist
request_changes_on_error: false

# Override severity for specific rules
rule_severities:
  SEC001: "error"
  SEC002: "error"
  SEC003: "error"
```

---

## 🔒 Pull Requests from Forks & Security Considerations

### The Fork PR Problem
When a pull request originates from a fork repository, GitHub Actions runs the workflow with a **read-only** `GITHUB_TOKEN` by default and denies access to repository secrets. This prevents malicious contributors from submitting PRs that read secrets or modify the base repository.

Because `pull-requests: write` permissions are unavailable for fork PRs, reviewbot will receive an HTTP `403 Forbidden` if it attempts to post reviews directly using the standard `pull_request` event.

### The `pull_request_target` Event & Its Risks
To post comments on fork PRs, workflows can use the `pull_request_target` trigger, which runs in the context of the **base** repository and has write permissions.

> ⚠️ **CRITICAL SECURITY WARNING**:
> Never combine `pull_request_target` with an unconditional `actions/checkout` of the pull request's head branch:
> ```yaml
> # ❌ VULNERABLE TO ARBITRARY CODE EXECUTION:
> on: pull_request_target
> steps:
>   - uses: actions/checkout@v4
>     with:
>       ref: ${{ github.event.pull_request.head.sha }} # DANGER!
>   - run: npm test  # Malicious PR can execute arbitrary commands with repo secrets!
> ```
> If a workflow checks out untrusted code from a fork and executes code or build scripts, an attacker can exfiltrate your secrets or compromise your repository.

### Safe Alternative Patterns
1. **Internal Teams**: If contributions only come from internal branches within the same repository, `on: pull_request` works out of the box with `pull-requests: write`.
2. **Read-Only / CI Artifact Separation**: For public open-source repositories accepting untrusted forks, run the lint and security checks in an unprivileged `pull_request` job, save findings as an artifact, and use a separate restricted `pull_request_target` or `workflow_run` workflow to download the artifact and post the review comment.

---

## 🛡️ Built-in Security Rules

Each rule is implemented as an independent, pluggable module under `reviewbot/security/rules/`.

| Rule ID | Name | Default Severity | Description | Suggested Fix |
| :--- | :--- | :---: | :--- | :--- |
| **SEC001** | Hardcoded Secrets | `error` | Detects AWS Access Keys (`AKIA...`), private key headers, and generic password/key assignments with string literals >= 8 characters. **Values are automatically redacted in posted comments.** | Store credentials in environment variables or GitHub Secrets. |
| **SEC002** | Dangerous Calls | `error` / `warning` | Detects invocations of `eval()`, `exec()`, `subprocess` with `shell=True`, unsafe `yaml.load()`, `verify=False` in network requests, and `pickle.loads()`. | Use `ast.literal_eval`, parameter lists with `shell=False`, `yaml.safe_load`, and safe data formats (JSON). |
| **SEC003** | SQL Injection | `error` | Flags SQL statements assembled using f-strings, `%`, `+` concatenation, or `.format()`. | Use parameterized queries (e.g. `cursor.execute(sql, params)`) or an ORM. |

---

## ✍️ How to Add a New Security Rule

Adding a new security rule is modular and straightforward:

1. Create a new module in `reviewbot/security/rules/`, e.g. `reviewbot/security/rules/sec004_insecure_hashing.py`:

```python
import re
from typing import Optional
from reviewbot.models import Finding, Severity
from reviewbot.security.base import SecurityRule

MD5_SHA1_RE = re.compile(r"\bhashlib\.(md5|sha1)\s*\(")


class InsecureHashingRule(SecurityRule):
    @property
    def id(self) -> str:
        return "SEC004"

    @property
    def name(self) -> str:
        return "Insecure Cryptographic Hash"

    @property
    def description(self) -> str:
        return "Detects MD5 or SHA1 hash functions vulnerable to collision attacks."

    @property
    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check_line(
        self,
        file_path: str,
        line_number: int,
        line_content: str,
        full_content: Optional[str] = None,
    ) -> list[Finding]:
        if MD5_SHA1_RE.search(line_content):
            return [
                Finding(
                    file_path=file_path,
                    line=line_number,
                    rule_id=self.id,
                    message="MD5 and SHA-1 hashes are cryptographically broken.",
                    severity=self.default_severity,
                    suggested_fix="Use `hashlib.sha256()` or `hashlib.blake2b()` for secure hashing.",
                    normalized_snippet=line_content.strip(),
                )
            ]
        return []
```

2. Register the rule in `reviewbot/security/registry.py`:

```python
from reviewbot.security.rules.sec004_insecure_hashing import InsecureHashingRule

# In _register_defaults():
self.register(InsecureHashingRule())
```

3. Add corresponding unit tests in `tests/test_security_rules.py`.

---

## 🧪 Missing Tests Check: Heuristic & Limitations

### How It Works
When a pull request introduces or changes files in `source_paths` (default `src/`), the bot inspects the PR diff for test files matching `test_patterns` (e.g. `tests/test_*.py`). It maps source files to test files using module stems (e.g., `src/auth/service.py` looks for `test_service.py` or `service_test.py`).

If source files lack corresponding test files, reviewbot includes a **Missing Tests Warning** section in the pull request review body (without cluttering the code diff with inline comments).

### Limitations
- **Heuristic matching**: Relies on standard naming conventions (`test_<module>.py` or `<module>_test.py`). If tests are structured in consolidated or end-to-end suites, the bot might flag a file.
- **Diff-only context**: The check analyzes files present in the current PR diff. It does not execute tests or calculate runtime line/branch coverage (tools like Codecov or Coveralls remain complementary for runtime coverage).
- **Refactoring changes**: Pure refactoring or comments in source files may trigger the notice if no test file was modified in the same PR.

Repositories can customize `source_paths` and `test_patterns` in `.reviewbot.yml` to fit their project structure.

---

## 🔌 Linter Layer Architecture & Multi-Language Support

The linter architecture is built around the `BaseLinter` abstract class defined in `reviewbot/linters/base.py`:

```python
class BaseLinter(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def can_handle(self, file_path: str) -> bool: ...

    @abstractmethod
    def lint(
        self,
        file_path: str,
        added_lines: set[int],
        content: Optional[str] = None,
        config: Optional[ReviewBotConfig] = None,
    ) -> list[Finding]: ...
```

### Built-in Linters
1. **Ruff** (`reviewbot/linters/ruff.py`):
   - Analyzes Python files (`.py`, `.pyi`).
   - Runs `ruff check --output-format json` via subprocess.
   - Filters findings strictly to added/changed lines in the PR diff.
2. **ESLint** (`reviewbot/linters/eslint.py`):
   - Analyzes JavaScript and TypeScript files (`.js`, `.jsx`, `.ts`, `.tsx`, `.mjs`, `.cjs`, `.mts`, `.cts`).
   - Executes `eslint` via subprocess with JSON output formatting.
   - Installed with Node.js in the Docker action image for out-of-the-box JS/TS linting.
   - Filters findings strictly to added/changed lines in the PR diff.

### Adding Custom Linters
To support additional linters (e.g., ShellCheck, GolangCI-Lint):
1. Subclass `BaseLinter` in `reviewbot/linters/`.
2. Implement `can_handle()` to match relevant file extensions.
3. In `lint()`, execute the linter with JSON output via `subprocess.run()`, map findings to standard `Finding` objects, and filter against `added_lines`.
4. Register the new linter in `reviewbot/linters/__init__.py`.

---

## ⚙️ Configuration Reference (`.reviewbot.yml`)

| Setting | Type | Default | Description |
| :--- | :---: | :---: | :--- |
| `enabled_rules` | `list[str]` | `null` | Explicit list of rule IDs to enable. If `null`, all non-disabled rules run. |
| `disabled_rules` | `list[str]` | `[]` | List of rule IDs to suppress. |
| `severity_threshold` | `string` | `"info"` | Minimum severity to report (`"info"`, `"warning"`, `"error"`). |
| `max_comments` | `int` | `30` | Maximum number of inline comments posted in a single PR review. |
| `ignore_paths` | `list[str]` | Standard ignore globs | Glob patterns for files to exclude from analysis. |
| `source_paths` | `list[str]` | `["src/", "app/"]` | Root directories for application source code. |
| `test_patterns` | `list[str]` | `["tests/**/test_*.py", ...]` | Glob patterns for identifying test files. |
| `request_changes_on_error` | `bool` | `false` | If true, submits review with `REQUEST_CHANGES` when errors are present. |
| `rule_severities` | `dict[str, str]` | `{}` | Per-rule severity overrides (e.g. `F401: "warning"`). |

---

## 🛠️ CLI Options & Flags

| Option | Flag | Description |
| :--- | :--- | :--- |
| Config Path | `--config-path <path>` | Path to `.reviewbot.yml` (default: `.reviewbot.yml`). |
| PR Number | `--pr <number>` | Pull request number (resolved automatically in GitHub Actions). |
| Repository | `--repo <owner/repo>` | Target repository (resolved automatically in GitHub Actions). |
| Head SHA | `--head-sha <sha>` | Head commit SHA of the PR branch. |
| Token | `--token <token>` | GitHub token for REST API access. |
| Fail on Error | `--fail-on-error` | Exit with status 1 if any error-level finding is detected (non-blocking by default). |
| **Dry Run Mode** | `--dry-run` | **Preview mode**: outputs the exact review JSON payload to stdout without posting to GitHub. |
| **LLM Review** | `--llm-review` | Sends diff hunks to LLM endpoint for architectural insights (requires `REVIEWBOT_LLM_API_KEY`). |
| Verbose | `-v`, `--verbose` | Enables detailed debug logging. |

---

## 🛠️ Local Development & Testing

```bash
# 1. Set up Python virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 2. Install dependencies in editable mode
pip install -e ".[dev]"

# 3. Format & Lint with Ruff
ruff check .
ruff format --check .

# 4. Strict Type Checking with Mypy
mypy --strict reviewbot

# 5. Run full test suite with coverage report (100% mocked, 0 real GitHub calls)
pytest -v --cov=reviewbot --cov-report=term-missing
```

---

## 📄 License

Apache-2.0.
