"""Errors raised by shop rules. MCP servers turn these into tool errors."""


class NotFound(LookupError):
    """A part, bike, supplier, or order that does not exist."""


class RuleViolation(ValueError):
    """A request that breaks a business rule."""
