from __future__ import annotations

import io
import json
import zipfile

from PIL import Image
from pydantic import ValidationError

from app.annotations import TileAnnotations, migrate_tile_annotations
from app.config import THUMBNAIL_QUALITY, THUMBNAIL_SIZE
from app.manifest import Manifest, migrate_manifest
from app.obb_geometry import obb_to_axis_aligned, to_yolo_detect_line, to_yolo_obb_line
from app.session_state import SessionProject

# Top-level directories the full app's export can contain that this app never produces and
# should silently ignore on import (training runs, test runs, in-flight job state - all
# irrelevant to an ingest+annotate-only tool).
_IGNORED_TOP_LEVEL_DIRS = ("models", "runs", "tests", ".jobs")


def import_zip(zip_bytes: bytes) -> SessionProject:
    # Every failure mode below (corrupt upload, missing/malformed manifest, unparseable
    # annotations JSON) is normalized to ValueError so callers only need one except clause -
    # otherwise a genuinely non-zip upload raises zipfile.BadZipFile, a malformed manifest
    # raises pydantic's ValidationError, etc., and an uncaught one would surface to the user as
    # a raw traceback instead of a clean st.error message.
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            if "manifest.json" not in names:
                raise ValueError("Invalid project archive: missing manifest.json")

            manifest_data = migrate_manifest(json.loads(zf.read("manifest.json")))
            manifest = Manifest.model_validate(manifest_data)

            tiles: dict[str, bytes] = {}
            thumbnails: dict[str, bytes] = {}
            annotations: dict[str, TileAnnotations] = {}

            for name in names:
                if name.endswith("/") or any(name.startswith(f"{d}/") for d in _IGNORED_TOP_LEVEL_DIRS):
                    continue
                if name.startswith("images/") and name.endswith(".jpg"):
                    tile_id = name[len("images/") : -len(".jpg")]
                    tiles[tile_id] = zf.read(name)
                elif name.startswith("thumbnails/") and name.endswith(".jpg"):
                    tile_id = name[len("thumbnails/") : -len(".jpg")]
                    thumbnails[tile_id] = zf.read(name)
                elif name.startswith("annotations/") and name.endswith(".json"):
                    tile_id = name[len("annotations/") : -len(".json")]
                    data = migrate_tile_annotations(json.loads(zf.read(name)))
                    annotations[tile_id] = TileAnnotations.model_validate(data)
                # labels/*.txt intentionally ignored on import - derived data, regenerated on export.

            # Regenerate any thumbnail missing from the archive, mirroring the full app's
            # _regenerate_missing_thumbnails.
            for tile_id, jpg_bytes in tiles.items():
                if tile_id not in thumbnails:
                    img = Image.open(io.BytesIO(jpg_bytes))
                    img.thumbnail((THUMBNAIL_SIZE, THUMBNAIL_SIZE))
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=THUMBNAIL_QUALITY)
                    thumbnails[tile_id] = buf.getvalue()

            # A tile referenced by the manifest's sources but missing its annotations.json (e.g.
            # a hand-edited or partial archive) still needs an empty TileAnnotations so the
            # Annotate screen has something to render/save against.
            for tile_id in tiles:
                if tile_id not in annotations:
                    with Image.open(io.BytesIO(tiles[tile_id])) as img:
                        w, h = img.size
                    annotations[tile_id] = TileAnnotations(tile_id=tile_id, width=w, height=h)
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid project archive: not a valid zip file") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid project archive: malformed JSON ({exc})") from exc
    except ValidationError as exc:
        raise ValueError(f"Invalid project archive: {exc}") from exc

    return SessionProject(manifest=manifest, tiles=tiles, thumbnails=thumbnails, annotations=annotations)


def _yolo_label_text(ann: TileAnnotations, task_type: str) -> str:
    # Mirrors the exact branch in the full app's backend/app/annotations/service.py:
    # save_tile_annotations - detect-task projects collapse through obb_to_axis_aligned first
    # so a stray nonzero angle on a detect project still exports a valid axis-aligned line.
    lines = []
    for a in ann.annotations:
        if task_type == "detect":
            line = to_yolo_detect_line(
                a.class_id, *obb_to_axis_aligned(a.cx, a.cy, a.w, a.h, a.angle), ann.width, ann.height
            )
        else:
            line = to_yolo_obb_line(a.class_id, a.cx, a.cy, a.w, a.h, a.angle, ann.width, ann.height)
        lines.append(line)
    return "\n".join(lines) + ("\n" if lines else "")


def export_zip(project: SessionProject) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(project.manifest.model_dump(mode="json")))
        for tile_id, jpg in project.tiles.items():
            zf.writestr(f"images/{tile_id}.jpg", jpg)
        for tile_id, jpg in project.thumbnails.items():
            zf.writestr(f"thumbnails/{tile_id}.jpg", jpg)
        for tile_id, ann in project.annotations.items():
            zf.writestr(f"annotations/{tile_id}.json", ann.model_dump_json())
            zf.writestr(f"labels/{tile_id}.txt", _yolo_label_text(ann, project.manifest.task_type))
    return buf.getvalue()
