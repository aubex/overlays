#[cfg(not(windows))]
compile_error!("The UI module is Windows-only.");

use std::ffi::OsStr;
use std::mem::MaybeUninit;
use std::os::windows::ffi::OsStrExt;
use std::sync::{Arc, Mutex, mpsc};
use std::thread::{self, JoinHandle};

use windows::Win32::Foundation::{
    COLORREF, ERROR_CLASS_ALREADY_EXISTS, HINSTANCE, HWND, LPARAM, LRESULT, RECT, WPARAM,
};
use windows::Win32::Graphics::Gdi::{
    ANSI_CHARSET, BeginPaint, CreateFontIndirectW, CreatePen, CreateSolidBrush,
    DEVICE_DEFAULT_FONT, DeleteObject, DrawTextW, EndPaint, FW_NORMAL, FillRect, GetStockObject,
    GetTextExtentPoint32W, HBRUSH, HDC, HFONT, HGDIOBJ, InvalidateRect, LOGFONTW, PAINTSTRUCT,
    PS_SOLID, Rectangle, SelectObject, SetBkMode, SetTextColor, TRANSPARENT, TextOutW,
    UpdateWindow,
};
use windows::Win32::UI::WindowsAndMessaging::{
    CS_HREDRAW, CS_VREDRAW, CreateWindowExW, DefWindowProcW, DestroyWindow, DispatchMessageW,
    GWLP_USERDATA, GetClientRect, GetMessageW, GetSystemMetrics, GetWindowLongPtrW, IDC_ARROW,
    LoadCursorW, MSG, PostMessageW, PostQuitMessage, RegisterClassW, SM_CXSCREEN, SM_CYSCREEN,
    SW_SHOW, SetLayeredWindowAttributes, SetWindowLongPtrW, ShowWindow, TranslateMessage,
    WINDOW_EX_STYLE, WINDOW_STYLE, WM_APP, WM_CLOSE, WM_DESTROY, WM_KEYDOWN, WM_PAINT, WNDCLASSW,
    WS_EX_LAYERED, WS_EX_TOOLWINDOW, WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_POPUP,
};
use windows::core::PCWSTR;

use crate::render::{
    TextSize, countdown_box_rect, countdown_lines, get_countdown_position, get_qrcode_position,
    qr_top_start, qrcode_background_rect, qrcode_caption_rect,
};
use crate::state::{CountdownSnapshot, HighlightSnapshot, OverlaySnapshot, QrCodeSnapshot};

const WINDOW_CLASS_NAME: &str = "TransparentOverlayWindow";
const WINDOW_TITLE: &str = "Overlay";
const WM_APP_SNAPSHOT: u32 = WM_APP + 1;

#[derive(Debug, Clone)]
pub struct UiBridge {
    hwnd_raw: isize,
    shared_snapshot: Arc<Mutex<OverlaySnapshot>>,
}

impl UiBridge {
    fn hwnd(&self) -> HWND {
        HWND(self.hwnd_raw as _)
    }

    pub fn replace_snapshot(&self, snapshot: OverlaySnapshot) {
        if let Ok(mut shared_snapshot) = self.shared_snapshot.lock() {
            *shared_snapshot = snapshot;
        }
        unsafe {
            let _ = PostMessageW(Some(self.hwnd()), WM_APP_SNAPSHOT, WPARAM(0), LPARAM(0));
        }
    }

    pub fn shutdown(&self) {
        unsafe {
            let _ = PostMessageW(Some(self.hwnd()), WM_CLOSE, WPARAM(0), LPARAM(0));
        }
    }
}

pub struct UiRuntime {
    bridge: UiBridge,
    join_handle: Option<JoinHandle<()>>,
}

impl UiRuntime {
    pub fn bridge(&self) -> UiBridge {
        self.bridge.clone()
    }

    pub fn shutdown(&mut self) {
        self.bridge.shutdown();
        if let Some(join_handle) = self.join_handle.take() {
            let _ = join_handle.join();
        }
    }
}

pub fn spawn_ui_thread() -> Result<UiRuntime, String> {
    let shared_snapshot = Arc::new(Mutex::new(OverlaySnapshot::default()));
    let (ready_tx, ready_rx) = mpsc::channel();
    let state_for_thread = shared_snapshot.clone();

    let join_handle = thread::spawn(move || {
        unsafe { ui_thread_main(state_for_thread, ready_tx) };
    });

    let hwnd_raw = ready_rx
        .recv()
        .map_err(|_| "UI thread failed before reporting readiness".to_string())??;

    Ok(UiRuntime {
        bridge: UiBridge {
            hwnd_raw,
            shared_snapshot,
        },
        join_handle: Some(join_handle),
    })
}

