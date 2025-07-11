import win32gui
import win32con
import win32api
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _win32typing import PyLOGFONT  # type: ignore

BOX_W, BOX_H, GAP, TOP = 300, 80, 10, 20


def draw_highlight_rectangle(hdc: int, rect: dict):
    l, t, r, b = rect["coords"]  # noqa: E741
    cr, cg, cb = rect["color"]

    pen = win32gui.CreatePen(win32con.PS_SOLID, 2, win32api.RGB(cr, cg, cb))
    brush = win32gui.CreateSolidBrush(win32api.RGB(cr, cg, cb))
    oldp = win32gui.SelectObject(hdc, pen)
    oldb = win32gui.SelectObject(hdc, brush)

    win32gui.Rectangle(hdc, l, t, r, b)

    win32gui.SelectObject(hdc, oldp)
    win32gui.SelectObject(hdc, oldb)
    win32gui.DeleteObject(pen)
    win32gui.DeleteObject(brush)


def get_countdown_position(idx: int, full: tuple[int, int, int, int]):
    left = (full[2] - BOX_W) // 2
    top = TOP + idx * (BOX_H + GAP)
    right, bottom = left + BOX_W, top + BOX_H

    return left, top, right, bottom


def get_qrcode_position(
    idx: int, total: int, box_gap: int, top_start: int, full: tuple[int, int, int, int]
):
    left = (full[2] - total) // 2
    top = top_start + idx * (total + box_gap)
    right = left + total
    bottom = top + total
    return left, top, right, bottom


def create_font() -> "PyLOGFONT":
    lf = win32gui.LOGFONT()
    lf.lfHeight = -20
    lf.lfWeight = win32con.FW_NORMAL
    lf.lfCharSet = win32con.ANSI_CHARSET
    lf.lfFaceName = "Segoe UI"
    return lf


def draw_countdown_window(
    hdc: int,
    cd: dict,
    position: tuple[int, int, int, int],
    padding: tuple[int, int] = (8, 8),
):
    left, top, right, bottom = position
    initial_w = right - left
    pad_x, pad_y = padding

    # Build lines
    lines = [cd["message"]]
    if "remaining" in cd:
        lines.append(f"Closing in {cd['remaining']} s")

    # Select font & colors
    lf = create_font()
    font = win32gui.CreateFontIndirect(lf)
    oldf = win32gui.SelectObject(hdc, font)
    win32gui.SetTextColor(hdc, win32api.RGB(0, 0, 128))
    win32gui.SetBkMode(hdc, win32con.TRANSPARENT)

    # Measure each line
    sizes = [win32gui.GetTextExtentPoint32(hdc, line) for line in lines]
    line_widths, line_heights = zip(*sizes)
    text_w = max(line_widths)
    text_h = sum(line_heights)

    # **UPDATED CENTERED BOX CALCULATION**
    init_center_x = left + initial_w // 2
    content_half_w = max(initial_w, text_w) // 2

    final_left = init_center_x - content_half_w - pad_x
    final_right = init_center_x + content_half_w + pad_x
    final_top = top - pad_y
    final_bottom = final_top + text_h + 2 * pad_y
    final_rect = (final_left, final_top, final_right, final_bottom)

    # Paint background
    bg = win32gui.CreateSolidBrush(win32api.RGB(200, 220, 255))
    win32gui.FillRect(hdc, final_rect, bg)
    win32gui.DeleteObject(bg)

    # Draw each line with ExtTextOut, centered
    y = final_top + pad_y
    for line, (w, h) in zip(lines, sizes):
        x = final_left + ((final_right - final_left) - w) // 2
        win32gui.ExtTextOut(hdc, x, y, win32con.ETO_CLIPPED, None, line, None)
        y += h

    # Cleanup
    win32gui.SelectObject(hdc, oldf)
    win32gui.DeleteObject(font)


def draw_qrcode(
    hdc: int,
    qr_code: dict,
    position: tuple[int, int, int, int],
):
    left, top, right, bottom = position
    pad = qr_code["padding"]
    caption = qr_code.get("caption", "")

    # 1) select a known font so measurements are reliable
    font = win32gui.GetStockObject(win32con.DEVICE_DEFAULT_FONT)
    win32gui.SelectObject(hdc, font)

    # 2) measure text size
    txt_w, txt_h = (0, 0)
    if caption:
        txt_w, txt_h = win32gui.GetTextExtentPoint32(hdc, caption)

    qr_width = right - left

    # 2) figure out horizontal expansion
    #    if caption is wider than the QR, we need to grow left/right
    extra = max(0, txt_w - qr_width)
    # split the extra evenly (if odd, right gets the extra pixel)
    left_expansion = extra // 2
    right_expansion = extra - left_expansion

    # 3) add your own margin if you like
    h_margin = 5
    v_margin = 5

    # 3) extend white background to include caption area
    bg_bottom = bottom + (txt_h + h_margin if caption else 0)
    bg_left = left - left_expansion - h_margin
    bg_right = right + right_expansion + h_margin
    bg_brush = win32gui.CreateSolidBrush(win32api.RGB(255, 255, 255))
    win32gui.FillRect(hdc, (bg_left, top - v_margin, bg_right, bg_bottom), bg_brush)
    win32gui.DeleteObject(bg_brush)

    # 4) draw QR modules
    for ry, row in enumerate(qr_code["matrix"]):
        for cx, bit in enumerate(row):
            if not bit:
                continue
            x0 = left + pad + cx * qr_code["pix_per_mod"]
            y0 = top + pad + ry * qr_code["pix_per_mod"]
            x1 = x0 + qr_code["pix_per_mod"]
            y1 = y0 + qr_code["pix_per_mod"]
            pen = win32gui.CreatePen(win32con.PS_SOLID, 0, win32api.RGB(0, 0, 0))
            brush = win32gui.CreateSolidBrush(win32api.RGB(0, 0, 0))
            win32gui.SelectObject(hdc, pen)
            win32gui.SelectObject(hdc, brush)
            win32gui.Rectangle(hdc, x0, y0, x1, y1)
            win32gui.DeleteObject(pen)
            win32gui.DeleteObject(brush)

    # 5) draw caption inside the white box, centered
    if caption:
        caption_top = bottom + (v_margin // 2)
        caption_rect = (bg_left, caption_top, bg_right, caption_top + txt_h)
        win32gui.SetTextColor(hdc, win32api.RGB(0, 0, 0))
        win32gui.SetBkMode(hdc, win32con.TRANSPARENT)
        win32gui.DrawText(
            hdc,
            caption,
            -1,
            caption_rect,
            win32con.DT_CENTER | win32con.DT_SINGLELINE | win32con.DT_VCENTER,
        )
