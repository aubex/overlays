import ctypes
from ctypes import wintypes
from types import TracebackType

import win32api
import win32con
import win32gui

# Use a shared DrawTextW setup:
DrawTextW = ctypes.windll.user32.DrawTextW
DrawTextW.argtypes = [
    wintypes.HDC,
    wintypes.LPCWSTR,
    ctypes.c_int,
    ctypes.POINTER(
        ctypes.c_long * 4
    ),  # We can pass (left, top, right, bottom) as an array
    ctypes.c_uint,
]
DrawTextW.restype = ctypes.c_int


def measure_text(
    hdc: wintypes.HDC,
    text: str,
    max_width: int,
    font: wintypes.HFONT | None = None,
    flags: int = win32con.DT_CALCRECT | win32con.DT_WORDBREAK | win32con.DT_CENTER,
) -> tuple[int, int]:
    """
    Measures the dimensions required to render text with word wrapping.

    Uses the Windows DrawTextW API to calculate the width and height needed to
    display the specified text within a given maximum width, applying word
    wrapping as needed.

    Args:
        hdc (wintypes.HDC): Handle to the device context for rendering.
        text (str): The text to measure.
        max_width (int): Maximum width in pixels to constrain the text.
        font (Optional[wintypes.HFONT]): Handle to font object to use for measurement.
            If None, uses the currently selected font in the device context.
            Defaults to None.
        flags (int): Combination of DrawText formatting flags from win32con.
            Defaults to DT_CALCRECT | DT_WORDBREAK | DT_CENTER.

    Returns:
        Tuple[int, int]: A tuple containing (width, height) in pixels required
            to render the text.

    """
    old_font = None
    if font:
        old_font = win32gui.SelectObject(hdc, font)
    rect = (0, 0, max_width, 0)
    rect_array = (ctypes.c_long * 4)(*rect)
    DrawTextW(hdc, text, -1, rect_array, flags)
    if font and old_font:
        win32gui.SelectObject(hdc, old_font)
    width = rect_array[2] - rect_array[0]
    height = rect_array[3] - rect_array[1]
    return width, height


def create_layered_window(  # noqa: PLR0913
    class_name: str,
    h_instance: wintypes.HINSTANCE,
    x: int,
    y: int,
    width: int,
    height: int,
    ex_style: int,
    style: int,
) -> wintypes.HWND:
    """
    Creates a layered, topmost window with specified parameters.

    Uses the Windows CreateWindowEx API to create a window with the given
    geometry and style attributes. Typically used for creating layered
    windows (with WS_EX_LAYERED extended style) that can support per-pixel
    alpha blending.

    Args:
        class_name (str): The registered window class name, previously registered
            via RegisterClass.
        h_instance (wintypes.HINSTANCE): Handle to the instance of the module
            to be associated with the window.
        x (int): Initial x-coordinate of the window's top-left corner in pixels.
        y (int): Initial y-coordinate of the window's top-left corner in pixels.
        width (int): Width of the window in pixels.
        height (int): Height of the window in pixels.
        ex_style (int): Extended window style flags (e.g., win32con.WS_EX_LAYERED
            for layered windows).
        style (int): Window style flags (e.g., win32con.WS_POPUP for a popup window).

    Returns:
        wintypes.HWND: Handle to the newly created window.

    """
    hwnd: wintypes.HWND = win32gui.CreateWindowEx(
        ex_style,
        class_name,
        "",
        style,
        x,
        y,
        width,
        height,
        None,  # No parent window
        None,  # No menu
        h_instance,
        None,  # No extra creation data
    )
    return hwnd


def set_layered_window_attributes(
    hwnd: wintypes.HWND,
    alpha: int = 230,
) -> None:
    """
    Sets the transparency level for a layered window.

    Applies an alpha transparency effect to a window that has the WS_EX_LAYERED
    extended style. Uses the Windows SetLayeredWindowAttributes API to control
    the window's opacity.

    Args:
        hwnd (wintypes.HWND): Handle to the window to modify. The window must
            have been created with the WS_EX_LAYERED extended style.
        alpha (int): Alpha transparency value, ranging from 0 (fully transparent)
            to 255 (fully opaque). Defaults to 230.

    Returns:
        None

    """
    win32gui.SetLayeredWindowAttributes(hwnd, 0, alpha, win32con.LWA_ALPHA)


