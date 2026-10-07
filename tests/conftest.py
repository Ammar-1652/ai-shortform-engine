"""Use an installed external speech directory when the operator has one.

The production code still refuses ``verified_live`` unless that directory is
set and the WAV bytes match the catalog. This does not invent audio.
"""

from __future__ import annotations

import os
from pathlib import Path


def pytest_configure(config: object) -> None:
    del config
    if os.environ.get("CLIPFORGE_SPEECH_EVIDENCE_ROOT", "").strip():
        return
    root = Path.home() / ".local" / "clipforge-speech-evidence"
    if root.is_dir() and not root.is_symlink():
        os.environ["CLIPFORGE_SPEECH_EVIDENCE_ROOT"] = str(root)
