import io
import json
import zipfile

import numpy as np
import pytest
from PIL import Image

from app.annotations import Annotation, TileAnnotations
from app.manifest import ClassDef, IngestEvent, Manifest, SourceSummary
from app.portable_export_import import export_zip, import_zip
from app.session_state import SessionProject


def _fake_jpeg_bytes(size=(320, 320)) -> bytes:
    arr = (np.random.rand(size[1], size[0], 3) * 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _build_sample_project() -> SessionProject:
    manifest = Manifest(
        name="Sample Project",
        task_type="obb",
        classes=[ClassDef(id=0, name="corn_double"), ClassDef(id=1, name="corn_single")],
        sources=[
            SourceSummary(
                source_id="src1",
                prefix="field1",
                events=[IngestEvent(original_filenames=["IMG_0001.jpg"], tile_ids=["field1_IMG_0001_tile_00000"])],
            )
        ],
    )
    tile_id = "field1_IMG_0001_tile_00000"
    jpg = _fake_jpeg_bytes()
    annotations = {
        tile_id: TileAnnotations(
            tile_id=tile_id,
            width=320,
            height=320,
            annotations=[
                Annotation(class_id=1, cx=100, cy=100, w=40, h=20, angle=15, source="model",
                           confidence=0.82, status="unconfirmed"),
            ],
        )
    }
    return SessionProject(manifest=manifest, tiles={tile_id: jpg}, thumbnails={tile_id: jpg}, annotations=annotations)


class TestExportImportRoundTrip:
    def test_portable_tiled_project_survives_export_then_reimport(self):
        original = _build_sample_project()
        zip_bytes = export_zip(original)
        reimported = import_zip(zip_bytes)

        assert reimported.manifest.name == original.manifest.name
        assert reimported.manifest.task_type == original.manifest.task_type
        assert [c.name for c in reimported.manifest.classes] == [c.name for c in original.manifest.classes]
        assert set(reimported.tiles.keys()) == set(original.tiles.keys())

        tile_id = next(iter(original.tiles))
        orig_ann = original.annotations[tile_id].annotations[0]
        reimported_ann = reimported.annotations[tile_id].annotations[0]
        assert reimported_ann.class_id == orig_ann.class_id
        assert reimported_ann.status == "unconfirmed"  # pre-annotation handoff must survive intact
        assert reimported_ann.source == "model"
        assert reimported_ann.confidence == orig_ann.confidence
        assert reimported_ann.cx == orig_ann.cx

    def test_export_includes_regenerated_yolo_labels(self):
        project = _build_sample_project()
        zip_bytes = export_zip(project)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            tile_id = next(iter(project.tiles))
            assert f"labels/{tile_id}.txt" in names
            label_text = zf.read(f"labels/{tile_id}.txt").decode()
            parts = label_text.split()
            assert parts[0] == "1"  # class_id
            assert len(parts) == 9  # class + 4 (x,y) OBB corner pairs

    def test_import_rejects_archive_without_manifest(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("images/foo.jpg", b"not a real image")
        with pytest.raises(ValueError):
            import_zip(buf.getvalue())

    def test_import_rejects_a_non_zip_upload(self):
        # A corrupt or wrong-type upload raises zipfile.BadZipFile, not ValueError - import_zip
        # must normalize it so callers only need one except clause.
        with pytest.raises(ValueError):
            import_zip(b"this is not a zip file at all")

    def test_import_rejects_malformed_manifest_json(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("manifest.json", "{not valid json")
        with pytest.raises(ValueError):
            import_zip(buf.getvalue())

    def test_import_rejects_manifest_failing_schema_validation(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            # Missing the required "name" field.
            zf.writestr("manifest.json", json.dumps({"schema_version": 3, "classes": [], "sources": []}))
        with pytest.raises(ValueError):
            import_zip(buf.getvalue())

    def test_import_ignores_training_and_test_run_directories(self):
        project = _build_sample_project()
        zip_bytes = export_zip(project)
        # Simulate a full-app export that also includes runs/ (training artifacts) - the
        # portable app must skip these gracefully, not error out.
        buf = io.BytesIO(zip_bytes)
        with zipfile.ZipFile(buf, "a") as zf:
            zf.writestr("runs/abc123/weights/best.pt", b"fake weights")
            zf.writestr("tests/xyz/metrics.json", "{}")
        reimported = import_zip(buf.getvalue())
        assert len(reimported.tiles) == 1

    def test_import_regenerates_missing_thumbnail(self):
        project = _build_sample_project()
        zip_bytes = export_zip(project)
        # Strip the thumbnail from the archive to simulate a hand-built/partial zip.
        buf_in = io.BytesIO(zip_bytes)
        buf_out = io.BytesIO()
        with zipfile.ZipFile(buf_in) as zin, zipfile.ZipFile(buf_out, "w") as zout:
            for item in zin.infolist():
                if item.filename.startswith("thumbnails/"):
                    continue
                zout.writestr(item, zin.read(item.filename))
        reimported = import_zip(buf_out.getvalue())
        tile_id = next(iter(project.tiles))
        assert tile_id in reimported.thumbnails

    def test_reexport_of_a_reimported_project_is_stable(self):
        original = _build_sample_project()
        once = import_zip(export_zip(original))
        twice = import_zip(export_zip(once))
        assert once.manifest.model_dump(mode="json") == twice.manifest.model_dump(mode="json")
        assert set(once.tiles) == set(twice.tiles)


class TestFullAppCompatibility:
    def test_imports_a_manifest_shaped_like_the_full_apps_export(self):
        """Builds a zip matching the exact byte-layout the full app's export_import.py
        produces (manifest.json + images/ + labels/ + annotations/ + thumbnails/), to confirm
        this app's import_zip is compatible with real full-app exports, not just its own."""
        manifest_dict = {
            "schema_version": 3,
            "project_id": "abc123",
            "name": "Full App Export",
            "task_type": "obb",
            "classes": [{"id": 0, "name": "corn", "color": "#3DBE5B"}],
            "tiling_defaults": {"tile_w": 640, "tile_h": 640, "overlap_pct": 15, "padding_mode": "shift", "proportion_pct": 30},
            "sources": [{"source_id": "s1", "prefix": "field1", "events": [
                {"ingested_at": None, "source_type": "photo", "proportion_pct": 30,
                 "original_filenames": ["IMG_0001.jpg"], "tile_ids": ["field1_IMG_0001_tile_00000"]}
            ]}],
        }
        ann_dict = {
            "schema_version": 1, "tile_id": "field1_IMG_0001_tile_00000", "width": 640, "height": 640,
            "annotations": [{"id": "a1", "class_id": 0, "cx": 320, "cy": 320, "w": 50, "h": 30,
                              "angle": 0, "source": "manual", "confidence": None, "status": "confirmed",
                              "updated_at": "2026-01-01T00:00:00Z"}],
            "updated_at": "2026-01-01T00:00:00Z",
        }
        jpg = _fake_jpeg_bytes((640, 640))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest_dict))
            zf.writestr("images/field1_IMG_0001_tile_00000.jpg", jpg)
            zf.writestr("thumbnails/field1_IMG_0001_tile_00000.jpg", jpg)
            zf.writestr("annotations/field1_IMG_0001_tile_00000.json", json.dumps(ann_dict))
            zf.writestr("labels/field1_IMG_0001_tile_00000.txt", "0 0.4 0.4 0.6 0.4 0.6 0.6 0.4 0.6\n")

        project = import_zip(buf.getvalue())
        assert project.manifest.name == "Full App Export"
        assert len(project.tiles) == 1
        assert project.annotations["field1_IMG_0001_tile_00000"].annotations[0].class_id == 0
