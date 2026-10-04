"""Publish a replacement only after every boundary succeeds.

The previous current artifact stays current until the database commit and the
sidecar write both finish. A failure leaves partial files unpromoted.
"""

from __future__ import annotations

from collections.abc import Callable

from clipforge.errors import ClipforgeError


class PromotionError(ClipforgeError):
    """A promotion boundary failed. The previous current artifact stays current."""


def promote(
    *,
    write_output: Callable[[], None],
    write_manifest: Callable[[], None],
    commit_database: Callable[[], None],
    write_sidecar: Callable[[], None],
    rollback_database: Callable[[], None],
) -> None:
    """Run the promotion boundaries in order. Sidecar failure rolls the database back."""
    try:
        write_output()
    except Exception as exc:
        raise PromotionError("output failed. Partial output was not promoted.") from exc
    try:
        write_manifest()
    except Exception as exc:
        raise PromotionError("manifest publication failed. Partial output was not promoted.") from exc
    try:
        commit_database()
    except Exception as exc:
        rollback_database()
        raise PromotionError(
            "database commit failed after the manifest was written. The previous artifact stays current."
        ) from exc
    try:
        write_sidecar()
    except Exception as exc:
        rollback_database()
        raise PromotionError("sidecar publication failed. The previous current artifact was restored.") from exc
