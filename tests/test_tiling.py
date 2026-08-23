import pytest

from app.ingestion.tiling import (
    compute_crop_box,
    compute_tile_grid,
    fit_crop_to_grid,
    sanitize_stem,
    tile_filename,
)


def _spans_overlap(a_x0: int, a_w: int, b_x0: int, b_w: int) -> bool:
    return a_x0 < b_x0 + b_w and b_x0 < a_x0 + a_w


class TestComputeCropBox:
    def test_30_pct_is_per_dimension_not_area(self):
        crop = compute_crop_box(1000, 2000, 30)
        assert crop.width == 300
        assert crop.height == 600

    def test_centered_on_centroid(self):
        crop = compute_crop_box(1000, 1000, 50)
        assert crop.width == 500
        assert crop.height == 500
        assert crop.x0 == 250
        assert crop.y0 == 250

    def test_100_pct_is_whole_image(self):
        crop = compute_crop_box(800, 600, 100)
        assert (crop.x0, crop.y0, crop.width, crop.height) == (0, 0, 800, 600)

    def test_odd_dimensions_stay_in_bounds(self):
        crop = compute_crop_box(1001, 999, 33)
        assert crop.x0 + crop.width <= 1001
        assert crop.y0 + crop.height <= 999

    def test_rejects_out_of_range_proportion(self):
        with pytest.raises(ValueError):
            compute_crop_box(100, 100, 0)
        with pytest.raises(ValueError):
            compute_crop_box(100, 100, 101)


class TestComputeTileGrid:
    def test_exact_fit_no_overlap(self):
        crop = compute_crop_box(1280, 640, 100)
        tiles = compute_tile_grid(crop, 640, 640, overlap_pct=0, padding_mode="shift")
        assert len(tiles) == 2
        assert {(t.row, t.col) for t in tiles} == {(0, 0), (0, 1)}
        assert not any(t.needs_padding for t in tiles)

    def test_shift_mode_last_tile_flush_no_padding(self):
        crop = compute_crop_box(1000, 640, 100)  # 1000 not evenly divisible by 640
        tiles = compute_tile_grid(crop, 640, 640, overlap_pct=0, padding_mode="shift")
        assert not any(t.needs_padding for t in tiles)
        for t in tiles:
            assert t.x + t.width <= crop.x0 + crop.width
            assert t.y + t.height <= crop.y0 + crop.height

    def test_drop_partial_excludes_overrunning_tiles(self):
        crop = compute_crop_box(1000, 640, 100)
        tiles = compute_tile_grid(crop, 640, 640, overlap_pct=0, padding_mode="drop_partial")
        # second column (x=640) would overrun 1000 by 280px -> dropped
        assert len(tiles) == 1
        assert tiles[0].col == 0

    def test_reflect_mode_keeps_overrunning_tile_flagged(self):
        crop = compute_crop_box(1000, 640, 100)
        tiles = compute_tile_grid(crop, 640, 640, overlap_pct=0, padding_mode="reflect")
        assert len(tiles) == 2
        assert tiles[1].needs_padding is True
        assert tiles[0].needs_padding is False

    def test_overlap_50_pct_doubles_tile_density_along_axis(self):
        crop = compute_crop_box(1280, 640, 100)
        no_overlap = compute_tile_grid(crop, 640, 640, overlap_pct=0, padding_mode="drop_partial")
        with_overlap = compute_tile_grid(crop, 640, 640, overlap_pct=50, padding_mode="drop_partial")
        assert len(with_overlap) > len(no_overlap)

    def test_tile_larger_than_crop_single_tile_needs_padding(self):
        crop = compute_crop_box(300, 300, 100)
        tiles = compute_tile_grid(crop, 640, 640, overlap_pct=15, padding_mode="reflect")
        assert len(tiles) == 1
        assert tiles[0].needs_padding is True
        assert tiles[0].x == crop.x0
        assert tiles[0].y == crop.y0

    def test_tile_larger_than_crop_drop_partial_yields_no_tiles(self):
        crop = compute_crop_box(300, 300, 100)
        tiles = compute_tile_grid(crop, 640, 640, overlap_pct=15, padding_mode="drop_partial")
        assert tiles == []

    def test_indices_are_sequential_and_unique(self):
        crop = compute_crop_box(2000, 1500, 100)
        tiles = compute_tile_grid(crop, 640, 640, overlap_pct=15, padding_mode="shift")
        indices = [t.index for t in tiles]
        assert indices == list(range(len(tiles)))

    def test_rejects_bad_overlap(self):
        crop = compute_crop_box(1000, 1000, 100)
        with pytest.raises(ValueError):
            compute_tile_grid(crop, 640, 640, overlap_pct=100, padding_mode="shift")


