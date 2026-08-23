# Ported verbatim from supervisely/backend/app/ingestion/tile_extract.py (private repo).
# This is a separate repo (yolo-obb-portable) - no shared package - keep in sync manually.

from __future__ import annotations

import numpy as np

from app.ingestion.image_sources import ImageSource
from app.ingestion.tiling import CropBox, PaddingMode, TileSpec


def extract_tile(source: ImageSource, crop: CropBox, tile: TileSpec, padding_mode: PaddingMode) -> np.ndarray:
    """Reads a tile's pixels, clamped strictly to the crop box (never the wider source image -
    padding fills the shortfall synthetically so a 'reflect'/'constant_black' tile never sneaks
    in real pixels from outside the user's chosen crop percentage)."""
    crop_x1, crop_y1 = crop.x0 + crop.width, crop.y0 + crop.height
    valid_x0 = max(tile.x, crop.x0)
    valid_y0 = max(tile.y, crop.y0)
    valid_x1 = min(tile.x + tile.width, crop_x1)
    valid_y1 = min(tile.y + tile.height, crop_y1)

    canvas = np.zeros((tile.height, tile.width, 3), dtype=np.uint8)
    valid_w = max(0, valid_x1 - valid_x0)
    valid_h = max(0, valid_y1 - valid_y0)
    if valid_w > 0 and valid_h > 0:
        raw = source.read_raw(valid_x0, valid_y0, valid_w, valid_h)
        off_x, off_y = valid_x0 - tile.x, valid_y0 - tile.y
        canvas[off_y : off_y + valid_h, off_x : off_x + valid_w] = raw

    if not tile.needs_padding or padding_mode in ("constant_black", "shift", "drop_partial"):
        return canvas

    if padding_mode == "reflect" and valid_w > 0 and valid_h > 0:
        pad_bottom = tile.height - valid_h
        pad_right = tile.width - valid_w
        # np.pad's reflect mode requires the pad width to not exceed the source dimension;
        # fall back to edge-replication for the rare tile where the overrun is that large.
        mode = "reflect" if pad_bottom < valid_h and pad_right < valid_w else "edge"
        region = canvas[:valid_h, :valid_w]
        canvas = np.pad(region, ((0, pad_bottom), (0, pad_right), (0, 0)), mode=mode)
    return canvas
