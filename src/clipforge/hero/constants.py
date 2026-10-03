"""Hero draft recipe. It is not the rough-preview recipe."""

from typing import Literal

RECIPE_NAME: Literal["hero-draft"] = "hero-draft"
RECIPE_VERSION: Literal["1"] = "1"
JOB_HERO: Literal["hero_draft_render"] = "hero_draft_render"
KIND_HERO: Literal["hero_draft_set_json"] = "hero_draft_set_json"
TOOL_NAME = "clipforge-hero"
COMPOSITION_ID = "HeroDraft"
MOTION_LIBRARY_VERSION: Literal["motion-library-v1"] = "motion-library-v1"
CAPTION_ALGORITHM: Literal["hero-caption-v1"] = "hero-caption-v1"

OUTPUT_FPS_NUMERATOR = 30
OUTPUT_FPS_DENOMINATOR = 1
OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920
DURATION_TOLERANCE_US = 100_000
DISK_ESTIMATE_BYTES = 96 * 1024 * 1024
FAKE_MODEL_NAME = "fake-forced-align-v1"
FAKE_WHISPERX_VERSION = "test-double"