def draw_colored_background(
    hdc: wintypes.HDC,
    rect: tuple[int, int, int, int],
    r: int,
    g: int,
    b: int,
) -> None:
    """
    Fills a specified rectangle with a solid RGB color.

    Creates a solid brush with the given RGB values and uses it to fill the
    provided rectangle in the specified device context. The brush is cleaned
    up after use.

    Args:
        hdc (wintypes.HDC): Handle to the device context where the rectangle
            will be drawn.
        rect (Tuple[int, int, int, int]): A tuple of (left, top, right, bottom)
            coordinates in pixels defining the rectangle to fill.
        r (int): Red component of the color (0-255).
        g (int): Green component of the color (0-255).
        b (int): Blue component of the color (0-255).

    Returns:
        None

    """
    brush: wintypes.HBRUSH = win32gui.CreateSolidBrush(win32api.RGB(r, g, b))
    win32gui.FillRect(hdc, rect, brush)
    win32gui.DeleteObject(brush)


def draw_centered_text(
    hdc: wintypes.HDC,
    rect: tuple[int, int, int, int],
    text: str,
    text_color: tuple[int, int, int] = (0, 0, 128),
    flags: int = win32con.DT_CENTER | win32con.DT_VCENTER | win32con.DT_WORDBREAK,
) -> None:
    """
    Draws text centered within a specified rectangle.

    Renders the given text in the provided device context, centered both
    horizontally and vertically within the rectangle, with optional word
    breaking. Sets the text color and uses a transparent background.

    Args:
        hdc (wintypes.HDC): Handle to the device context where the text will be drawn.
        rect (Tuple[int, int, int, int]): A tuple of (left, top, right, bottom)
            coordinates in pixels defining the bounding rectangle.
        text (str): The text string to render.
        text_color (Tuple[int, int, int]): RGB color tuple for the text, with each
            component in range 0-255. Defaults to (0, 0, 128) (dark blue).
        flags (int): Combination of DrawText formatting flags from win32con.
            Defaults to DT_CENTER | DT_VCENTER | DT_WORDBREAK.

    Returns:
        None

    """
    win32gui.SetTextColor(hdc, win32api.RGB(*text_color))
    win32gui.SetBkMode(hdc, win32con.TRANSPARENT)
    rect_array = (ctypes.c_long * 4)(*rect)
    DrawTextW(hdc, text, -1, rect_array, flags)


class GDIContext:
    """
    Context manager for temporary GDI object selection.

    Manages the selection of GDI objects (pen, brush, font) into a device context,
    ensuring that original objects are restored and temporary objects are deleted
    upon exit. Useful for scoped painting operations in Windows GDI.

    Attributes:
        hdc (wintypes.HDC): The device context handle to operate on.
        pen (wintypes.HPEN | None): Pen object to select, if any.
        brush (wintypes.HBRUSH | None): Brush object to select, if any.
        font (wintypes.HFONT | None): Font object to select, if any.
        old_pen (wintypes.HPEN | None): Original pen, saved for restoration.
        old_brush (wintypes.HBRUSH | None): Original brush, saved for restoration.
        old_font (wintypes.HFONT | None): Original font, saved for restoration.

    """

    def __init__(
        self,
        hdc: wintypes.HDC,
        pen: wintypes.HPEN | None = None,
        brush: wintypes.HBRUSH | None = None,
        font: wintypes.HFONT | None = None,
    ) -> None:
        """
        Initializes the GDI context manager.

        Args:
            hdc (wintypes.HDC): Handle to the device context to manage.
            pen (wintypes.HPEN | None): Pen handle to select into the DC.
                Defaults to None.
            brush (wintypes.HBRUSH | None): Brush handle to select into the DC.
                Defaults to None.
            font (wintypes.HFONT | None): Font handle to select into the DC.
                Defaults to None.

        """
        self.hdc: wintypes.HDC = hdc
        self.pen: wintypes.HPEN | None = pen
        self.brush: wintypes.HBRUSH | None = brush
        self.font: wintypes.HFONT | None = font
        self.old_pen: wintypes.HPEN | None = None
        self.old_brush: wintypes.HBRUSH | None = None
        self.old_font: wintypes.HFONT | None = None

    def __enter__(self) -> "GDIContext":
        """
        Selects GDI objects into the device context.

        Returns:
            GDIContext: The context manager instance itself.

        """
        if self.pen:
            self.old_pen = win32gui.SelectObject(self.hdc, self.pen)
        if self.brush:
            self.old_brush = win32gui.SelectObject(self.hdc, self.brush)
        if self.font:
            self.old_font = win32gui.SelectObject(self.hdc, self.font)
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: TracebackType | None,
    ) -> None:
        """
        Restores original GDI objects and cleans up.

        Restores the original pen, brush, and font to the device context if they
        were replaced, and deletes the temporary objects passed to the context.

        Args:
            _exc_type (type[BaseException] | None): Exception type, if an exception occurred.
            _exc_val (BaseException | None): Exception value, if an exception occurred.
            _exc_tb (TracebackType | None): Traceback, if an exception occurred.

        """
        # For pen:
        if self.pen:
            # Restore old if present
            if self.old_pen is not None:
                win32gui.SelectObject(self.hdc, self.old_pen)
            # Always delete the pen we created/selected
            win32gui.DeleteObject(self.pen)

        # Similarly for brush and font:
        if self.brush:
            if self.old_brush is not None:
                win32gui.SelectObject(self.hdc, self.old_brush)
            win32gui.DeleteObject(self.brush)

        if self.font:
            if self.old_font is not None:
                win32gui.SelectObject(self.hdc, self.old_font)
            win32gui.DeleteObject(self.font)