unsafe fn ui_thread_main(
    shared_snapshot: Arc<Mutex<OverlaySnapshot>>,
    ready_tx: mpsc::Sender<Result<isize, String>>,
) {
    let class_name = to_wide(WINDOW_CLASS_NAME);
    let title = to_wide(WINDOW_TITLE);
    let instance = HINSTANCE::default();
    let cursor = match LoadCursorW(None, IDC_ARROW) {
        Ok(cursor) => cursor,
        Err(err) => {
            let _ = ready_tx.send(Err(err.to_string()));
            return;
        }
    };

    let window_class = WNDCLASSW {
        style: CS_HREDRAW | CS_VREDRAW,
        hCursor: cursor,
        hInstance: instance,
        lpszClassName: PCWSTR(class_name.as_ptr()),
        lpfnWndProc: Some(window_proc),
        hbrBackground: HBRUSH::default(),
        ..Default::default()
    };
    let atom = RegisterClassW(&window_class);
    if atom == 0 && windows::Win32::Foundation::GetLastError() != ERROR_CLASS_ALREADY_EXISTS {
        let _ = ready_tx.send(Err("Failed to register window class".to_string()));
        return;
    }

    let screen_width = GetSystemMetrics(SM_CXSCREEN);
    let screen_height = GetSystemMetrics(SM_CYSCREEN);

    let hwnd = match CreateWindowExW(
        WINDOW_EX_STYLE(
            WS_EX_LAYERED.0 | WS_EX_TRANSPARENT.0 | WS_EX_TOPMOST.0 | WS_EX_TOOLWINDOW.0,
        ),
        PCWSTR(class_name.as_ptr()),
        PCWSTR(title.as_ptr()),
        WINDOW_STYLE(WS_POPUP.0),
        0,
        0,
        screen_width,
        screen_height,
        None,
        None,
        Some(instance),
        None,
    ) {
        Ok(hwnd) => hwnd,
        Err(err) => {
            let _ = ready_tx.send(Err(err.to_string()));
            return;
        }
    };

    let transparent_key = rgb(255, 0, 255);
    let _ = SetWindowLongPtrW(
        hwnd,
        GWLP_USERDATA,
        Box::into_raw(Box::new(WindowState {
            shared_snapshot,
            current_snapshot: OverlaySnapshot::default(),
            transparent_key,
        })) as isize,
    );

    if let Err(err) = SetLayeredWindowAttributes(
        hwnd,
        transparent_key,
        200,
        windows::Win32::UI::WindowsAndMessaging::LWA_COLORKEY
            | windows::Win32::UI::WindowsAndMessaging::LWA_ALPHA,
    ) {
        let _ = ready_tx.send(Err(err.to_string()));
        return;
    }

    let _ = ShowWindow(hwnd, SW_SHOW);
    let _ = UpdateWindow(hwnd);
    let _ = ready_tx.send(Ok(hwnd.0 as isize));

    let mut message = MSG::default();
    while GetMessageW(&mut message, None, 0, 0).into() {
        let _ = TranslateMessage(&message);
        DispatchMessageW(&message);
    }
}

struct WindowState {
    shared_snapshot: Arc<Mutex<OverlaySnapshot>>,
    current_snapshot: OverlaySnapshot,
    transparent_key: COLORREF,
}

unsafe extern "system" fn window_proc(
    hwnd: HWND,
    message: u32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    match message {
        WM_APP_SNAPSHOT => {
            if let Some(state) = window_state_mut(hwnd) {
                if let Ok(snapshot) = state.shared_snapshot.lock() {
                    state.current_snapshot = snapshot.clone();
                }
                let _ = InvalidateRect(Some(hwnd), None, true);
            }
            LRESULT(0)
        }
        WM_PAINT => {
            on_paint(hwnd);
            LRESULT(0)
        }
        WM_KEYDOWN if wparam.0 as u32 == 0x1B => {
            let _ = DestroyWindow(hwnd);
            LRESULT(0)
        }
        WM_CLOSE => {
            let _ = DestroyWindow(hwnd);
            LRESULT(0)
        }
        WM_DESTROY => {
            if let Some(state) = window_state_ptr(hwnd) {
                drop(Box::from_raw(state));
                let _ = SetWindowLongPtrW(hwnd, GWLP_USERDATA, 0);
            }
            PostQuitMessage(0);
            LRESULT(0)
        }
        _ => DefWindowProcW(hwnd, message, wparam, lparam),
    }
}

