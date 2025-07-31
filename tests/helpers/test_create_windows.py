import pytest
import win32api
import win32api as _win32api
import win32con
import win32gui
import win32gui as _win32gui

from overlays.helpers import (
    draw_countdown_window,
    draw_qrcode,
)


@pytest.fixture(autouse=True)
def stub_win32(monkeypatch):
    """
    Stub out win32gui, win32api, win32con functions to record calls and provide controlled outputs.
    """
    # State holders for recorded calls
    state = {
        "selected_fonts": [],
        "text_colors": [],
        "bk_modes": [],
        "text_extents": {},
        "fills": [],
        "deleted": [],
        "text_out": [],
    }

    # create_font stub
    monkeypatch.setattr("overlays.helpers.create_font", lambda: "LOGFONT")

    # Font creation and selection
    monkeypatch.setattr(_win32gui, "CreateFontIndirect", lambda lf: 1001)

    def fake_SelectObject(hdc, obj):
        state["selected_fonts"].append((hdc, obj))
        return 2002  # old font handle

    monkeypatch.setattr(_win32gui, "SelectObject", fake_SelectObject)

    # Text and background settings
    monkeypatch.setattr(
        _win32gui,
        "SetTextColor",
        lambda hdc, color: state["text_colors"].append((hdc, color)),
    )
    monkeypatch.setattr(
        _win32gui, "SetBkMode", lambda hdc, mode: state["bk_modes"].append((hdc, mode))
    )

    # Text measurement
    def fake_GetTextExtentPoint32(hdc, text):
        # Return deterministic width/height based on text length
        if text.startswith("Closing in"):
            size = (len(text) * 5, 20)
        else:
            size = (len(text) * 8, 10)
        state["text_extents"][text] = size
        return size

    monkeypatch.setattr(_win32gui, "GetTextExtentPoint32", fake_GetTextExtentPoint32)

    # Brush, FillRect, DeleteObject
    monkeypatch.setattr(_win32gui, "CreateSolidBrush", lambda color: 3003)

    def fake_FillRect(hdc, rect, brush):
        state["fills"].append((hdc, rect, brush))

    monkeypatch.setattr(_win32gui, "FillRect", fake_FillRect)
    monkeypatch.setattr(
        _win32gui, "DeleteObject", lambda obj: state["deleted"].append(obj)
    )

    # Text output
    def fake_ExtTextOut(hdc, x, y, flags, clip, text, op):
        state["text_out"].append((hdc, x, y, flags, text))

    monkeypatch.setattr(_win32gui, "ExtTextOut", fake_ExtTextOut)

    # RGB helper
    monkeypatch.setattr(_win32api, "RGB", lambda r, g, b: (r, g, b))

    yield state


def test_without_remaining(stub_win32):
    state = stub_win32
    # Test data without 'remaining'
    cd = {"message": "Hello"}
    position = (0, 100, 200, 150)
    hdc = 42

    # Call the function
    draw_countdown_window(hdc, cd, position)

    # Verify text extents measured for only the message
    assert "Hello" in state["text_extents"]
    assert len(state["text_extents"]) == 1

    # Compute expected rectangle
    left, top, right, _ = position
    initial_w = right - left
    pad_x, pad_y = (8, 8)
    text_w, text_h = state["text_extents"]["Hello"]
    init_center_x = left + initial_w // 2
    content_half_w = max(initial_w, text_w) // 2
    final_left = init_center_x - content_half_w - pad_x
    final_right = init_center_x + content_half_w + pad_x
    final_top = top - pad_y
    final_bottom = final_top + text_h + 2 * pad_y
    expected_rect = (final_left, final_top, final_right, final_bottom)

    # Check FillRect call
    assert (hdc, expected_rect, 3003) in state["fills"]

    # Check ExtTextOut called once with centered text
    assert len(state["text_out"]) == 1
    call = state["text_out"][0]
    _, x, y, flags, text = call
    assert text == "Hello"
    # y should start at final_top + pad_y
    assert y == final_top + pad_y


