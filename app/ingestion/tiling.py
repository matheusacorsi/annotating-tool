# Ported verbatim from supervisely/backend/app/ingestion/tiling.py (private repo).
# This is a separate repo (yolo-obb-portable) - no shared package - keep in sync manually if
# the source-of-truth file changes tiling geometry/padding-mode behavior.

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

PaddingMode = Literal["shift", "reflect", "constant_black", "drop_partial"]


@dataclass(frozen=True)
class CropBox:
    x0: int
    y0: int
    width: int
    height: int


@dataclass(frozen=True)
class TileSpec:
    row: int
    col: int
    index: int
    # Origin in source-image pixel coordinates (crop offset already applied).
    x: int
    y: int
    width: int
    height: int
    # True when (x, y, width, height) extends past the crop bounds and the
    # extracted pixels need reflect/black padding to fill the tile canvas.
    needs_padding: bool


def compute_crop_box(source_width: int, source_height: int, proportion_pct: float) -> CropBox:
    if not (0 < proportion_pct <= 100):
        raise ValueError(f"proportion_pct must be in (0, 100], got {proportion_pct}")
    crop_w = round(source_width * proportion_pct / 100)
    crop_h = round(source_height * proportion_pct / 100)
    crop_w = max(1, min(crop_w, source_width))
    crop_h = max(1, min(crop_h, source_height))
    x0 = (source_width - crop_w) // 2
    y0 = (source_height - crop_h) // 2
    return CropBox(x0=x0, y0=y0, width=crop_w, height=crop_h)


def _axis_origins(crop_len: int, tile_len: int, overlap_pct: float) -> list[int]:
    stride = round(tile_len * (1 - overlap_pct / 100))
    stride = max(1, stride)
    if crop_len <= tile_len:
        return [0]
    n = math.ceil((crop_len - tile_len) / stride) + 1
    return [i * stride for i in range(n)]


def _fitted_extent(crop_len: int, tile_len: int, overlap_pct: float, source_len: int) -> int:
    if crop_len <= tile_len:
        return min(tile_len, source_len)
    stride = max(1, round(tile_len * (1 - overlap_pct / 100)))
    n = math.ceil((crop_len - tile_len) / stride) + 1
    needed = (n - 1) * stride + tile_len
    # Only ever grows the crop (never shrinks below what was requested) - capped at the
    # actual source image bounds, since there may not be enough source pixels to grow into.
    return min(needed, source_len)


def fit_crop_to_grid(
    crop: CropBox, source_width: int, source_height: int, tile_w: int, tile_h: int, overlap_pct: float
) -> CropBox:
    """Grows the requested crop box (re-centered, capped at the source image bounds) so a
    whole number of tiles fits at the *exact* requested stride on each axis, with no leftover
    tile needing to be shifted (and thereby forced to overlap its neighbor) to stay in bounds.

    compute_tile_grid's "shift" padding mode slides an overrunning last tile back flush with
    the crop edge - if the crop wasn't already an exact multiple of the tile stride, that shift
    silently introduces overlap even when overlap_pct=0, since the neighboring tile hasn't
    moved. Growing the crop first (surpassing the requested proportion_pct when needed) instead
    of shrinking the tile spacing keeps "no overlap" true at 0%, at the cost of using slightly
    more of the source image than requested - the caller should report the resulting crop size
    (e.g. as an effective crop %) back to the user.
    """
    new_w = _fitted_extent(crop.width, tile_w, overlap_pct, source_width)
    new_h = _fitted_extent(crop.height, tile_h, overlap_pct, source_height)
    x0 = (source_width - new_w) // 2
    y0 = (source_height - new_h) // 2
    return CropBox(x0=x0, y0=y0, width=new_w, height=new_h)


def compute_tile_grid(
    crop: CropBox,
    tile_w: int,
    tile_h: int,
    overlap_pct: float = 15,
    padding_mode: PaddingMode = "shift",
) -> list[TileSpec]:
    if tile_w <= 0 or tile_h <= 0:
        raise ValueError("tile dimensions must be positive")
    if not (0 <= overlap_pct < 100):
        raise ValueError(f"overlap_pct must be in [0, 100), got {overlap_pct}")

    col_origins = _axis_origins(crop.width, tile_w, overlap_pct)
    row_origins = _axis_origins(crop.height, tile_h, overlap_pct)

    tiles: list[TileSpec] = []
    index = 0
    for row, local_y in enumerate(row_origins):
        for col, local_x in enumerate(col_origins):
            x, y = local_x, local_y
            overrun_x = (x + tile_w) - crop.width
            overrun_y = (y + tile_h) - crop.height

            if padding_mode == "shift":
                if overrun_x > 0:
                    x = max(0, crop.width - tile_w)
                if overrun_y > 0:
                    y = max(0, crop.height - tile_h)
                overrun_x = (x + tile_w) - crop.width
                overrun_y = (y + tile_h) - crop.height
                needs_padding = overrun_x > 0 or overrun_y > 0  # only when tile itself > crop
            elif padding_mode == "drop_partial":
                if overrun_x > 0 or overrun_y > 0:
                    continue
                needs_padding = False
            else:  # reflect, constant_black
                needs_padding = overrun_x > 0 or overrun_y > 0

            tiles.append(
                TileSpec(
                    row=row,
                    col=col,
                    index=index,
                    x=crop.x0 + x,
                    y=crop.y0 + y,
                    width=tile_w,
                    height=tile_h,
                    needs_padding=needs_padding,
                )
            )
            index += 1

    return tiles


def sanitize_stem(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", normalized).strip("_")
    return normalized or "src"


def tile_filename(prefix: str, source_stem: str, tile: TileSpec, ext: str = "jpg") -> str:
    prefix = sanitize_stem(prefix)
    stem = sanitize_stem(source_stem)
    return f"{prefix}_{stem}_tile_{tile.index:05d}.{ext}"
