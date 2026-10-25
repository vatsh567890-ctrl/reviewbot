"""SEC003: Detection of SQL queries constructed via string formatting or concatenation."""

from __future__ import annotations

import re
from typing import Optional

from reviewbot.models import Finding, Severity
from reviewbot.security.base import SecurityRule

SQL_KEYWORDS = r"(?:SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|DROP\s+TABLE|ALTER\s+TABLE)"

# 1. f-strings containing SQL commands and interpolated variables: f"... SELECT ... {var} ..."
FSTRING_SQL_RE = re.compile(
    rf"""\bf[fFrRuUbB]*["'].*?\b{SQL_KEYWORDS}\b.*?\{{[^}}]+\}}""",
    re.IGNORECASE,
)

# 2. String formatting via %: "... SELECT ..." % (var,)
PERCENT_SQL_RE = re.compile(
    rf"""["'].*?\b{SQL_KEYWORDS}\b.*?["']\s*%\s*""",
    re.IGNORECASE,
)

# 3. String concatenation via +: "... SELECT ..." + var or var + "... WHERE ..."
CONCAT_SQL_RE = re.compile(
    rf"""(?:["'].*?\b{SQL_KEYWORDS}\b.*?["']\s*\+\s*|\+\s*["'].*?\b(?:WHERE|FROM|VALUES|SET)\b.*?["'])""",
    re.IGNORECASE,
)

# 4. .format() method on SQL string: "... SELECT ... {}".format(...)
FORMAT_SQL_RE = re.compile(
    rf"""["'].*?\b{SQL_KEYWORDS}\b.*?["']\.format\s*\(""",
    re.IGNORECASE,
)


class SQLInjectionRule(SecurityRule):
    """Detects SQL queries built with unsafe string formatting or concatenation."""

    @property
    def id(self) -> str:
        return "SEC003"

    @property
    def name(self) -> str:
        return "SQL Injection via String Formatting"

    @property
    def description(self) -> str:
        return "Detects SQL queries assembled using f-strings, %, +, or .format() instead of parameterized queries."

    @property
    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check_line(
        self,
        file_path: str,
        line_number: int,
        line_content: str,
        full_content: Optional[str] = None,
    ) -> list[Finding]:
        findings: list[Finding] = []
        stripped = line_content.strip()

        # Skip comment lines
        if stripped.startswith("#") or stripped.startswith("//"):
            return []

        matched = False
        technique = ""

        if FSTRING_SQL_RE.search(line_content):
            matched = True
            technique = "an f-string"
        elif PERCENT_SQL_RE.search(line_content):
            matched = True
            technique = "% formatting"
        elif CONCAT_SQL_RE.search(line_content):
            matched = True
            technique = "string concatenation (+)"
        elif FORMAT_SQL_RE.search(line_content):
            matched = True
            technique = "the .format() method"

        if matched:
            findings.append(
                Finding(
                    file_path=file_path,
                    line=line_number,
                    rule_id=self.id,
                    message=f"Possible SQL injection: SQL query dynamically constructed using {technique}.",
                    severity=self.default_severity,
                    suggested_fix="Use parameterized queries with database placeholders (e.g. `cursor.execute('SELECT ... WHERE id = %s', (user_id,))`) or an ORM.",
                    normalized_snippet=stripped,
                )
            )

        return findings
