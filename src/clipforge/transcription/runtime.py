"""Choose a device and compute type from what CTranslate2 can actually run.

``nvidia-smi`` and ``nvcc`` are not evidence. Explicit CUDA never falls back
to CPU. AUTO uses CUDA only when CTranslate2 reports a device and a supported
compute type.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from clipforge.errors import MediaError

DeviceName = Literal["cpu", "cuda"]

_CPU_PREFERENCE = ("int8", "int8_float32", "float32")
_CUDA_PREFERENCE = ("int8_float16", "float16", "int8", "float32")


@dataclass(frozen=True, slots=True)
class RuntimeFacts:
    cuda_device_count: int
    cpu_compute_types: tuple[str, ...]
    cuda_compute_types: tuple[str, ...]
    cuda_error: str | None

    @property
    def cuda_usable(self) -> bool:
        return self.cuda_device_count > 0 and bool(self.cuda_compute_types) and self.cuda_error is None


@dataclass(frozen=True, slots=True)
class ResolvedRuntime:
    requested_device: str
    device: DeviceName
    compute_type: str
    warning: str | None


def probe_runtime() -> RuntimeFacts:
    """Ask CTranslate2. Importing it does not load a Whisper model."""
    try:
        import ctranslate2
    except ImportError as exc:
        raise MediaError(
            "CTranslate2 is not installed. Install project dependencies with uv sync. "
            "A model was not downloaded."
        ) from exc
    cuda_error: str | None = None
    cuda_count = 0
    try:
        cuda_count = int(ctranslate2.get_cuda_device_count())
    except Exception as exc:
        cuda_error = f"{exc.__class__.__name__}: {exc}"
        cuda_count = 0
    try:
        cpu_types = tuple(str(item) for item in ctranslate2.get_supported_compute_types("cpu"))
    except Exception as exc:
        raise MediaError(f"CTranslate2 could not report CPU compute types: {exc}") from exc
    cuda_types: tuple[str, ...] = ()
    if cuda_count > 0 and cuda_error is None:
        try:
            cuda_types = tuple(str(item) for item in ctranslate2.get_supported_compute_types("cuda"))
        except Exception as exc:
            cuda_error = f"{exc.__class__.__name__}: {exc}"
            cuda_types = ()
    if cuda_count > 0 and cuda_error is None:
        missing = _missing_cuda_libraries()
        if missing:
            cuda_error = (
                "CTranslate2 lists CUDA devices, but these libraries did not load: "
                + ", ".join(missing)
                + ". CUDA toolkit 13 does not provide the CUDA 12 cuBLAS and cuDNN 9 libraries "
                "this CTranslate2 build expects."
            )
            cuda_types = ()
    return RuntimeFacts(
        cuda_device_count=cuda_count,
        cpu_compute_types=cpu_types,
        cuda_compute_types=cuda_types,
        cuda_error=cuda_error,
    )


def _missing_cuda_libraries() -> tuple[str, ...]:
    """Return CUDA 12 libraries CTranslate2 needs and this process cannot load."""
    import ctypes

    missing: list[str] = []
    for name in ("libcublas.so.12", "libcudnn.so.9"):
        try:
            ctypes.CDLL(name)
        except OSError:
            missing.append(name)
    return tuple(missing)


def resolve_runtime(
    *,
    requested_device: str,
    requested_compute_type: str,
    facts: RuntimeFacts | None = None,
) -> ResolvedRuntime:
    known = facts if facts is not None else probe_runtime()
    warning: str | None = None
    device: DeviceName
    if requested_device == "cpu":
        device = "cpu"
    elif requested_device == "cuda":
        if not known.cuda_usable:
            reason = known.cuda_error or (
                f"CTranslate2 reports {known.cuda_device_count} CUDA device(s) and "
                f"compute types {list(known.cuda_compute_types) or 'none'}"
            )
            raise MediaError(
                "CUDA was requested but CTranslate2 cannot use CUDA "
                f"({reason}). Clipforge did not fall back to CPU. "
                "Re-run with --device cpu, or --device auto to allow CPU when CUDA is unavailable."
            )
        device = "cuda"
    elif requested_device == "auto":
        if known.cuda_usable:
            device = "cuda"
        else:
            device = "cpu"
            reason = known.cuda_error or (
                f"CUDA device count is {known.cuda_device_count} and supported CUDA compute types "
                f"are {list(known.cuda_compute_types) or 'none'}"
            )
            warning = f"CUDA was not selected because {reason.rstrip('.')}. CPU will be used."
    else:
        raise MediaError("device must be auto, cpu, or cuda")
    supported = known.cpu_compute_types if device == "cpu" else known.cuda_compute_types
    compute_type = _select_compute_type(requested_compute_type, supported, device)
    return ResolvedRuntime(
        requested_device=requested_device,
        device=device,
        compute_type=compute_type,
        warning=warning,
    )


def _select_compute_type(requested: str, supported: tuple[str, ...], device: str) -> str:
    if not supported:
        raise MediaError(f"CTranslate2 reported no compute types for {device}")
    if requested != "auto":
        if requested not in supported:
            raise MediaError(
                f"compute type {requested} is not supported on {device}. "
                f"CTranslate2 reported {list(supported)}. "
                "Clipforge did not substitute a different type."
            )
        return requested
    preference = _CPU_PREFERENCE if device == "cpu" else _CUDA_PREFERENCE
    for candidate in preference:
        if candidate in supported:
            return candidate
    return supported[0]
