from unittest.mock import patch

import pytest

# Assume GDIContext is defined as:
from helpers import GDIContext


@pytest.fixture
def mock_hdc() -> int:
    return 1  # A dummy HDC handle


@pytest.fixture
def pen_handle() -> int:
    return 101


@pytest.fixture
def brush_handle() -> int:
    return 202


@pytest.fixture
def font_handle() -> int:
    return 303


@pytest.fixture
def old_pen_handle() -> int:
    return 999


@pytest.fixture
def old_brush_handle() -> int:
    return 888


@pytest.fixture
def old_font_handle() -> int:
    return 777


def test_gdi_context_no_objects(mock_hdc: int) -> None:
    # No pen, brush, or font provided
    # Should not call SelectObject or DeleteObject at all
    with (
        patch("helpers.win32gui.SelectObject") as mock_select,
        patch("helpers.win32gui.DeleteObject") as mock_delete,
    ):
        with GDIContext(mock_hdc):
            pass

        mock_select.assert_not_called()
        mock_delete.assert_not_called()


def test_gdi_context_with_pen_only(
    mock_hdc: int, pen_handle: int, old_pen_handle: int
) -> None:
    # Only a pen is provided
    # On enter: SelectObject(hdc, pen) returns old_pen
    # On exit: restore old_pen, delete pen
    def fake_selectobject(hdc: int, obj: int) -> int | None:
        # If selecting pen returns old_pen
        return old_pen_handle if obj == pen_handle else None

    with (
        patch(
            "helpers.win32gui.SelectObject",
            side_effect=fake_selectobject,
        ) as mock_select,
        patch("helpers.win32gui.DeleteObject") as mock_delete,
    ):
        with GDIContext(mock_hdc, pen=pen_handle):
            # Inside the context, pen is selected
            pass

        # On enter, one SelectObject call
        # On exit, one SelectObject (restore) + one DeleteObject
        assert mock_select.call_count == 2
        assert mock_delete.call_count == 1
        mock_delete.assert_called_with(pen_handle)


def test_gdi_context_with_brush_and_font(
    mock_hdc: int,
    brush_handle: int,
    font_handle: int,
    old_brush_handle: int,
    old_font_handle: int,
) -> None:
    def fake_selectobject(hdc: int, obj: int) -> int | None:
        if obj == brush_handle:
            return old_brush_handle
        if obj == font_handle:
            return old_font_handle
        return None

    with (
        patch(
            "helpers.win32gui.SelectObject",
            side_effect=fake_selectobject,
        ) as mock_select,
        patch("helpers.win32gui.DeleteObject") as mock_delete,
    ):
        with GDIContext(mock_hdc, brush=brush_handle, font=font_handle):
            # Inside context, brush and font selected
            pass

        # Enter: 2 SelectObject calls (for brush and font)
        # Exit: 2 SelectObject calls to restore old brush and font, and 2 DeleteObject calls
        assert mock_select.call_count == 4
        assert mock_delete.call_count == 2
        mock_delete.assert_any_call(brush_handle)
        mock_delete.assert_any_call(font_handle)


def test_gdi_context_all_three_objects(  # noqa: PLR0913
    mock_hdc: int,
    pen_handle: int,
    brush_handle: int,
    font_handle: int,
    old_pen_handle: int,
    old_brush_handle: int,
    old_font_handle: int,
) -> None:
    # Provide pen, brush, and font
    # On enter, select each and store old objects
    # On exit, restore and delete them all
    def fake_selectobject(hdc: int, obj: int) -> int:
        if obj == pen_handle:
            return old_pen_handle
        if obj == brush_handle:
            return old_brush_handle
        if obj == font_handle:
            return old_font_handle
        return None

    with (
        patch(
            "helpers.win32gui.SelectObject",
            side_effect=fake_selectobject,
        ) as mock_select,
        patch("helpers.win32gui.DeleteObject") as mock_delete,
    ):
        with GDIContext(mock_hdc, pen=pen_handle, brush=brush_handle, font=font_handle):
            pass

        # Enter: 3 SelectObject calls total
        # Exit: 3 SelectObject calls to restore old objects, 3 DeleteObject calls
        assert mock_select.call_count == 6
        assert mock_delete.call_count == 3
        mock_delete.assert_any_call(pen_handle)
        mock_delete.assert_any_call(brush_handle)
        mock_delete.assert_any_call(font_handle)


def test_gdi_context_no_old_objects(mock_hdc: int, brush_handle: int) -> int:
    # If SelectObject returns None, means no old object was present.
    # Still, we should delete the provided object on exit if provided.
    def fake_selectobject(hdc: int, obj: int) -> None:
        return None

    with (
        patch(
            "helpers.win32gui.SelectObject",
            side_effect=fake_selectobject,
        ) as mock_select,
        patch("helpers.win32gui.DeleteObject") as mock_delete,
    ):
        with GDIContext(mock_hdc, brush=brush_handle):
            pass

        # Enter: 1 SelectObject call for brush
        # Exit: Since old_brush is None, we won't restore it, but we still
        # DeleteObject(brush_handle). This implies on exit we do not call
        # SelectObject for the brush again since old_brush is None.
        # So total: Enter = 1 call, Exit = 1 DeleteObject call, no restore call
        assert mock_select.call_count == 1
        assert mock_delete.call_count == 1
        mock_delete.assert_called_with(brush_handle)
