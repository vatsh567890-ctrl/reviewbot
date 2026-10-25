"""Unit tests for pluggable security rules SEC001, SEC002, SEC003 and registry."""

from reviewbot.config import ReviewBotConfig
from reviewbot.models import Finding, Severity
from reviewbot.security.base import SecurityRule
from reviewbot.security.registry import SecurityRegistry
from reviewbot.security.rules import (
    DangerousCallsRule,
    HardcodedSecretsRule,
    SQLInjectionRule,
)


def test_sec001_aws_key_detection_and_redaction():
    rule = HardcodedSecretsRule()
    line = '    aws_key = "AKIA1234567890EXAMPL"'
    findings = rule.check_line("src/auth.py", 10, line)

    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "SEC001"
    assert f.severity == Severity.ERROR
    # Verify the secret is NOT exposed in the snippet or message
    assert "AKIA1234567890EXAMPL" not in f.normalized_snippet
    assert "AKIA****************" in f.normalized_snippet


def test_sec001_generic_secret_assignment_redaction():
    rule = HardcodedSecretsRule()
    line = 'api_key = "sk_live_abcdef123456789"'
    findings = rule.check_line("src/config.py", 5, line)

    assert len(findings) == 1
    assert "sk_live_abcdef123456789" not in findings[0].normalized_snippet
    assert "********" in findings[0].normalized_snippet


def test_sec001_private_key_header():
    rule = HardcodedSecretsRule()
    line = "-----BEGIN RSA PRIVATE KEY-----"
    findings = rule.check_line("certs/server.pem", 1, line)

    assert len(findings) == 1
    assert findings[0].rule_id == "SEC001"


def test_sec001_benign_placeholders_not_flagged():
    rule = HardcodedSecretsRule()
    lines = [
        'password = "password"',
        'api_key = "dummy"',
        'secret = "placeholder"',
        'token = "your_secret_here"',
    ]
    for line in lines:
        findings = rule.check_line("tests/test_dummy.py", 1, line)
        assert len(findings) == 0


def test_sec002_dangerous_calls():
    rule = DangerousCallsRule()

    # eval
    f_eval = rule.check_line("src/eval.py", 2, 'result = eval("1 + 1")')
    assert len(f_eval) == 1
    assert f_eval[0].rule_id == "SEC002"
    assert f_eval[0].severity == Severity.ERROR

    # exec
    f_exec = rule.check_line("src/dyn.py", 3, "exec(user_code)")
    assert len(f_exec) == 1

    # subprocess with shell=True
    f_shell = rule.check_line("src/cmd.py", 4, "subprocess.run(cmd, shell=True)")
    assert len(f_shell) == 1

    # yaml.load without SafeLoader
    f_yaml = rule.check_line("src/parser.py", 5, "data = yaml.load(stream)")
    assert len(f_yaml) == 1

    # yaml.load with SafeLoader is safe
    f_yaml_safe = rule.check_line(
        "src/parser.py", 6, "data = yaml.load(stream, Loader=yaml.SafeLoader)"
    )
    assert len(f_yaml_safe) == 0

    # verify=False
    f_verify = rule.check_line("src/net.py", 7, 'requests.get("https://example.com", verify=False)')
    assert len(f_verify) == 1
    assert f_verify[0].severity == Severity.WARNING

    # pickle.loads
    f_pickle = rule.check_line("src/cache.py", 8, "obj = pickle.loads(raw_data)")
    assert len(f_pickle) == 1

    # Comments are ignored
    f_comment = rule.check_line("src/cache.py", 9, '# eval("do not flag me")')
    assert len(f_comment) == 0


def test_sec003_sql_injection():
    rule = SQLInjectionRule()

    # f-string SQL
    f_fstring = rule.check_line(
        "src/repo.py", 10, 'query = f"SELECT * FROM users WHERE id = {uid}"'
    )
    assert len(f_fstring) == 1
    assert f_fstring[0].rule_id == "SEC003"
    assert f_fstring[0].severity == Severity.ERROR

    # % formatting SQL
    f_percent = rule.check_line(
        "src/repo.py", 11, "query = \"DELETE FROM items WHERE code = '%s'\" % code"
    )
    assert len(f_percent) == 1

    # + concatenation SQL
    f_concat = rule.check_line(
        "src/repo.py", 12, 'query = "SELECT name FROM accounts WHERE id = " + str(acc_id)'
    )
    assert len(f_concat) == 1

    # .format() SQL
    f_format = rule.check_line(
        "src/repo.py", 13, "\"UPDATE records SET status = '{}'\".format(status)"
    )
    assert len(f_format) == 1

    # Safe parameterized query not flagged
    f_safe = rule.check_line(
        "src/repo.py", 14, 'cursor.execute("SELECT * FROM users WHERE id = %s", (uid,))'
    )
    assert len(f_safe) == 0


def test_security_registry_run_checks_only_on_added_lines():
    registry = SecurityRegistry()
    content = """line 1: import os
line 2: api_key = "AKIA1234567890EXAMPLE"
line 3: safe_line = 42
line 4: eval("bad()")
"""
    # Only line 2 and 3 are added in diff (line 4 is untouched old code)
    added_lines = {2, 3}
    config = ReviewBotConfig()

    findings = registry.run_checks("src/test.py", added_lines, content, config)

    # Line 2 (AWS key) should be flagged, but line 4 (eval) should NOT be flagged because it's not in added_lines!
    assert len(findings) == 1
    assert findings[0].line == 2
    assert findings[0].rule_id == "SEC001"


def test_custom_security_rule_registration():
    class CustomRule(SecurityRule):
        @property
        def id(self) -> str:
            return "SEC999"

        @property
        def name(self) -> str:
            return "Custom Test Rule"

        @property
        def description(self) -> str:
            return "Flags TODO comments"

        def check_line(self, file_path, line_number, line_content, full_content=None):
            if "TODO" in line_content:
                return [
                    Finding(
                        file_path=file_path,
                        line=line_number,
                        rule_id=self.id,
                        message="TODO found",
                        severity=Severity.INFO,
                    )
                ]
            return []

    registry = SecurityRegistry()
    registry.register(CustomRule())
    assert registry.get_rule("SEC999") is not None

    findings = registry.run_checks(
        "src/todo.py",
        {1},
        "# TODO: finish this",
        ReviewBotConfig(),
    )
    assert len(findings) == 1
    assert findings[0].rule_id == "SEC999"
