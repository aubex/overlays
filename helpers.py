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


def get_countdown_size(idx: int, full: tuple[int, int, int, int]):
    left = (full[2] - BOX_W) // 2
    top = TOP + idx * (BOX_H + GAP)
    right, bottom = left + BOX_W, top + BOX_H

    return left, top, right, bottom


def get_qrcode_size(
    idx: int, total: int, box_gap: int, top_start: int, full: tuple[int, int, int, int]
):
    left = (full[2] - total) // 2
    top = top_start + idx * (total + box_gap)
    right = left + total
    bottom = top + total
    return left, top, right, bottom


def draw_countdown_rectangle(hdc: int, size: tuple[int, int, int, int]):
    left, top, right, bottom = size
    bg = win32gui.CreateSolidBrush(win32api.RGB(200, 220, 255))
    win32gui.FillRect(hdc, (left, top, right, bottom), bg)
    win32gui.DeleteObject(bg)


def create_font() -> "PyLOGFONT":
    lf = win32gui.LOGFONT()
    lf.lfHeight = -22
    lf.lfWeight = win32con.FW_NORMAL
    lf.lfCharSet = win32con.ANSI_CHARSET
    lf.lfFaceName = "Segoe UI"
    return lf


def draw_countdown_message(hdc: int, cd: dict, size: tuple[int, int, int, int]):
    left, top, right, bottom = size
    msg = f"{cd['message']}"
    if "remaining" in cd:
        msg += f"\nClosing in {cd['remaining']} s"
    lf = create_font()
    f2 = win32gui.CreateFontIndirect(lf)
    oldf = win32gui.SelectObject(hdc, f2)
    win32gui.SetTextColor(hdc, win32api.RGB(0, 0, 128))
    win32gui.SetBkMode(hdc, win32con.TRANSPARENT)
    win32gui.DrawText(
        hdc,
        msg,
        -1,
        (left, top, right, bottom),
        win32con.DT_CENTER | win32con.DT_VCENTER | win32con.DT_WORDBREAK,
    )
    win32gui.SelectObject(hdc, oldf)
    win32gui.DeleteObject(f2)


def draw_qrcode(
    hdc: int,
    qr_code: dict,
    size: tuple[int, int, int, int],
):
    left, top, right, bottom = size
    pad = qr_code["padding"]

    # white background box
    bg = win32gui.CreateSolidBrush(win32api.RGB(255, 255, 255))
    win32gui.FillRect(hdc, (left, top, right, bottom), bg)
    win32gui.DeleteObject(bg)

    # draw each black module
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

    # draw optional caption beneath the QR code
    if qr_code["caption"]:
        caption_rect = (left, bottom + 5, right, bottom + 5 + 20)
        win32gui.SetTextColor(hdc, win32api.RGB(0, 0, 0))
        win32gui.SetBkMode(hdc, win32con.TRANSPARENT)
        win32gui.DrawText(
            hdc,
            qr_code["caption"],
            -1,
            caption_rect,
            win32con.DT_CENTER | win32con.DT_VCENTER,
        )
