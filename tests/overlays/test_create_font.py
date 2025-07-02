from unittest.mock import patch

import win32con

from helpers import create_font


def test_create_font_basic() -> None:
    # We'll patch CreateFontIndirect and ensure it is called with correct LOGFONT parameters.
    mock_font_handle = 1234  # A dummy handle representing HFONT

    def fake_createfontindirect(logfont: int) -> int:
        # logfont is a LOGFONT structure. We can check its fields here.
        # For simplicity, just return mock_font_handle.
        return mock_font_handle

    with patch(
        "helpers.win32gui.CreateFontIndirect",
        side_effect=fake_createfontindirect,
    ) as mock_create:
        font_name = "Segoe UI"
        height = 0
        weight = win32con.FW_NORMAL
        italic = False

        hfont = create_font(
            font_name=font_name, height=height, weight=weight, italic=italic
        )
        assert hfont == mock_font_handle

        # Extract the actual LOGFONT struct passed
        call_args = mock_create.call_args[0]
        # call_args[0] should be the LOGFONT structure
        logfont_struct = call_args[0]

        # Validate fields:
        assert logfont_struct.lfFaceName == font_name
        assert logfont_struct.lfHeight == height
        assert logfont_struct.lfWeight == weight
        assert logfont_struct.lfItalic == 0  # since italic=False


def test_create_font_italic() -> None:
    mock_font_handle = 5678

    def fake_createfontindirect(logfont: int) -> int:
        return mock_font_handle

    with patch(
        "helpers.win32gui.CreateFontIndirect",
        side_effect=fake_createfontindirect,
    ) as mock_create:
        font_name = "Arial"
        height = -20
        weight = win32con.FW_BOLD
        italic = True

        hfont = create_font(
            font_name=font_name, height=height, weight=weight, italic=italic
        )
        assert hfont == mock_font_handle

        call_args = mock_create.call_args[0]
        logfont_struct = call_args[0]

        assert logfont_struct.lfFaceName == font_name
        assert logfont_struct.lfHeight == height
        assert logfont_struct.lfWeight == weight
        assert logfont_struct.lfItalic == 1  # since italic=True


def test_create_font_no_face_name() -> None:
    # Test using a default font name if none is given (if that's expected behavior)
    # If the code doesn't handle no face name, skip this test or adapt accordingly.
    mock_font_handle = 9999

    def fake_createfontindirect(logfont: int) -> int:
        return mock_font_handle

    with patch(
        "helpers.win32gui.CreateFontIndirect",
        side_effect=fake_createfontindirect,
    ) as mock_create:
        # Call without specifying font_name, which might default to "Segoe UI" or an empty string
        hfont = create_font()
        assert hfont == mock_font_handle

        call_args = mock_create.call_args[0]
        logfont_struct = call_args[0]

        # Assuming default is "Segoe UI" as coded previously:
        assert logfont_struct.lfFaceName == "Segoe UI"
