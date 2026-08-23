# Trimmed from supervisely/backend/app/config.py (private repo) - keep constant VALUES in sync
# manually. Dropped WORKSPACE_ROOT (no disk-backed workspace here) and TRAIN_MEMORY_FRACTION
# (no training in the portable app).

DEFAULT_TILE_SIZE = 640
DEFAULT_OVERLAP_PCT = 15
DEFAULT_PADDING_MODE = "shift"
DEFAULT_PROPORTION_PCT = 30

THUMBNAIL_SIZE = 200
THUMBNAIL_QUALITY = 80

TILE_JPEG_QUALITY = 100

MANIFEST_SCHEMA_VERSION = 3
ANNOTATION_SCHEMA_VERSION = 1
