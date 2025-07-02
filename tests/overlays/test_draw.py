from unittest.mock import patch

import pytest
import win32api
import win32con

from helpers import draw_centered_text, draw_colored_background


@pytest.fixture
def mock_hdc() -> int:
    # A mock handle to a device context
    return 1


@pytest.fixture
def test_rect() -> tuple[int, int, int, int]:
    # A sample rectangle (left, top, right, bottom)
    return (0, 0, 200, 100)


def test_draw_colored_background(
    mock_hdc: int, test_rect: tuple[int, int, int, int]
) -> int:
    # We'll mock CreateSolidBrush, FillRect, and DeleteObject
    # to ensure they're called with expected parameters.
    mock_brush = 999  # Dummy brush handle

    with (
        patch(
            "helpers.win32gui.CreateSolidBrush",
            return_value=mock_brush,
        ) as mock_create_brush,
        patch("helpers.win32gui.FillRect") as mock_fill_rect,
        patch("helpers.win32gui.DeleteObject") as mock_delete_object,
    ):
        r, g, b = 200, 220, 255
        draw_colored_background(mock_hdc, test_rect, r, g, b)

        # Verify CreateSolidBrush was called with the correct RGB value
        expected_color = win32api.RGB(r, g, b)
        mock_create_brush.assert_called_once_with(expected_color)

        # Verify FillRect was called with hdc, rect, and brush
        mock_fill_rect.assert_called_once_with(mock_hdc, test_rect, mock_brush)

        # Verify DeleteObject was called to clean up the brush
        mock_delete_object.assert_called_once_with(mock_brush)


def test_draw_centered_text(mock_hdc: int, test_rect: tuple[int, int, int, int]) -> int:
    # For draw_centered_text, we need to mock DrawTextW, SetTextColor, SetBkMode.
    # We'll ensure they're called correctly and in the correct order.
    text = "Hello World!"
    text_color = (0, 128, 128)  # teal
    flags = win32con.DT_CENTER | win32con.DT_VCENTER | win32con.DT_WORDBREAK

    # Mock DrawTextW
    def fake_drawtextw(
        hdc: int, text_ptr: int, text_len: int, rect_ptr: int, dw_flags: int
    ) -> int:
        # Just return a success indicator
        return 1

    with (
        patch(
            "helpers.DrawTextW",
            side_effect=fake_drawtextw,
        ) as mock_drawtext,
        patch("helpers.win32gui.SetTextColor") as mock_set_text_color,
        patch("helpers.win32gui.SetBkMode") as mock_set_bk_mode,
    ):
        draw_centered_text(
            mock_hdc, test_rect, text, text_color=text_color, flags=flags
        )

        # Check that SetTextColor and SetBkMode were called
        expected_text_color = win32api.RGB(*text_color)
        mock_set_text_color.assert_called_once_with(mock_hdc, expected_text_color)
        mock_set_bk_mode.assert_called_once_with(mock_hdc, win32con.TRANSPARENT)

        # Check DrawTextW call
        # DrawTextW expects rect as a ctypes array; we just ensure the call was made.
        # mock_drawtext is patched so we can verify it was called.
        # We do not easily verify the rect array content directly, but we know the text and flags.
        calls = mock_drawtext.mock_calls
        assert len(calls) == 1
        # The call arguments: (hdc, text, length, rect_ptr, flags)
        # text is passed as LPCWSTR, and length as -1. Check the text and flags:
        # The exact rect_ptr verification is tricky, but we trust the function for now.
        _, draw_args, _ = calls[0]
        # draw_args should be (hdc, text, -1, rect_ptr, flags)
        # hdc:
        assert draw_args[0] == mock_hdc
        # text_ptr: we passed text as a string, the ctypes call should see it as text_ptr,
        # checking only flags and len:
        assert draw_args[2] == -1
        assert draw_args[4] == flags
        # We won't decode rect_ptr deeply, just trust our function passed it correctly.
