"""Custom exceptions for OLGA Automation."""


class OlgaAutomationError(Exception):
    """Base exception for all olga-automation errors."""


class OpiParseError(OlgaAutomationError):
    """Failed to parse .opi XML file."""


class KeywordNotFoundError(OlgaAutomationError):
    """Requested keyword tag not found in .opi file."""


class OlgaExecutionError(OlgaAutomationError):
    """OLGA simulation execution failed."""


class LicenseError(OlgaExecutionError):
    """FlexLM license issue detected."""


class OutputParseError(OlgaAutomationError):
    """Failed to parse OLGA output file (.tpl, .ppl, .out)."""