def create_font(
    font_name: str = "Segoe UI",
    height: int = 0,
    weight: int = win32con.FW_NORMAL,
    *,
    italic: bool = False,
) -> wintypes.HFONT | None:
    """
    Creates a font object for custom text rendering.

    Constructs a LOGFONT structure with the specified parameters and uses it to
    create a Windows font handle (HFONT) via CreateFontIndirect. Suitable for
    use in GDI text rendering operations.

    Args:
        font_name (str): Name of the font face (e.g., "Segoe UI", "Arial").
            Defaults to "Segoe UI".
        height (int): Font height in logical units. If positive, specifies the
            cell height; if negative, specifies the character height; if 0,
            uses the default height from the system. Defaults to 0.
        weight (int): Font weight, typically from win32con (e.g., FW_NORMAL=400,
            FW_BOLD=700). Defaults to win32con.FW_NORMAL.
        italic (bool): Whether the font should be italicized. Defaults to False.

    Returns:
        Optional[wintypes.HFONT]: Handle to the created font object, or None if
            the creation fails.

    """
    # Define LOGFONT structure
    LogFont = [  # noqa: N806
        ("lfHeight", ctypes.c_long),
        ("lfWidth", ctypes.c_long),
        ("lfEscapement", ctypes.c_long),
        ("lfOrientation", ctypes.c_long),
        ("lfWeight", ctypes.c_long),
        ("lfItalic", ctypes.c_byte),
        ("lfUnderline", ctypes.c_byte),
        ("lfStrikeOut", ctypes.c_byte),
        ("lfCharSet", ctypes.c_byte),
        ("lfOutPrecision", ctypes.c_byte),
        ("lfClipPrecision", ctypes.c_byte),
        ("lfQuality", ctypes.c_byte),
        ("lfPitchAndFamily", ctypes.c_byte),
        ("lfFaceName", wintypes.WCHAR * 32),
    ]

    class LogFontStruct(ctypes.Structure):
        _fields_ = LogFont

    # Initialize LOGFONT instance
    lf = LogFontStruct()
    lf.lfHeight = height
    lf.lfWeight = weight
    lf.lfItalic = 1 if italic else 0
    lf.lfCharSet = win32con.DEFAULT_CHARSET
    lf.lfOutPrecision = win32con.OUT_DEFAULT_PRECIS
    lf.lfClipPrecision = win32con.CLIP_DEFAULT_PRECIS
    lf.lfQuality = win32con.DEFAULT_QUALITY
    lf.lfPitchAndFamily = win32con.DEFAULT_PITCH | win32con.FF_DONTCARE
    lf.lfFaceName = font_name

    return win32gui.CreateFontIndirect(lf)
