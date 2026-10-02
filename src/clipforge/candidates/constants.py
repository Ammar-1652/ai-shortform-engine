"""Fixed candidate-mining recipe. Thresholds live on the profile, not the CLI."""

from typing import Literal

RECIPE_NAME: Literal["candidate-mining"] = "candidate-mining"
RECIPE_VERSION: Literal["1"] = "1"
JOB_CANDIDATE = "candidate_mine"
KIND_CANDIDATE = "candidate_set_json"
TOOL_NAME = "clipforge-candidate"

# Candidate JSON, its partial file, a short log, and a little overhead.
DISK_ESTIMATE_BYTES = 8 * 1024 * 1024

EXCERPT_CHARS = 300
MID_TARGET_US = 30_000_000

# Words per spoken second. The plateau is the broad useful band.
DENSITY_LOW_ZERO = 0.5
DENSITY_LOW_FULL = 1.5
DENSITY_HIGH_FULL = 3.5
DENSITY_HIGH_ZERO = 6.0

# Scene cuts per second that saturate the edit signal. Further cuts do not add reward.
SCENE_CUTS_PER_SECOND_CAP = 0.2