unsafe fn on_paint(hwnd: HWND) {
    let mut paint = PAINTSTRUCT::default();
    let hdc = BeginPaint(hwnd, &mut paint);
    if hdc.0.is_null() {
        return;
    }

    let mut rect = RECT::default();
    let _ = GetClientRect(hwnd, &mut rect);
    if let Some(state) = window_state_mut(hwnd) {
        draw_all(
            hdc,
            (rect.left, rect.top, rect.right, rect.bottom),
            &state.current_snapshot,
            state.transparent_key,
        );
    }
    let _ = EndPaint(hwnd, &paint);
}

unsafe fn draw_all(
    hdc: HDC,
    full_rect: (i32, i32, i32, i32),
    snapshot: &OverlaySnapshot,
    transparent_key: COLORREF,
) {
    let background = CreateSolidBrush(transparent_key);
    let rect = rect_from_tuple(full_rect);
    let _ = FillRect(hdc, &rect, background);
    let _ = DeleteObject(HGDIOBJ(background.0));

    for rectangle in &snapshot.rectangles {
        draw_highlight_rectangle(hdc, rectangle);
    }

    for (index, countdown) in snapshot.countdowns.iter().enumerate() {
        draw_countdown(hdc, countdown, get_countdown_position(index, full_rect));
    }

    let box_gap = 10;
    let top_start = qr_top_start(snapshot);
    for (index, qrcode) in snapshot.qrcodes.iter().enumerate() {
        let total = qrcode.qr_size + (2 * qrcode.padding);
        draw_qrcode(
            hdc,
            qrcode,
            get_qrcode_position(index, total, box_gap, top_start, full_rect),
        );
    }
}

unsafe fn draw_highlight_rectangle(hdc: HDC, rectangle: &HighlightSnapshot) {
    let (left, top, right, bottom) = rectangle.coords;
    let (red, green, blue) = rectangle.color;
    let color = rgb(red, green, blue);
    let pen = CreatePen(PS_SOLID, 2, color);
    let brush = CreateSolidBrush(color);
    let old_pen = SelectObject(hdc, HGDIOBJ(pen.0));
    let old_brush = SelectObject(hdc, HGDIOBJ(brush.0));
    let _ = Rectangle(hdc, left, top, right, bottom);
    let _ = SelectObject(hdc, old_pen);
    let _ = SelectObject(hdc, old_brush);
    let _ = DeleteObject(HGDIOBJ(pen.0));
    let _ = DeleteObject(HGDIOBJ(brush.0));
}

unsafe fn draw_countdown(hdc: HDC, countdown: &CountdownSnapshot, position: (i32, i32, i32, i32)) {
    let lines = countdown_lines(countdown);
    let font = create_countdown_font();
    let old_font = SelectObject(hdc, HGDIOBJ(font.0));
    let _ = SetTextColor(hdc, rgb(0, 0, 128));
    let _ = SetBkMode(hdc, TRANSPARENT);

    let line_sizes: Vec<_> = lines.iter().map(|line| measure_text(hdc, line)).collect();
    let final_rect = countdown_box_rect(position, &line_sizes, (8, 8));
    let background = CreateSolidBrush(rgb(200, 220, 255));
    let _ = FillRect(hdc, &rect_from_tuple(final_rect), background);
    let _ = DeleteObject(HGDIOBJ(background.0));

    let mut y = final_rect.1 + 8;
    for (line, size) in lines.iter().zip(line_sizes.iter()) {
        let x = final_rect.0 + (((final_rect.2 - final_rect.0) - size.width) / 2);
        draw_text(hdc, x, y, line);
        y += size.height;
    }

    let _ = SelectObject(hdc, old_font);
    let _ = DeleteObject(HGDIOBJ(font.0));
}

