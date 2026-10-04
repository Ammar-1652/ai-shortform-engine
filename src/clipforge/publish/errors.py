"""Fail-closed delivery errors. The category is safe to print."""

from __future__ import annotations

from clipforge.errors import ClipforgeError

EXTERNAL_PUBLISHING = "External platform publishing is not implemented; local delivery export is available."


class PublishError(ClipforgeError):
    """A local delivery cannot be planned, exported, or verified."""

    def __init__(self, message: str, *, category: str) -> None:
        super().__init__(message)
        self.category = category
