"""Fixed first-pass recipe. VAD is off so the ASR clock stays audible and aligned."""

RECIPE_NAME = "transcription"
RECIPE_VERSION = "1"
JOB_TRANSCRIBE = "transcribe"
KIND_TRANSCRIPT = "transcript_json"
DEFAULT_MODEL = "small.en"
DEFAULT_LANGUAGE = "en"
TASK = "transcribe"
BEAM_SIZE = 5
TEMPERATURE = 0.0
# Whisper frame hop is 20 ms. 100 ms covers a few frames of end-of-file overshoot.
TIMING_TOLERANCE_US = 100_000
ENGLISH_ONLY_SUFFIX = ".en"


def recipe_id() -> str:
    return f"{RECIPE_NAME}-v{RECIPE_VERSION}"
