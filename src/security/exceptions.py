"""Security exceptions for the frontline and voice subsystems."""

from __future__ import annotations


class SecurityException(Exception):
    """Base exception for all security/invariant failures."""


class DuplicateTurnException(SecurityException):
    """Raised when a duplicate turn sequence or payload hash is detected."""


class WebhookValidationException(SecurityException):
    """Raised when telephony or carrier webhook fails signature validation."""
