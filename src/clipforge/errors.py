"""Actionable errors. Callers must surface these. They must not be swallowed."""


class ClipforgeError(Exception):
    """Base error. The message says what failed and how to fix it."""


class TimelineError(ClipforgeError):
    """A time-map or frame-rate value cannot be used."""


class InvalidTimeMapError(TimelineError):
    """The mapping definition itself is illegal."""


class TimeNotMappedError(TimelineError):
    """A lookup asked for a time that this map does not contain."""


class AmbiguousTimeError(TimelineError):
    """A lookup has more than one legal answer. Construction should prevent this."""


class InvalidFrameRateError(TimelineError):
    """The frame rate is missing, non-rational, or outside the supported range."""


class FrameOutOfRangeError(TimelineError):
    """The requested frame does not start inside the output timeline."""


class StorageError(ClipforgeError):
    """SQLite rejected an operation or the database is not usable."""


class SchemaExportError(ClipforgeError):
    """JSON Schema files are missing or do not match the Pydantic models."""


class MediaError(ClipforgeError):
    """A local media operation failed. The message says what to fix."""


class ComplianceGateError(ClipforgeError):
    """Rights or campaign compliance blocked the operation. A score cannot override this."""