unsafe fn draw_qrcode(hdc: HDC, qrcode: &QrCodeSnapshot, position: (i32, i32, i32, i32)) {
    let stock_font = HFONT(GetStockObject(DEVICE_DEFAULT_FONT).0);
    let old_font = SelectObject(hdc, HGDIOBJ(stock_font.0));

    let caption_size = if qrcode.caption.is_empty() {
        None
    } else {
        Some(measure_text(hdc, &qrcode.caption))
    };
    let background_rect = qrcode_background_rect(position, caption_size);
    let background = CreateSolidBrush(rgb(255, 255, 255));
    let _ = FillRect(hdc, &rect_from_tuple(background_rect), background);
    let _ = DeleteObject(HGDIOBJ(background.0));

    let pen = CreatePen(PS_SOLID, 0, rgb(0, 0, 0));
    let brush = CreateSolidBrush(rgb(0, 0, 0));
    let old_pen = SelectObject(hdc, HGDIOBJ(pen.0));
    let old_brush = SelectObject(hdc, HGDIOBJ(brush.0));

    let (left, top, _, _) = position;
    for (row_index, row) in qrcode.matrix.iter().enumerate() {
        for (column_index, dark) in row.iter().enumerate() {
            if !dark {
                continue;
            }
            let x0 = left + qrcode.padding + (column_index as i32 * qrcode.pix_per_mod);
            let y0 = top + qrcode.padding + (row_index as i32 * qrcode.pix_per_mod);
            let x1 = x0 + qrcode.pix_per_mod;
            let y1 = y0 + qrcode.pix_per_mod;
            let _ = Rectangle(hdc, x0, y0, x1, y1);
        }
    }

    let _ = SelectObject(hdc, old_pen);
    let _ = SelectObject(hdc, old_brush);
    let _ = DeleteObject(HGDIOBJ(pen.0));
    let _ = DeleteObject(HGDIOBJ(brush.0));

    if let Some(caption_size) = caption_size {
        let mut caption_rect =
            rect_from_tuple(qrcode_caption_rect(position, caption_size, background_rect));
        let _ = SetTextColor(hdc, rgb(0, 0, 0));
        let _ = SetBkMode(hdc, TRANSPARENT);
        let mut wide = to_wide(&qrcode.caption);
        let text_len = wide.len().saturating_sub(1);
        let _ = DrawTextW(
            hdc,
            &mut wide[..text_len],
            &mut caption_rect,
            windows::Win32::Graphics::Gdi::DT_CENTER
                | windows::Win32::Graphics::Gdi::DT_SINGLELINE
                | windows::Win32::Graphics::Gdi::DT_VCENTER,
        );
    }

    let _ = SelectObject(hdc, old_font);
}

unsafe fn create_countdown_font() -> HFONT {
    let mut face_name = [0_u16; 32];
    let wide_name = to_wide("Segoe UI");
    for (index, value) in wide_name.iter().copied().enumerate().take(face_name.len()) {
        face_name[index] = value;
    }

    let mut font = LOGFONTW::default();
    font.lfHeight = -20;
    font.lfWeight = FW_NORMAL.0 as i32;
    font.lfCharSet = ANSI_CHARSET;
    font.lfFaceName = face_name;
    HFONT(CreateFontIndirectW(&font).0)
}

unsafe fn measure_text(hdc: HDC, text: &str) -> TextSize {
    let wide = to_wide(text);
    let mut size = MaybeUninit::zeroed();
    let text_len = wide.len().saturating_sub(1);
    let _ = GetTextExtentPoint32W(hdc, &wide[..text_len], size.as_mut_ptr());
    let size = size.assume_init();
    TextSize {
        width: size.cx,
        height: size.cy,
    }
}

unsafe fn draw_text(hdc: HDC, x: i32, y: i32, text: &str) {
    let wide = to_wide(text);
    let text_len = wide.len().saturating_sub(1);
    let _ = TextOutW(hdc, x, y, &wide[..text_len]);
}

unsafe fn window_state_mut(hwnd: HWND) -> Option<&'static mut WindowState> {
    let state = window_state_ptr(hwnd)?;
    Some(&mut *state)
}

unsafe fn window_state_ptr(hwnd: HWND) -> Option<*mut WindowState> {
    let value = GetWindowLongPtrW(hwnd, GWLP_USERDATA);
    if value == 0 {
        None
    } else {
        Some(value as *mut WindowState)
    }
}

fn rect_from_tuple((left, top, right, bottom): (i32, i32, i32, i32)) -> RECT {
    RECT {
        left,
        top,
        right,
        bottom,
    }
}

fn rgb(red: u8, green: u8, blue: u8) -> COLORREF {
    COLORREF((red as u32) | ((green as u32) << 8) | ((blue as u32) << 16))
}

fn to_wide(value: &str) -> Vec<u16> {
    OsStr::new(value)
        .encode_wide()
        .chain(std::iter::once(0))
        .collect()
}
