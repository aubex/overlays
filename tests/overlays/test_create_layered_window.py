from unittest.mock import patch

import pytest
import win32con

from helpers import create_layered_window, set_layered_window_attributes


@pytest.fixture
def mock_hwnd() -> int:
    # Simulate a valid HWND as a non-zero integer (e.g., 100).
    return 100


def test_create_layered_window_calls_api_with_correct_args(mock_hwnd: int) -> None:
    class_name = "MyTestClass"
    h_instance = 1  # Just a dummy handle value
    x, y, width, height = 50, 100, 300, 200
    ex_style = 0x00080000  # WS_EX_LAYERED as an example
    style = 0x80000000  # WS_POPUP as an example

    with patch(
        "helpers.win32gui.CreateWindowEx",
        return_value=mock_hwnd,
    ) as mock_create:
        hwnd = create_layered_window(
            class_name, h_instance, x, y, width, height, ex_style, style
        )

        # Check that CreateWindowEx was called with the right parameters
        mock_create.assert_called_once_with(
            ex_style,
            class_name,
            "",
            style,
            x,
            y,
            width,
            height,
            None,
            None,
            h_instance,
            None,
        )

        # Check that the returned hwnd matches the mocked return value
        assert hwnd == mock_hwnd


def test_create_layered_window_returns_none_when_api_fails() -> None:
    class_name = "MyFailClass"
    h_instance = 2
    x, y, width, height = 10, 20, 100, 50
    ex_style = 0x00080000
    style = 0x80000000

    with patch(
        "helpers.win32gui.CreateWindowEx",
        return_value=None,
    ) as mock_create:
        hwnd = create_layered_window(
            class_name, h_instance, x, y, width, height, ex_style, style
        )

        # Check if return is None when API fails
        assert hwnd is None
        mock_create.assert_called_once()


def test_set_layered_window_attributes_default_alpha(mock_hwnd: int) -> None:
    # Test with default alpha=230
    with patch(
        "helpers.win32gui.SetLayeredWindowAttributes",
    ) as mock_set_attrs:
        set_layered_window_attributes(mock_hwnd)
        mock_set_attrs.assert_called_once_with(mock_hwnd, 0, 230, win32con.LWA_ALPHA)


def test_set_layered_window_attributes_custom_alpha(mock_hwnd: int) -> None:
    # Test with a custom alpha value
    custom_alpha = 128
    with patch(
        "helpers.win32gui.SetLayeredWindowAttributes",
    ) as mock_set_attrs:
        set_layered_window_attributes(mock_hwnd, alpha=custom_alpha)
        mock_set_attrs.assert_called_once_with(
            mock_hwnd, 0, custom_alpha, win32con.LWA_ALPHA
        )


def test_set_layered_window_attributes_edge_alpha(mock_hwnd: int) -> None:
    # Test an edge case: fully transparent (0) or fully opaque (255)
    with patch(
        "helpers.win32gui.SetLayeredWindowAttributes",
    ) as mock_set_attrs:
        set_layered_window_attributes(mock_hwnd, alpha=0)
        mock_set_attrs.assert_called_once_with(mock_hwnd, 0, 0, win32con.LWA_ALPHA)

    with patch(
        "helpers.win32gui.SetLayeredWindowAttributes",
    ) as mock_set_attrs:
        set_layered_window_attributes(mock_hwnd, alpha=255)
        mock_set_attrs.assert_called_once_with(mock_hwnd, 0, 255, win32con.LWA_ALPHA)
