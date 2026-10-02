"""Versioned derivative recipes. The version is part of cache identity. The clock is not."""

ANALYSIS_PROXY_NAME = "analysis-proxy"
ANALYSIS_PROXY_VERSION = "1"
ASR_AUDIO_NAME = "asr-audio"
ASR_AUDIO_VERSION = "1"
PROXY_CRF = "28"
PROXY_PRESET = "veryfast"
PROXY_AUDIO_BITRATE = "96k"

KIND_PROBE = "ffprobe_json"
KIND_PROXY = "analysis_proxy"
KIND_ASR = "asr_audio"
JOB_MEDIA_PREPARE = "media_prepare"


def recipe_id(name: str, version: str) -> str:
    return f"{name}-v{version}"
