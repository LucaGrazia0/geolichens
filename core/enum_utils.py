"""Decode both legacy SIP integer enums and Python/Qt 6 scoped enums."""


def enum_value(value):
    """Return the numeric value without requiring Enum to implement __int__."""
    return int(getattr(value, 'value', value))
