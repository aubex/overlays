from collections.abc import Callable
from unittest.mock import patch

import pytest
import win32con

from helpers import measure_text


@pytest.fixture
def mock_hdc() -> None:
    # We cannot create a real HDC easily in tests, so just return a mock integer or None.
    return 1  # Just a dummy handle value.


@pytest.fixture
def mock_font() -> None:
    # Font handles are also system-dependent. Return None or a dummy handle.
    return None


@pytest.fixture
def mock_drawtextw() -> Callable[[int, int, int, tuple[int, int, int, int], int], int]:
    # Create a mock function to replace DrawTextW.
    # The real DrawTextW sets rect_array based on measured text. We'll simulate that:
    def fake_drawtextw(
        hdc: int,
        text: int,
        text_len: int,
        rect_ptr: tuple[int, int, int, int],
        flags: int,
    ) -> int:
        # rect_ptr is a ctypes array of four longs [left, top, right, bottom].
        # We'll simulate a measurement result. For example:
        # Let's say the measured width is 200 and height is 40.
        rect = rect_ptr
        rect[0] = 0  # left
        rect[1] = 0  # top
        rect[2] = 200  # right
        rect[3] = 40  # bottom
        return 1  # Return value not really important, just non-zero

    return fake_drawtextw


@pytest.fixture
def mock_selectobject() -> Callable[[int, int], int | None]:
    # Mock win32gui.SelectObject so it doesn't fail in tests
    def fake_selectobject(hdc: int, obj: int) -> int | None:
        return None  # Normally returns the previously selected object

    return fake_selectobject


def test_measure_text_basic(
    mock_hdc: int,
    mock_font: None,
    mock_drawtextw: Callable[[int, int, int, tuple[int, int, int, int], int], int],
    mock_selectobject: Callable[[int, int], int | None],
) -> None:
    # Patch DrawTextW and SelectObject calls
    with (
        patch("helpers.DrawTextW", new=mock_drawtextw),
        patch("helpers.win32gui.SelectObject", new=mock_selectobject),
    ):
        # Run measure_text with defaults
        width, height = measure_text(
            hdc=mock_hdc,
            text="Hello World!",
            max_width=400,
            font=mock_font,
        )
        assert width == 200
        assert height == 40


def test_measure_text_different_flags(
    mock_hdc: int,
    mock_font: None,  # Adjust to int if fixture changes
    mock_drawtextw: Callable[[int, int, int, tuple[int, int, int, int], int], int],
    mock_selectobject: Callable[[int, int], int | None],
) -> None:
    with (
        patch("helpers.DrawTextW", new=mock_drawtextw),
        patch("helpers.win32gui.SelectObject", new=mock_selectobject),
    ):
        # Change flags to see if code still runs without issue
        flags = win32con.DT_CALCRECT | win32con.DT_LEFT
        width, height = measure_text(
            hdc=mock_hdc,
            text="Another test text",
            max_width=300,
            font=mock_font,
            flags=flags,
        )

        # Our mock_drawtextw always sets the same rect,
        # so we still expect the same width/height.
        assert width == 200
        assert height == 40


def test_measure_text_with_font_change(
    mock_hdc: int,
    mock_drawtextw: Callable[[int, int, int, tuple[int, int, int, int], int], int],
) -> None:
    # When font is provided, measure_text selects it and then restores it.
    # We'll ensure SelectObject is called correctly.
    select_calls = []

    def fake_selectobject(hdc: int, obj: int) -> str | None:
        select_calls.append((hdc, obj))
        # On the first call, return something non-None to simulate an old font was replaced
        if len(select_calls) == 1:
            return 123
        return None

    with (
        patch("helpers.DrawTextW", new=mock_drawtextw),
        patch(
            "helpers.win32gui.SelectObject",
            side_effect=fake_selectobject,
        ),
    ):
        width, height = measure_text(
            hdc=mock_hdc,
            text="With font",
            max_width=200,
            font="mock_font_handle",  # Just a dummy
        )

        assert width == 200
        assert height == 40
        # Check that SelectObject was called twice: once to select the font and once to restore
        assert len(select_calls) == 2


def test_measure_text_no_font(
    mock_hdc: int,
    mock_drawtextw: Callable[[int, int, int, tuple[int, int, int, int], int], int],
) -> None:
    # If no font is provided, we should not call SelectObject at all.
    with (
        patch("helpers.DrawTextW", new=mock_drawtextw),
        patch("helpers.win32gui.SelectObject") as mock_select,
    ):
        width, height = measure_text(
            hdc=mock_hdc,
            text="No font scenario",
            max_width=200,
            font=None,
        )

        assert width == 200
        assert height == 40
        mock_select.assert_not_called()
