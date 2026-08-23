import io

import numpy as np
from PIL import Image

from app.ingestion.tiling import compute_crop_box, compute_tile_grid, fit_crop_to_grid
from app.manifest import ClassDef
from app.portable_ingest import preview_tile_counts, tile_uploaded_files


class FakeUploadedFile:
    def __init__(self, name: str, data: bytes):
        self.name = name
        self._data = data

    def getvalue(self) -> bytes:
        return self._data


def _fake_jpeg(width: int, height: int) -> bytes:
    arr = (np.random.rand(height, width, 3) * 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="JPEG", quality=90)
    return buf.getvalue()


class TestTileUploadedFiles:
    def test_tile_count_matches_manual_grid_computation(self):
        width, height = 1280, 960
        f = FakeUploadedFile("IMG_0001.jpg", _fake_jpeg(width, height))

        project = tile_uploaded_files(
            files=[f],
            tile_w=320,
            tile_h=320,
            overlap_pct=0,
            padding_mode="shift",
            proportion_pct=100,
            prefix="test",
            classes=[ClassDef(id=0, name="corn")],
            project_name="Test Project",
        )

        # Manually reproduce the exact same pure-function pipeline to cross-check.
        crop = compute_crop_box(width, height, 100)
        crop = fit_crop_to_grid(crop, width, height, 320, 320, 0)
        expected_grid = compute_tile_grid(crop, 320, 320, 0, "shift")

        assert len(project.tiles) == len(expected_grid)
        assert len(project.thumbnails) == len(expected_grid)
        assert len(project.annotations) == len(expected_grid)
        assert project.manifest.sources[0].tile_count == len(expected_grid)

    def test_tiles_are_real_jpegs_of_the_requested_size(self):
        f = FakeUploadedFile("IMG_0001.jpg", _fake_jpeg(640, 640))
        project = tile_uploaded_files(
            files=[f], tile_w=320, tile_h=320, overlap_pct=0, padding_mode="shift",
            proportion_pct=100, prefix="p", classes=[ClassDef(id=0, name="a")], project_name="T",
        )
        first_tile_bytes = next(iter(project.tiles.values()))
        img = Image.open(io.BytesIO(first_tile_bytes))
        assert img.format == "JPEG"
        assert img.size == (320, 320)

    def test_empty_annotations_created_per_tile(self):
        f = FakeUploadedFile("IMG_0001.jpg", _fake_jpeg(640, 640))
        project = tile_uploaded_files(
            files=[f], tile_w=320, tile_h=320, overlap_pct=0, padding_mode="shift",
            proportion_pct=100, prefix="p", classes=[ClassDef(id=0, name="a")], project_name="T",
        )
        for ann in project.annotations.values():
            assert ann.annotations == []
            assert ann.status == "empty"

    def test_manifest_classes_and_task_type_preserved(self):
        f = FakeUploadedFile("IMG_0001.jpg", _fake_jpeg(640, 640))
        classes = [ClassDef(id=0, name="corn_double"), ClassDef(id=1, name="corn_single")]
        project = tile_uploaded_files(
            files=[f], tile_w=320, tile_h=320, overlap_pct=0, padding_mode="shift",
            proportion_pct=100, prefix="p", classes=classes, project_name="T", task_type="obb",
        )
        assert [c.name for c in project.manifest.classes] == ["corn_double", "corn_single"]
        assert project.manifest.task_type == "obb"

    def test_multiple_files_share_one_source_group_by_prefix(self):
        files = [FakeUploadedFile(f"IMG_{i:04d}.jpg", _fake_jpeg(640, 640)) for i in range(3)]
        project = tile_uploaded_files(
            files=files, tile_w=320, tile_h=320, overlap_pct=0, padding_mode="shift",
            proportion_pct=100, prefix="field1", classes=[ClassDef(id=0, name="a")], project_name="T",
        )
        assert len(project.manifest.sources) == 1
        assert project.manifest.sources[0].tile_count == 12  # 4 tiles/image * 3 images


class TestPreviewTileCounts:
    def test_preview_matches_actual_tiling_count(self):
        f = FakeUploadedFile("IMG_0001.jpg", _fake_jpeg(1280, 960))
        preview = preview_tile_counts([f], tile_w=320, tile_h=320, overlap_pct=0, proportion_pct=100)
        project = tile_uploaded_files(
            files=[f], tile_w=320, tile_h=320, overlap_pct=0, padding_mode="shift",
            proportion_pct=100, prefix="p", classes=[ClassDef(id=0, name="a")], project_name="T",
        )
        assert preview[0]["tile_count"] == len(project.tiles)
