"""Security rules and analysis framework for reviewbot."""

from reviewbot.security.base import SecurityRule
from reviewbot.security.registry import SecurityRegistry

__all__ = [
    "SecurityRule",
    "SecurityRegistry",
]
