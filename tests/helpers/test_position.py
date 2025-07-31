from overlays.helpers import (
    BOX_H,
    BOX_W,
    GAP,
    TOP,
    get_countdown_position,
    get_qrcode_position,
)


def test_get_countdown_position_zero_index():
    """Index 0 should compute centered left and top equal to TOP."""
    full = (0, 0, 100, 200)
    left, top, right, bottom = get_countdown_position(0, full)
    expected_left = (full[2] - BOX_W) // 2
    expected_top = TOP + 0 * (BOX_H + GAP)
    assert (left, top, right, bottom) == (
        expected_left,
        expected_top,
        expected_left + BOX_W,
        expected_top + BOX_H,
    )


def test_get_countdown_position_multiple_index():
    """Index >0 should offset top by index*(BOX_H+GAP)."""
    full = (10, 5, 90, 150)
    idx = 2
    left, top, right, bottom = get_countdown_position(idx, full)
    expected_left = (full[2] - BOX_W) // 2
    expected_top = TOP + idx * (BOX_H + GAP)
    assert (left, top, right, bottom) == (
        expected_left,
        expected_top,
        expected_left + BOX_W,
        expected_top + BOX_H,
    )


def test_get_qrcode_position_zero_index():
    """Index 0 should compute centered QR code at top_start."""
    full = (0, 0, 50, 50)
    total = 10
    box_gap = 4
    top_start = 3
    left, top, right, bottom = get_qrcode_position(0, total, box_gap, top_start, full)
    expected_left = (full[2] - total) // 2
    expected_top = top_start + 0 * (total + box_gap)
    assert (left, top, right, bottom) == (
        expected_left,
        expected_top,
        expected_left + total,
        expected_top + total,
    )


def test_get_qrcode_position_multiple_index():
    """Index >0 should offset top by index*(total+box_gap)."""
    full = (5, 5, 100, 100)
    total = 20
    box_gap = 5
    top_start = 2
    idx = 1
    left, top, right, bottom = get_qrcode_position(idx, total, box_gap, top_start, full)
    expected_left = (full[2] - total) // 2
    expected_top = top_start + idx * (total + box_gap)
    assert (left, top, right, bottom) == (
        expected_left,
        expected_top,
        expected_left + total,
        expected_top + total,
    )