class TestFitCropToGrid:
    def test_zero_overlap_grows_crop_to_avoid_shift_induced_overlap(self):
        # 2000x640 source, 50% crop -> 1000px wide requested crop, 640px tiles: 1000 isn't an
        # exact multiple of 640, so the old shift-based grid would overlap the last tile by
        # 280px even at overlap_pct=0. There's plenty of source slack (2000 >= needed 1280),
        # so the fix should grow the crop instead of ever letting tiles overlap.
        crop = compute_crop_box(2000, 640, 50)
        assert crop.width == 1000  # sanity check on the pre-fix crop size

        fitted = fit_crop_to_grid(crop, 2000, 640, 640, 640, overlap_pct=0)
        assert fitted.width == 1280  # (n-1)*stride + tile_w = 640 + 640
        assert fitted.width > crop.width  # grew, never shrank
        assert fitted.width <= 2000  # stayed within the actual source image

        tiles = compute_tile_grid(fitted, 640, 640, overlap_pct=0, padding_mode="shift")
        assert len(tiles) == 2
        assert not any(t.needs_padding for t in tiles)
        cols = sorted(tiles, key=lambda t: t.x)
        assert not _spans_overlap(cols[0].x, cols[0].width, cols[1].x, cols[1].width)
        # exactly adjacent, no gap and no overlap
        assert cols[0].x + cols[0].width == cols[1].x

    def test_recenters_the_grown_crop_on_the_source_image(self):
        crop = compute_crop_box(2000, 640, 50)
        fitted = fit_crop_to_grid(crop, 2000, 640, 640, 640, overlap_pct=0)
        assert fitted.x0 == (2000 - fitted.width) // 2

    def test_never_shrinks_below_the_requested_crop(self):
        crop = compute_crop_box(1280, 640, 100)  # already an exact multiple, no growth needed
        fitted = fit_crop_to_grid(crop, 1280, 640, 640, 640, overlap_pct=0)
        assert fitted.width == crop.width == 1280

    def test_caps_growth_at_the_source_image_when_no_slack_is_available(self):
        # 100% crop already uses the whole source width - there's no room to grow into, so
        # the fitted extent can't exceed the source even though a clean grid would want more.
        crop = compute_crop_box(1000, 640, 100)
        fitted = fit_crop_to_grid(crop, 1000, 640, 640, 640, overlap_pct=0)
        assert fitted.width == 1000

    def test_nonzero_overlap_still_fits_a_whole_number_of_tiles(self):
        crop = compute_crop_box(2000, 640, 50)  # 1000px requested
        fitted = fit_crop_to_grid(crop, 2000, 640, 640, 640, overlap_pct=15)
        tiles = compute_tile_grid(fitted, 640, 640, overlap_pct=15, padding_mode="shift")
        assert not any(t.needs_padding for t in tiles)


class TestFilenames:
    def test_sanitizes_unsafe_characters(self):
        assert sanitize_stem("Field #1 (north) / drone.raw") == "Field_1_north_drone_raw"

    def test_tile_filename_is_deterministic_and_unique_per_index(self):
        crop = compute_crop_box(1280, 640, 100)
        tiles = compute_tile_grid(crop, 640, 640, overlap_pct=0, padding_mode="shift")
        names = {tile_filename("field1", "IMG_0003", t) for t in tiles}
        assert len(names) == len(tiles)
        assert all(n.startswith("field1_IMG_0003_tile_") for n in names)
