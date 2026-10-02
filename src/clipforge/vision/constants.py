"""Fixed visual-analysis recipe. Thresholds stay in the profile, not on the CLI."""

RECIPE_NAME = "visual-analysis"
RECIPE_VERSION = "1"
JOB_VISUAL = "visual_analyze"
KIND_VISUAL = "visual_analysis_json"

SCENE_DETECTOR = "AdaptiveDetector"
SCENE_BACKEND = "pyav"
SCENE_ENDPOINT_TOLERANCE_US = 100_000

ADAPTIVE_THRESHOLD = 3.0
MIN_CONTENT_VAL = 15.0
WINDOW_WIDTH = 2
MIN_SCENE_LEN_FRAMES = 1

REPRESENTATIVE_FRACTIONS = ("1/5", "1/2", "4/5")
SHORT_SCENE_US = 1_000_000
FACE_SAMPLE_INTERVAL_US = 500_000
JPEG_QUALITY = 85
JPEG_LONG_EDGE = 640
CONTACT_COLUMNS = 4
CONTACT_ROWS = 5
DIFFERENCE_EDGE = 64
METRICS_VERSION = "1"

MIN_DETECTION_CONFIDENCE = 0.5
MIN_SUPPRESSION_THRESHOLD = 0.3
PIXEL_CLAMP = 2

TRACKING_ALGORITHM = "greedy-iou-v1"
TRACKING_IOU_THRESHOLD = 0.3
TRACKING_CENTER_DISTANCE = 0.2
TRACKING_MAX_GAP_US = 1_000_000

FACE_MODEL_FILENAME = "blaze_face_short_range.tflite"
FACE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_detector/"
    "blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
)
FACE_ENGINE = "mediapipe-tasks-face-detector"


def recipe_id() -> str:
    return f"{RECIPE_NAME}-v{RECIPE_VERSION}"
