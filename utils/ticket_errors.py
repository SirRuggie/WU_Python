"""Shared thread-ticket failures without Discord or dashboard dependencies."""


class ThreadTicketError(RuntimeError):
    """A safe, operator-actionable thread ticket failure."""


class ThreadConfigurationError(ThreadTicketError):
    """Thread parents, roles, or permissions are unsafe or incomplete."""
