import win32con
import win32gui

from overlays.helpers import create_font


def test_create_font_returns_logfont_instance():
    """create_font should return the same type as win32gui.LOGFONT()."""
    font = create_font()
    # win32gui.LOGFONT() may return a factory struct, so use its type for isinstance
    expected_type = type(win32gui.LOGFONT())
    assert isinstance(font, expected_type), (
        f"Expected LOGFONT instance of type {expected_type!r}, got {type(font)!r}"
    )


def test_create_font_attributes():
    """The LOGFONT returned by create_font should have the correct default attributes."""
    font = create_font()
    assert font.lfHeight == -20, f"Expected lfHeight -22, got {font.lfHeight}"
    assert font.lfWeight == win32con.FW_NORMAL, (
        f"Expected lfWeight FW_NORMAL, got {font.lfWeight}"
    )
    assert font.lfCharSet == win32con.ANSI_CHARSET, (
        f"Expected lfCharSet ANSI_CHARSET, got {font.lfCharSet}"
    )
    assert font.lfFaceName == "Segoe UI", (
        f"Expected lfFaceName 'Segoe UI', got {font.lfFaceName}"
    )


def test_create_font_returns_fresh_instances():
    """Each call to create_font should return a new, independent LOGFONT instance."""
    font1 = create_font()
    font2 = create_font()
    # Modify one instance and ensure the other is unaffected
    font1.lfHeight = -30
    assert font2.lfHeight == -20, (
        "Expected second instance lfHeight to remain -22 after modifying the first instance."
    )
