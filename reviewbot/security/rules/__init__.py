"""Built-in security rules for reviewbot."""

from reviewbot.security.rules.sec001_hardcoded_secrets import HardcodedSecretsRule
from reviewbot.security.rules.sec002_dangerous_calls import DangerousCallsRule
from reviewbot.security.rules.sec003_sql_injection import SQLInjectionRule

__all__ = [
    "HardcodedSecretsRule",
    "DangerousCallsRule",
    "SQLInjectionRule",
]
