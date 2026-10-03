"""Fixed rough-preview recipe. Output-changing numbers live on the profile."""

from typing import Literal

RECIPE_NAME: Literal["rough-preview"] = "rough-preview"
RECIPE_VERSION: Literal["1"] = "1"
JOB_PREVIEW: Literal["rough_preview_render"] = "rough_preview_render"
KIND_PREVIEW: Literal["rough_preview_set_json"] = "rough_preview_set_json"
TOOL_NAME = "clipforge-preview"
COMPOSITION_ID = "RoughPreview"

OUTPUT_FPS_NUMERATOR = 30
OUTPUT_FPS_DENOMINATOR = 1
OUTPUT_WIDTH = 720
OUTPUT_HEIGHT = 1280

# max(100 ms, two 30 fps frame periods). Two frames are 66_666 us, so 100 ms wins.
DURATION_TOLERANCE_US = 100_000

DISK_ESTIMATE_BYTES = 64 * 1024 * 1024
