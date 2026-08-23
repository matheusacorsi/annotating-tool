# Ported verbatim from supervisely/backend/app/ingestion/image_sources.py (private repo).
# This is a separate repo (yolo-obb-portable) - no shared package - keep in sync manually.
#
# Decision A (see plan): the portable app deliberately does NOT install `rasterio` in
# requirements.txt, so RasterioImageSource never actually gets used (_HAS_RASTERIO stays
# False and open_image_source() always falls through to PillowImageSource) - the existing
# try/except below already handles this gracefully with zero code changes needed. Kept
# verbatim rather than stripped so re-adding orthomosaic support later is a one-line
# requirements.txt change, not a re-port.

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None  # drone orthomosaics legitimately exceed PIL's decompression-bomb heuristic

# Rasterio pulls in GDAL; only large TIFFs need windowed reads, so keep it optional/lazy.
try:
    import rasterio
    from rasterio.windows import Window

    _HAS_RASTERIO = True
except ImportError:  # pragma: no cover - exercised only when rasterio isn't installed
    _HAS_RASTERIO = False

# Files at/above this size get windowed (rasterio) reads instead of a full in-memory PIL load,
# regardless of whether they're geo-referenced - the point is avoiding a multi-GB decode, not GIS support.
LARGE_FILE_THRESHOLD_BYTES = 200 * 1024 * 1024


class ImageSource(Protocol):
    def dimensions(self) -> tuple[int, int]: ...  # (width, height)

    def read_raw(self, x: int, y: int, w: int, h: int) -> np.ndarray:
        """Read an in-bounds region as an (h, w, 3) uint8 RGB array. Caller guarantees the
        region lies fully within [0, width) x [0, height) - no padding/clamping here."""
        ...

    def close(self) -> None: ...


class PillowImageSource:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._image = Image.open(path)
        self._image.load()

    def dimensions(self) -> tuple[int, int]:
        return self._image.width, self._image.height

    def read_raw(self, x: int, y: int, w: int, h: int) -> np.ndarray:
        region = self._image.crop((x, y, x + w, y + h)).convert("RGB")
        return np.asarray(region, dtype=np.uint8)

    def close(self) -> None:
        self._image.close()


class RasterioImageSource:
    def __init__(self, path: Path) -> None:
        if not _HAS_RASTERIO:
            raise RuntimeError("rasterio is required to read this file but is not installed")
        self._dataset = rasterio.open(path)

    def dimensions(self) -> tuple[int, int]:
        return self._dataset.width, self._dataset.height

    def read_raw(self, x: int, y: int, w: int, h: int) -> np.ndarray:
        window = Window(x, y, w, h)
        band_count = min(self._dataset.count, 3)
        data = self._dataset.read(indexes=list(range(1, band_count + 1)), window=window)
        chw_to_hwc = np.transpose(data, (1, 2, 0))
        if chw_to_hwc.shape[2] == 1:
            chw_to_hwc = np.repeat(chw_to_hwc, 3, axis=2)
        return np.ascontiguousarray(chw_to_hwc, dtype=np.uint8)

    def close(self) -> None:
        self._dataset.close()


def open_image_source(path: Path) -> ImageSource:
    suffix = path.suffix.lower()
    is_tiff = suffix in (".tif", ".tiff")
    if is_tiff and _HAS_RASTERIO and path.stat().st_size >= LARGE_FILE_THRESHOLD_BYTES:
        return RasterioImageSource(path)
    return PillowImageSource(path)
