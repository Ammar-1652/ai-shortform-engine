"""Focused Round 4 fail-closed hardening tests."""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from clipforge.errors import MediaError
from clipforge.vision import face_backend
from clipforge.vision import models as vision_models
from clipforge.vision.constants import FACE_MODEL_FILENAME

pytestmark = pytest.mark.vision


def test_missing_face_confidence_is_not_invented() -> None:
    assert face_backend._category_score(SimpleNamespace(categories=[])) is None
    assert face_backend._category_score(SimpleNamespace(categories=[SimpleNamespace(score=None)])) is None
    assert face_backend._category_score(SimpleNamespace(categories=[SimpleNamespace(score=True)])) is None
    assert face_backend._category_score(SimpleNamespace(categories=[SimpleNamespace(score=0.75)])) == 0.75


def test_face_model_download_refuses_symlinked_partial_before_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "models"
    directory.mkdir()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    partial = directory / f"{FACE_MODEL_FILENAME}.partial.download"
    partial.symlink_to(outside)

    def no_network(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("network should not be reached for an unsafe partial path")

    monkeypatch.setattr(vision_models.urllib.request, "urlopen", no_network)
    with pytest.raises(MediaError, match="partial"):
        vision_models._download("https://example.invalid/model", directory, expected_bytes=5)
    assert outside.read_bytes() == b"outside"
    assert not (directory / FACE_MODEL_FILENAME).exists()


def test_face_model_manifest_partial_symlink_cannot_redirect_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "models"
    directory.mkdir()
    outside = tmp_path / "outside-manifest.json"
    outside.write_bytes(b"outside-manifest")
    (directory / "manifest.json.partial").symlink_to(outside)

    class Response(io.BytesIO):
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            self.close()

    monkeypatch.setattr(
        vision_models.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(b"model"),
    )

    with pytest.raises(MediaError, match="manifest was not published safely"):
        vision_models._download("https://example.invalid/model", directory, expected_bytes=5)

    assert outside.read_bytes() == b"outside-manifest"
    assert not (directory / FACE_MODEL_FILENAME).exists()