def test_with_remaining(stub_win32):
    state = stub_win32
    # Test data with 'remaining'
    cd = {"message": "Wait", "remaining": 5}
    position = (10, 20, 110, 70)
    hdc = 99

    # Call the function
    draw_countdown_window(hdc, cd, position, padding=(5, 5))

    # Verify text extents measured for both lines
    assert "Wait" in state["text_extents"]
    assert "Closing in 5 s" in state["text_extents"]
    assert len(state["text_extents"]) == 2

    # Compute expected rectangle for padding (5,5)
    left, top, right, _ = position
    initial_w = right - left
    pad_x, pad_y = (5, 5)
    sizes = state["text_extents"]
    text_w = max(sizes["Wait"][0], sizes["Closing in 5 s"][0])
    text_h = sizes["Wait"][1] + sizes["Closing in 5 s"][1]
    init_center_x = left + initial_w // 2
    content_half_w = max(initial_w, text_w) // 2
    final_left = init_center_x - content_half_w - pad_x
    final_right = init_center_x + content_half_w + pad_x
    final_top = top - pad_y
    final_bottom = final_top + text_h + 2 * pad_y
    expected_rect = (final_left, final_top, final_right, final_bottom)

    # Check both lines drawn
    assert len(state["text_out"]) == 2
    # Check FillRect
    assert (hdc, expected_rect, 3003) in state["fills"]

    # Ensure cleanup: font handle and brush deleted
    assert 3003 in state["deleted"]  # brush
    assert 1001 in state["deleted"]  # font

    # Ensure font selection restored
    # First selection: select new font, second: restore old font
    assert state["selected_fonts"][0][1] == 1001
    assert state["selected_fonts"][1][1] == 2002


def test_draw_qrcode(monkeypatch):
    """Should draw QR code modules and caption correctly."""
    calls = []

    # Patch brush and pen creation, FillRect, Rectangle, text functions
    def fake_CreateSolidBrush(color):
        calls.append(("CreateSolidBrush", color))
        return "brush"

    def fake_FillRect(hdc, rect, brush):
        calls.append(("FillRect", hdc, rect, brush))

    def fake_CreatePen(style, width, color):
        calls.append(("CreatePen", style, width, color))
        return "pen"

    def fake_SelectObject(hdc, obj):
        calls.append(("SelectObject", hdc, obj))

    def fake_Rectangle(hdc, x0, y0, x1, y1):
        calls.append(("Rectangle", hdc, x0, y0, x1, y1))

    def fake_SetTextColor(hdc, color):
        calls.append(("SetTextColor", hdc, color))

    def fake_SetBkMode(hdc, mode):
        calls.append(("SetBkMode", hdc, mode))

    def fake_DrawText(hdc, text, length, rect, flags):
        calls.append(("DrawText", hdc, text, rect, flags))

    def fake_DeleteObject(obj):
        calls.append(("DeleteObject", obj))

    for mod in [
        "CreateSolidBrush",
        "FillRect",
        "CreatePen",
        "SelectObject",
        "Rectangle",
        "SetTextColor",
        "SetBkMode",
        "DrawText",
        "DeleteObject",
    ]:
        monkeypatch.setattr(
            win32gui,
            mod,
            locals()[f"fake_{mod}" if mod != "Rectangle" else "fake_Rectangle"],
        )
    monkeypatch.setattr(win32api, "RGB", win32api.RGB)

    hdc = 102
    qr_code = {
        "padding": 1,
        "pix_per_mod": 2,
        "matrix": [[1, 0], [0, 1]],
        "caption": "QR",
    }
    size = (0, 0, 6, 6)  # left, top, right, bottom
    draw_qrcode(hdc, qr_code, size)

    # Check background fill
    assert ("CreateSolidBrush", win32api.RGB(255, 255, 255)) in calls
    assert ("FillRect", 102, (-10, -5, 16, 21), "brush") in calls
    assert ("DeleteObject", "brush") in calls

    # Check module draws: two modules for bits==1
    # First module at (left+1, top+1) => (1,1) to (3,3)
    assert ("CreatePen", win32con.PS_SOLID, 0, win32api.RGB(0, 0, 0)) in calls
    assert ("Rectangle", hdc, 1, 1, 3, 3) in calls

    # Check caption draw
    caption_rect = (0, 6 + 5, 6, 6 + 5 + 20)
    assert ("SetTextColor", hdc, win32api.RGB(0, 0, 0)) in calls
    assert ("DrawText", 102, "QR", (-10, 8, 16, 18), 37) in calls
