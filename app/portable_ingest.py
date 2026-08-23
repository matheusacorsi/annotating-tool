from __future__ import annotations

import io
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from PIL import Image

from app.annotations import TileAnnotations
from app.config import THUMBNAIL_QUALITY, THUMBNAIL_SIZE, TILE_JPEG_QUALITY
from app.ingestion.image_sources import open_image_source
from app.ingestion.tile_extract import extract_tile
from app.ingestion.tiling import compute_crop_box, compute_tile_grid, fit_crop_to_grid, tile_filename
from app.manifest import ClassDef, IngestEvent, Manifest, SourceSummary
from app.session_state import SessionProject


class UploadedFileLike:
    """Minimal protocol matching Streamlit's UploadedFile - lets tests pass a plain stand-in
    without needing a real Streamlit runtime."""

    name: str

    def getvalue(self) -> bytes: ...


def _encode_tile_jpeg(arr) -> bytes:
    buf = io.BytesIO()
    # subsampling=0 (4:4:4, no chroma subsampling) at quality=100 mirrors the full app's
    # ingest_job.py exactly - keeps tile pixel data identical, which matters for annotation
    # precision (fine plant-edge detail shouldn't get blurred by chroma downsampling).
    Image.fromarray(arr).save(buf, format="JPEG", quality=TILE_JPEG_QUALITY, subsampling=0)
    return buf.getvalue()


def _encode_thumbnail_jpeg(arr) -> bytes:
    img = Image.fromarray(arr)
    img.thumbnail((THUMBNAIL_SIZE, THUMBNAIL_SIZE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=THUMBNAIL_QUALITY)
    return buf.getvalue()


def preview_tile_counts(
    files: list[UploadedFileLike], tile_w: int, tile_h: int, overlap_pct: float, proportion_pct: float
) -> list[dict]:
    """Dry-run: computes tile counts and the effective (possibly grown) crop % per file,
    without extracting any pixels - mirrors the full app's stateless POST /api/ingest/preview."""
    results = []
    for f in files:
        with tempfile.NamedTemporaryFile(suffix=Path(f.name).suffix) as tmp:
            tmp.write(f.getvalue())
            tmp.flush()
            source = open_image_source(Path(tmp.name))
            try:
                w, h = source.dimensions()
            finally:
                source.close()
        crop = compute_crop_box(w, h, proportion_pct)
        fitted = fit_crop_to_grid(crop, w, h, tile_w, tile_h, overlap_pct)
        grid = compute_tile_grid(fitted, tile_w, tile_h, overlap_pct, "shift")
        effective_w_pct = fitted.width / w * 100
        effective_h_pct = fitted.height / h * 100
        results.append(
            {
                "filename": f.name,
                "width": w,
                "height": h,
                "tile_count": len(grid),
                "requested_proportion_pct": proportion_pct,
                "effective_width_pct": effective_w_pct,
                "effective_height_pct": effective_h_pct,
            }
        )
    return results


def tile_uploaded_files(
    files: list[UploadedFileLike],
    tile_w: int,
    tile_h: int,
    overlap_pct: float,
    padding_mode: str,
    proportion_pct: float,
    prefix: str,
    classes: list[ClassDef],
    project_name: str,
    task_type: str = "obb",
) -> SessionProject:
    """Tiles a batch of uploaded raw images entirely in memory - the uploaded bytes touch disk
    only transiently (a NamedTemporaryFile deleted immediately after tiling that one file, since
    open_image_source needs a real path for rasterio-style windowed reads); the derived tiles
    never touch disk at all, only session-state-bound bytes dicts."""
    tiles: dict[str, bytes] = {}
    thumbnails: dict[str, bytes] = {}
    annotations: dict[str, TileAnnotations] = {}
    tile_ids: list[str] = []
    filenames: list[str] = []

    for f in files:
        with tempfile.NamedTemporaryFile(suffix=Path(f.name).suffix) as tmp:
            tmp.write(f.getvalue())
            tmp.flush()
            source = open_image_source(Path(tmp.name))
            try:
                w, h = source.dimensions()
                crop = compute_crop_box(w, h, proportion_pct)
                crop = fit_crop_to_grid(crop, w, h, tile_w, tile_h, overlap_pct)
                grid = compute_tile_grid(crop, tile_w, tile_h, overlap_pct, padding_mode)
                for spec in grid:
                    arr = extract_tile(source, crop, spec, padding_mode)
                    filename = tile_filename(prefix, Path(f.name).stem, spec)
                    tile_id = filename.removesuffix(".jpg")
                    if tile_id in tiles:  # defensive; shouldn't happen within one batch
                        tile_id = f"{tile_id}_{uuid4().hex[:4]}"
                    tiles[tile_id] = _encode_tile_jpeg(arr)
                    thumbnails[tile_id] = _encode_thumbnail_jpeg(arr)
                    annotations[tile_id] = TileAnnotations(tile_id=tile_id, width=tile_w, height=tile_h)
                    tile_ids.append(tile_id)
            finally:
                source.close()
        filenames.append(f.name)

    manifest = Manifest(
        name=project_name,
        task_type=task_type,  # type: ignore[arg-type]
        classes=classes,
        sources=[
            SourceSummary(
                source_id=uuid4().hex[:8],
                prefix=prefix,
                events=[
                    IngestEvent(
                        ingested_at=datetime.now(timezone.utc),
                        proportion_pct=proportion_pct,
                        original_filenames=filenames,
                        tile_ids=tile_ids,
                    )
                ],
            )
        ],
    )
    manifest.tiling_defaults.tile_w = tile_w
    manifest.tiling_defaults.tile_h = tile_h
    manifest.tiling_defaults.overlap_pct = overlap_pct
    manifest.tiling_defaults.padding_mode = padding_mode
    manifest.tiling_defaults.proportion_pct = proportion_pct

    return SessionProject(manifest=manifest, tiles=tiles, thumbnails=thumbnails, annotations=annotations)
