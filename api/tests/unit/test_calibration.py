"""Stage 12 — calibration drift detection: a reworked/mismatched map is flagged, not silent."""
import pandas as pd
import pytest

from app.ingest.calibration import check_calibration, sample_positions, world_to_image

pytestmark = pytest.mark.unit

INFERNO = {"pos_x": -2087, "pos_y": 3870, "scale": 4.9, "version": "live"}


def test_world_to_image_origin():
    assert world_to_image(INFERNO, -2087, 3870) == (0.0, 0.0)


def test_in_bounds_positions_not_suspect():
    pts = [(0, 0), (2000, 2000), (-1000, 1000), (1500, -500), (-2000, 3000)]
    res = check_calibration(INFERNO, pts)
    assert res["checked"] is True
    assert res["suspect"] is False and res["in_bounds_fraction"] == 1.0


def test_wildly_off_positions_flag_suspect():
    # a wrong calibration would project real positions far off the radar
    pts = [(100_000, 100_000)] * 5 + [(-90_000, -90_000)] * 5
    res = check_calibration(INFERNO, pts)
    assert res["suspect"] is True and res["in_bounds_fraction"] == 0.0


def test_unknown_map_is_not_flagged():
    res = check_calibration(None, [(0, 0)])
    assert res["suspect"] is False and res["checked"] is False


def test_sample_positions_strides_the_frame():
    df = pd.DataFrame({"X": list(range(1000)), "Y": list(range(1000))})
    pts = sample_positions(df, limit=50)
    assert 0 < len(pts) <= 60
    assert all(isinstance(x, float) for x, _ in pts)
