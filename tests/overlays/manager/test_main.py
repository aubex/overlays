import ctypes
import queue
from collections.abc import Generator
from typing import TypeVar
from unittest.mock import MagicMock, Mock, call, patch

import pytest
import win32api
import win32con
import win32gui

from main import (
    OVERLAY_WINDOW_CLASS,
    BaseWindow,
    CountdownWindow,
    ElapsedTimeWindow,
    ElapsedTimeWindowControl,
    HighlightWindow,
    OverlayManager,
    WindowManager,
)

T = TypeVar("T")


@pytest.fixture
def mock_bw_win32() -> Generator[dict[str, Mock]]:
    with (
        patch("main.win32gui.WNDCLASS") as mock_wndclass,
        patch("main.win32gui.RegisterClass") as mock_register,
        patch("main.win32api.GetModuleHandle") as mock_module,
    ):
        mock_module.return_value = 12345  # Fake module handle
        mock_wndclass.return_value = Mock(
            style=0,
            lpfnWndProc=None,
            hInstance=None,
            hbrBackground=0,
            lpszClassName=None,
        )

        yield {
            "wndclass": mock_wndclass,
            "register": mock_register,
            "module": mock_module,
        }


class TestBaseWindow:
    def test_init_registers_window_class(self, mock_bw_win32: dict[str, Mock]) -> None:
        """Test that initialization properly registers the window class."""

        class TestWindow(BaseWindow):
            def create_window(self) -> None: ...
            def on_paint(self, hwnd: int) -> None: ...
            def on_timer(self, hwnd: int) -> None: ...
            def on_destroy(self, hwnd: int) -> None: ...

        _ = TestWindow("TestWindow")

        assert mock_bw_win32["register"].called
        wndclass = mock_bw_win32["wndclass"].return_value
        assert wndclass.style == win32con.CS_HREDRAW | win32con.CS_VREDRAW
        assert wndclass.hInstance == mock_bw_win32["module"].return_value
        assert wndclass.hbrBackground == win32con.COLOR_WINDOW
        assert wndclass.lpszClassName == f"{OVERLAY_WINDOW_CLASS}_TestWindow"

    def test_window_class_already_exists_handled(
        self, mock_bw_win32: dict[str, Mock]
    ) -> None:
        """Test that the 'class already exists' error is properly handled."""

        class TestWindow(BaseWindow):
            def create_window(self) -> None: ...
            def on_paint(self, hwnd: int) -> None: ...
            def on_timer(self, hwnd: int) -> None: ...
            def on_destroy(self, hwnd: int) -> None: ...

        # Simulate "class already exists" error
        error = win32gui.error()
        error.winerror = 1410
        mock_bw_win32["register"].side_effect = error

        # Should not raise an exception
        TestWindow("TestWindow")

    @patch("main.win32gui.SetWindowPos")
    def test_move_window(
        self, mock_set_pos: Mock, mock_bw_win32: dict[str, Mock]
    ) -> None:
        """Test that move_window calls SetWindowPos with correct parameters."""

        class TestWindow(BaseWindow): ...

        window = TestWindow("TestWindow")
        window.hwnd = 54321
        window.move_window(100, 200)

        mock_set_pos.assert_called_once_with(
            54321,  # hwnd
            None,  # insertAfter
            100,  # x
            200,  # y
            0,  # cx
            0,  # cy
            win32con.SWP_NOZORDER | win32con.SWP_NOSIZE,  # flags
        )

    @patch("ctypes.windll.user32.SetTimer")
    def test_set_timer(
        self, mock_set_timer: Mock, mock_bw_win32: dict[str, Mock]
    ) -> None:
        """Test that set_timer calls SetTimer with correct parameters."""

        class TestWindow(BaseWindow): ...

        window = TestWindow("TestWindow")
        window.hwnd = 54321
        window.set_timer(1, 1000)

        mock_set_timer.assert_called_once_with(54321, 1, 1000, None)

    def test_wnd_proc_handling(self, mock_bw_win32: dict[str, Mock]) -> None:
        """Test window procedure message handling."""
        paint_called = False
        timer_called = False
        destroy_called = False

        class TestWindow(BaseWindow):
            def create_window(self) -> None: ...

            def on_paint(self, hwnd: int) -> None:
                nonlocal paint_called
                paint_called = True

            def on_timer(self, hwnd: int) -> None:
                nonlocal timer_called
                timer_called = True

            def on_destroy(self, hwnd: int) -> None:
                nonlocal destroy_called
                destroy_called = True

        window = TestWindow("TestWindow")

        # Test WM_PAINT handling
        window.wnd_proc(12345, win32con.WM_PAINT, 0, 0)
        assert paint_called, "on_paint should have been called"

        # Test WM_TIMER handling
        window.wnd_proc(12345, win32con.WM_TIMER, 0, 0)
        assert timer_called, "on_timer should have been called"

        # Test WM_DESTROY handling
        window.wnd_proc(12345, win32con.WM_DESTROY, 0, 0)
        assert destroy_called, "on_destroy should have been called"

        # Test default message handling
        with patch("win32gui.DefWindowProc") as mock_def_proc:
            window.wnd_proc(12345, 9999, 0, 0)  # 9999 is a custom message
            mock_def_proc.assert_called_once_with(12345, 9999, 0, 0)

    @patch("win32gui.CreateWindowEx")
    def test_create_base_window(
        self,
        mock_create_window: Mock,
        mock_bw_win32: dict[str, Mock],
    ) -> None:
        """Test create_base_window method."""

        class TestWindow(BaseWindow):
            def create_window(self) -> None:
                self.create_base_window(
                    100,
                    200,
                    300,
                    400,
                    win32con.WS_EX_TOPMOST,
                    win32con.WS_POPUP,
                )

        window = TestWindow("TestWindow")
        window.set_resources(100, 200)

        # Verify CreateWindowEx was called with correct parameters
        expected_ex_style = (
            win32con.WS_EX_TOPMOST
            | win32con.WS_EX_NOACTIVATE
            | win32con.WS_EX_TRANSPARENT
        )

        mock_create_window.assert_called_once_with(
            expected_ex_style,
            f"{OVERLAY_WINDOW_CLASS}_TestWindow",
            "",
            win32con.WS_POPUP,
            100,
            200,
            300,
            400,
            None,
            None,
            mock_bw_win32["module"].return_value,
            None,
        )

    @patch("win32gui.BeginPaint")
    @patch("win32gui.SaveDC")
    @patch("win32gui.RestoreDC")
    @patch("win32gui.EndPaint")
    def test_safe_paint(
        self,
        mock_end_paint: MagicMock,
        mock_restore_dc: MagicMock,
        mock_save_dc: MagicMock,
        mock_begin_paint: MagicMock,
    ) -> None:
        """Test safe_paint method ensures proper painting context management."""

        class TestWindow(BaseWindow): ...

        window = TestWindow("TestWindow")

        # Setup mocks
        mock_begin_paint.return_value = (123, "ps")  # hdc and paint struct
        mock_save_dc.return_value = 456  # saved DC state

        # Test paint function to verify it's called
        paint_called = False

        def test_paint(hdc: int) -> None:
            nonlocal paint_called
            paint_called = True
            assert hdc == 123  # Should receive the hdc from BeginPaint

        # Call safe_paint
        window.safe_paint(789, test_paint)

        # Verify all painting operations occurred in correct order
        assert paint_called, "Paint function should have been called"

        mock_begin_paint.assert_called_once_with(789)
        mock_save_dc.assert_called_once_with(123)
        mock_restore_dc.assert_called_once_with(123, 456)
        mock_end_paint.assert_called_once_with(789, "ps")

    @patch("win32gui.CreateWindowEx")
    def test_error_handling_in_create_window(
        self,
        mock_create_window: MagicMock,
    ) -> None:
        """Test error handling during window creation."""

        class TestWindow(BaseWindow):
            def create_window(self) -> None:
                self.hdc = 100  # Mock HDC
                self.font = 200  # Mock font
                self.create_base_window(
                    100,
                    200,
                    300,
                    400,
                    win32con.WS_EX_TOPMOST,
                    win32con.WS_POPUP,
                )

        # Simulate CreateWindowEx failure
        mock_create_window.side_effect = win32gui.error()

        window = TestWindow("TestWindow")

        # Explicitly call create_window to trigger the error
        with pytest.raises(win32gui.error):
            window.create_window()


@pytest.fixture
def mock_cd_manager() -> Mock:
    manager = Mock()
    manager.active_windows = []
    return manager


@pytest.fixture
def mock_cd_win32() -> Generator[dict[str, Mock]]:
    # Mock all the Win32 API calls we need at a higher level
    with (
        patch("win32gui.CreateCompatibleDC") as mock_create_dc,
        patch("win32gui.GetStockObject") as mock_get_stock,
        patch("win32gui.SelectObject") as mock_select,
        patch("win32gui.DeleteDC") as mock_delete_dc,
        patch("win32api.GetSystemMetrics") as mock_metrics,
        patch("win32gui.CreateWindowEx") as mock_create_window,
        patch("win32gui.SetLayeredWindowAttributes") as mock_set_layered,
        patch("win32gui.ShowWindow") as mock_show,
        patch("win32gui.UpdateWindow") as mock_update,
        patch("win32gui.RegisterClass") as mock_register,
    ):
        # Setup basic returns
        mock_create_dc.return_value = 100
        mock_get_stock.return_value = 200
        mock_select.return_value = 300
        mock_metrics.return_value = 1920
        mock_create_window.return_value = 400

        # Mock DrawTextW at the module level instead of the function level
        with patch.object(ctypes.windll.user32, "DrawTextW", return_value=1):
            yield {
                "create_dc": mock_create_dc,
                "get_stock": mock_get_stock,
                "select": mock_select,
                "delete_dc": mock_delete_dc,
                "metrics": mock_metrics,
                "create_window": mock_create_window,
                "set_layered": mock_set_layered,
                "show": mock_show,
                "update": mock_update,
                "register": mock_register,
            }


class TestCountdownWindow:
    def test_window_creation_basic(
        self,
        mock_cd_win32: dict[str, Mock],
        mock_cd_manager: Mock,
    ) -> None:
        """Test basic window creation."""
        window = CountdownWindow("Test Message", 10, mock_cd_manager)

        # Set resources first (simulating what happens in the actual code)
        window.set_resources(
            mock_cd_win32["create_dc"].return_value,
            mock_cd_win32["get_stock"].return_value,
        )
        window.create_window()

        # Verify window class registration occurred
        assert mock_cd_win32["register"].called

        # Verify window was created
        assert mock_cd_win32["create_window"].called

        # Verify window was shown and updated
        assert mock_cd_win32["show"].called
        assert mock_cd_win32["update"].called

    def test_window_styles(
        self,
        mock_cd_win32: dict[str, Mock],
        mock_cd_manager: Mock,
    ) -> None:
        """Test window styles are set correctly."""
        window = CountdownWindow("Test Message", 10, mock_cd_manager)

        # Set resources first
        window.set_resources(
            mock_cd_win32["create_dc"].return_value,
            mock_cd_win32["get_stock"].return_value,
        )

        # Then create the window
        window.create_window()

        create_args = mock_cd_win32["create_window"].call_args[0]

        # Check extended styles
        ex_style = create_args[0]
        assert ex_style & win32con.WS_EX_TOPMOST
        assert ex_style & win32con.WS_EX_LAYERED
        assert ex_style & win32con.WS_EX_TRANSPARENT
        assert ex_style & win32con.WS_EX_NOACTIVATE

        # Check basic style
        style = create_args[3]
        assert style == win32con.WS_POPUP

    def test_custom_position(
        self,
        mock_cd_win32: dict[str, Mock],
        mock_cd_manager: Mock,
    ) -> None:
        """Test window creation with custom position."""
        window = CountdownWindow("Test Message", 10, mock_cd_manager)
        window.set_resources(
            mock_cd_win32["create_dc"].return_value,
            mock_cd_win32["get_stock"].return_value,
        )
        window.create_window(x=100, y=200)

        create_args = mock_cd_win32["create_window"].call_args[0]
        assert create_args[4] == 100  # x position
        assert create_args[5] == 200  # y position

    def test_on_timer(
        self,
        mock_cd_win32: dict[str, Mock],
        mock_cd_manager: Mock,
    ) -> None:
        """Test timer functionality."""
        with (
            patch("win32gui.PostMessage") as mock_post,
            patch("win32gui.InvalidateRect") as mock_invalidate,
        ):
            window = CountdownWindow("Test Message", 2, mock_cd_manager)

            # First tick
            window.on_timer(window.hwnd)
            assert window.countdown_seconds == 1
            assert mock_invalidate.called
            assert not mock_post.called

            # Reset mock calls
            mock_invalidate.reset_mock()

            # Second tick
            window.on_timer(window.hwnd)
            assert window.countdown_seconds == 0
            assert mock_post.called
            mock_post.assert_called_with(window.hwnd, win32con.WM_CLOSE, 0, 0)

    def test_on_destroy(
        self,
        mock_cd_win32: dict[str, Mock],
        mock_cd_manager: Mock,
    ) -> None:
        """Test cleanup on window destruction."""
        window = CountdownWindow("Test Message", 10, mock_cd_manager)
        window.on_destroy(window.hwnd)
        mock_cd_manager.remove_window.assert_called_once_with(window)


@pytest.fixture
def mock_hw_manager() -> Mock:
    manager = Mock()
    manager.active_windows = []
    return manager


@pytest.fixture
def mock_hw_win32() -> Generator[dict[str, Mock]]:
    with (
        patch("win32gui.CreateWindowEx") as mock_create_window,
        patch("win32gui.SetLayeredWindowAttributes") as mock_set_layered,
        patch("win32gui.ShowWindow") as mock_show,
        patch("win32gui.UpdateWindow") as mock_update,
        patch("win32gui.RegisterClass") as mock_register,
    ):
        # Setup basic returns
        mock_create_window.return_value = 400  # fake window handle

        yield {
            "create_window": mock_create_window,
            "set_layered": mock_set_layered,
            "show": mock_show,
            "update": mock_update,
            "register": mock_register,
        }


@pytest.fixture
def sample_rect() -> tuple[int, int, int, int]:
    return (100, 200, 300, 400)  # x, y, right, bottom


class TestHighlightWindow:
    def test_window_creation_basic(
        self,
        mock_hw_win32: dict[str, Mock],
        mock_hw_manager: Mock,
        sample_rect: tuple[int, int, int, int],
    ) -> None:
        """Test basic window creation with correct dimensions."""
        window = HighlightWindow(sample_rect, 10, mock_hw_manager)
        window.set_resources(100, 200)

        # Verify window class registration
        assert mock_hw_win32["register"].called

        # Verify window creation with correct dimensions
        create_args = mock_hw_win32["create_window"].call_args[0]
        assert create_args[4] == 100  # x position
        assert create_args[5] == 200  # y position
        assert create_args[6] == 200  # width (300 - 100)
        assert create_args[7] == 200  # height (400 - 200)

    def test_window_styles(
        self,
        mock_hw_win32: dict[str, Mock],
        mock_hw_manager: Mock,
        sample_rect: tuple[int, int, int, int],
    ) -> None:
        """Test window styles are set correctly."""
        window = HighlightWindow(sample_rect, 10, mock_hw_manager)
        window.set_resources(100, 200)

        create_args = mock_hw_win32["create_window"].call_args[0]

        # Check extended styles
        ex_style = create_args[0]
        assert ex_style & win32con.WS_EX_TOPMOST
        assert ex_style & win32con.WS_EX_LAYERED
        assert ex_style & win32con.WS_EX_TRANSPARENT
        assert ex_style & win32con.WS_EX_NOACTIVATE

        # Check basic style
        style = create_args[3]
        assert style == win32con.WS_POPUP

    def test_color_selection(
        self,
        mock_hw_win32: dict[str, Mock],
        mock_hw_manager: Mock,
        sample_rect: tuple[int, int, int, int],
    ) -> None:
        """Test that a color is randomly selected from the predefined list."""
        with patch("random.choice") as mock_choice:
            mock_choice.return_value = (255, 99, 71)  # Mock to return "Tomato" color

            window = HighlightWindow(sample_rect, 10, mock_hw_manager)
            window.set_resources(100, 200)

            mock_choice.assert_called_once_with(HighlightWindow.colors)
            assert window.color == (255, 99, 71)

    def test_transparency_settings(
        self,
        mock_hw_win32: dict[str, Mock],
        mock_hw_manager: Mock,
        sample_rect: tuple[int, int, int, int],
    ) -> None:
        """Test that transparency is set correctly."""
        window = HighlightWindow(sample_rect, 10, mock_hw_manager)
        window.set_resources(100, 200)

        mock_hw_win32["set_layered"].assert_called_once_with(
            mock_hw_win32["create_window"].return_value,
            0,
            128,
            win32con.LWA_ALPHA,
        )

    @patch("win32gui.GetClientRect")
    @patch("win32gui.CreatePen")
    @patch("win32gui.CreateSolidBrush")
    @patch("win32gui.SelectObject")
    @patch("win32gui.Rectangle")
    @patch("win32gui.DeleteObject")
    @patch("win32gui.BeginPaint")
    @patch("win32gui.EndPaint")
    @patch("win32gui.SaveDC")
    @patch("win32gui.RestoreDC")
    def test_on_paint(  # noqa: PLR0913
        self,
        mock_restore_dc: MagicMock,
        mock_save_dc: MagicMock,
        mock_end_paint: MagicMock,
        mock_begin_paint: MagicMock,
        mock_delete: MagicMock,
        mock_rectangle: MagicMock,
        mock_select: MagicMock,
        mock_create_brush: MagicMock,
        mock_create_pen: MagicMock,
        mock_get_rect: MagicMock,
        mock_hw_win32: dict[str, Mock],
        mock_hw_manager: Mock,
        sample_rect: tuple[int, int, int, int],
    ) -> None:
        """Test painting functionality."""
        # Setup mocks
        mock_get_rect.return_value = (0, 0, 200, 200)
        mock_begin_paint.return_value = (500, "ps")  # hdc and paint struct
        mock_create_pen.return_value = 601  # pen handle
        mock_create_brush.return_value = 602  # brush handle
        mock_save_dc.return_value = 700  # saved DC state

        # Mock SelectObject to return different values for each call
        mock_select.side_effect = [
            603,  # Return value when selecting pen
            604,  # Return value when selecting brush
            None,  # Return value when restoring old pen
            None,  # Return value when restoring old brush
        ]

        window = HighlightWindow(sample_rect, 10, mock_hw_manager)
        window.color = (255, 99, 71)  # Set a specific color for testing

        window.on_paint(window.hwnd)

        # Verify the complete painting sequence
        # 1. Begin paint and save DC state
        mock_begin_paint.assert_called_once_with(window.hwnd)
        mock_save_dc.assert_called_once_with(500)

        # 2. Create and select GDI objects
        mock_create_pen.assert_called_once_with(
            win32con.PS_SOLID, 5, win32api.RGB(255, 99, 71)
        )
        mock_create_brush.assert_called_once_with(win32api.RGB(255, 99, 71))

        # 3. Verify SelectObject calls sequence
        select_calls = mock_select.call_args_list
        assert len(select_calls) == 4
        assert select_calls[0] == call(500, 601)  # Select pen
        assert select_calls[1] == call(500, 602)  # Select brush
        assert select_calls[2] == call(500, 603)  # Restore old pen
        assert select_calls[3] == call(500, 604)  # Restore old brush

        # 4. Verify drawing
        mock_rectangle.assert_called_once_with(500, 0, 0, 200, 200)

        # 5. Verify cleanup sequence
        mock_restore_dc.assert_called_once_with(500, 700)
        mock_end_paint.assert_called_once_with(window.hwnd, "ps")

        # 6. Verify GDI object cleanup
        delete_calls = mock_delete.call_args_list
        assert len(delete_calls) == 2
        assert delete_calls[0] == call(601)  # Delete pen
        assert delete_calls[1] == call(602)  # Delete brush

    def test_on_timer(
        self,
        mock_hw_win32: dict[str, Mock],
        mock_hw_manager: Mock,
        sample_rect: tuple[int, int, int, int],
    ) -> None:
        """Test timer functionality."""
        with (
            patch("win32gui.PostMessage") as mock_post,
            patch("win32gui.InvalidateRect") as mock_invalidate,
        ):
            window = HighlightWindow(sample_rect, 2, mock_hw_manager)

            # First tick
            window.on_timer(window.hwnd)
            assert window.timeout_seconds == 1
            assert mock_invalidate.called
            assert not mock_post.called

            # Reset mock calls
            mock_invalidate.reset_mock()

            # Second tick
            window.on_timer(window.hwnd)
            assert window.timeout_seconds == 0
            assert mock_post.called
            mock_post.assert_called_with(window.hwnd, win32con.WM_CLOSE, 0, 0)

    def test_on_destroy(
        self,
        mock_hw_win32: dict[str, Mock],
        mock_hw_manager: Mock,
        sample_rect: tuple[int, int, int, int],
    ) -> None:
        """Test cleanup on window destruction."""
        window = HighlightWindow(sample_rect, 10, mock_hw_manager)
        window.on_destroy(window.hwnd)
        mock_hw_manager.remove_window.assert_called_once_with(window)

    def test_valid_colors(self) -> None:
        """Test that all predefined colors are valid RGB tuples."""
        for color in HighlightWindow.colors:
            assert len(color) == 3
            assert all(0 <= c <= 255 for c in color)


@pytest.fixture
def mock_et_manager() -> Mock:
    manager = Mock()
    manager.active_windows = []
    return manager


@pytest.fixture
def mock_et_win32() -> Generator[dict[str, Mock]]:
    with (
        patch("win32gui.CreateWindowEx") as mock_create_window,
        patch("win32gui.SetLayeredWindowAttributes") as mock_set_layered,
        patch("win32gui.ShowWindow") as mock_show,
        patch("win32gui.UpdateWindow") as mock_update,
        patch("win32gui.RegisterClass") as mock_register,
        patch("win32gui.CreateCompatibleDC") as mock_create_dc,
        patch("win32gui.GetStockObject") as mock_get_stock,
        patch("win32gui.SelectObject") as mock_select,
        patch("win32gui.DeleteDC") as mock_delete_dc,
        patch("win32api.GetSystemMetrics") as mock_metrics,
    ):
        # Setup basic returns
        mock_create_window.return_value = 400  # fake window handle
        mock_create_dc.return_value = 100
        mock_get_stock.return_value = 200
        mock_select.return_value = 300
        mock_metrics.return_value = 1920

        yield {
            "create_window": mock_create_window,
            "set_layered": mock_set_layered,
            "show": mock_show,
            "update": mock_update,
            "register": mock_register,
            "create_dc": mock_create_dc,
            "get_stock": mock_get_stock,
            "select": mock_select,
            "delete_dc": mock_delete_dc,
            "metrics": mock_metrics,
        }


class TestElapsedTimeWindow:
    def test_init(self, mock_et_win32: Mock, mock_et_manager: dict[str, Mock]) -> None:
        """Test initial state of ElapsedTimeWindow."""
        window = ElapsedTimeWindow("Test Message", mock_et_manager)

        assert window.message_text == "Test Message"
        assert window.elapsed_seconds == 0
        assert window.running
        assert window.manager == mock_et_manager

    def test_custom_position(
        self, mock_et_win32: Mock, mock_et_manager: dict[str, Mock]
    ) -> None:
        """Test window creation with custom position."""
        with patch("ctypes.windll.user32.DrawTextW", return_value=1):
            window = ElapsedTimeWindow("Test Message", mock_et_manager)
            window.set_resources(100, 200)
            window.create_window(x=100, y=200)

            args = mock_et_win32["create_window"].call_args[0]
            assert args[4] == 100  # x position
            assert args[5] == 200  # y position

    def test_update_message(
        self, mock_et_win32: Mock, mock_et_manager: dict[str, Mock]
    ) -> None:
        """Test message updating functionality."""
        window = ElapsedTimeWindow("Initial Message", mock_et_manager)
        with patch("win32gui.InvalidateRect") as mock_invalidate:
            window.hwnd = 400  # Set window handle
            window.update_message("Updated Message")

            assert window.message_text == "Updated Message"
            mock_invalidate.assert_called_once_with(400, None, True)

    @patch("win32gui.InvalidateRect")
    @patch("win32gui.PostMessage")
    def test_on_timer_running(
        self,
        mock_post: Mock,
        mock_invalidate: Mock,
        mock_et_win32: Mock,
        mock_et_manager: dict[str, Mock],
    ) -> None:
        """Test timer behavior while window is running."""
        window = ElapsedTimeWindow("Test Message", mock_et_manager)
        window.hwnd = 400

        # First tick
        window.on_timer(window.hwnd)
        assert window.elapsed_seconds == 1
        mock_invalidate.assert_called_once()
        mock_post.assert_not_called()

        # Second tick
        window.on_timer(window.hwnd)
        assert window.elapsed_seconds == 2
        assert mock_invalidate.call_count == 2

    @patch("win32gui.InvalidateRect")
    @patch("win32gui.PostMessage")
    def test_on_timer_stopped(
        self,
        mock_post: Mock,
        mock_invalidate: Mock,
        mock_et_win32: Mock,
        mock_et_manager: dict[str, Mock],
    ) -> None:
        """Test timer behavior after window is stopped."""
        window = ElapsedTimeWindow("Test Message", mock_et_manager)
        window.hwnd = 400

        window.stop()
        window.on_timer(window.hwnd)

        assert window.elapsed_seconds == 0  # Should not increment
        mock_invalidate.assert_not_called()
        mock_post.assert_called_once_with(400, win32con.WM_CLOSE, 0, 0)

    def test_stop(self, mock_et_win32: Mock, mock_et_manager: dict[str, Mock]) -> None:
        """Test stop functionality."""
        window = ElapsedTimeWindow("Test Message", mock_et_manager)
        assert window.running

        window.stop()
        assert not window.running

    def test_on_destroy(
        self, mock_et_win32: Mock, mock_et_manager: dict[str, Mock]
    ) -> None:
        """Test cleanup on window destruction."""
        window = ElapsedTimeWindow("Test Message", mock_et_manager)
        window.on_destroy(window.hwnd)
        mock_et_manager.remove_window.assert_called_once_with(window)


@pytest.fixture
def mock_window() -> Mock:
    window = Mock()
    window.hwnd = 400  # fake window handle
    return window


@pytest.fixture
def manager() -> WindowManager:
    return WindowManager()


class TestWindowManager:
    def test_init(self, manager: WindowManager) -> None:
        """Test initial state of WindowManager."""
        assert manager.active_windows == []

    def test_remove_window(self, manager: WindowManager, mock_window: Mock) -> None:
        """Test removing a window from active windows."""
        # Setup
        manager.active_windows = [mock_window]

        with (
            patch("win32api.GetSystemMetrics"),
            patch("win32gui.GetWindowRect"),
            patch("win32gui.MoveWindow"),
        ):
            manager.remove_window(mock_window)

            assert mock_window not in manager.active_windows
            assert len(manager.active_windows) == 0

    def test_remove_nonexistent_window(
        self, manager: WindowManager, mock_window: Mock
    ) -> None:
        """Test removing a window that isn't in active windows."""
        # Setup
        other_window = Mock()
        manager.active_windows = [other_window]

        with (
            patch("win32api.GetSystemMetrics"),
            patch("win32gui.GetWindowRect"),
            patch("win32gui.MoveWindow"),
        ):
            manager.remove_window(mock_window)

            assert other_window in manager.active_windows
            assert len(manager.active_windows) == 1

    def test_realign_single_window(
        self, manager: WindowManager, mock_window: Mock
    ) -> None:
        """Test realignment with a single window."""
        manager.active_windows = [mock_window]

        with (
            patch("win32api.GetSystemMetrics", return_value=1920) as mock_metrics,
            patch(
                "win32gui.GetWindowRect", return_value=(0, 0, 300, 200)
            ) as mock_get_rect,
            patch("win32gui.MoveWindow") as mock_move,
        ):
            manager.realign_windows()

            # Verify system metrics were checked
            mock_metrics.assert_called_once_with(win32con.SM_CXSCREEN)

            # Verify window rect was retrieved
            mock_get_rect.assert_called_once_with(mock_window.hwnd)

            # Calculate expected position
            width = 300  # rect[2] - rect[0]
            height = 200  # rect[3] - rect[1]
            expected_x = (1920 - width) // 2
            expected_y = 20  # y_start

            # Verify window was moved to correct position
            mock_move.assert_called_once_with(
                mock_window.hwnd,
                expected_x,
                expected_y,
                width,
                height,
                True,
            )

    def test_realign_multiple_windows(self, manager: WindowManager) -> None:
        """Test realignment with multiple windows."""
        window1 = Mock()
        window1.hwnd = 401
        window2 = Mock()
        window2.hwnd = 402
        window3 = Mock()
        window3.hwnd = 403

        manager.active_windows = [window1, window2, window3]

        with (
            patch("win32api.GetSystemMetrics", return_value=1920),
            patch(
                "win32gui.GetWindowRect",
                side_effect=[
                    (0, 0, 300, 150),  # window1: 300x150
                    (0, 0, 400, 200),  # window2: 400x200
                    (0, 0, 350, 180),  # window3: 350x180
                ],
            ),
            patch("win32gui.MoveWindow") as mock_move,
        ):
            manager.realign_windows()

            calls = mock_move.call_args_list
            assert len(calls) == 3

            # Map hwnd to their y positions to preserve the correct order
            y_positions_by_hwnd = {
                call_args[0][0]: call_args[0][2]  # hwnd: y_position
                for call_args in calls
            }

            # Check positions in the original window order
            expected_hwnds = [401, 402, 403]
            y_positions = [y_positions_by_hwnd[hwnd] for hwnd in expected_hwnds]

            # Now verify vertical positioning
            for i in range(1, len(y_positions)):
                assert y_positions[i] > y_positions[i - 1], (
                    f"Window {expected_hwnds[i]} should be below window {expected_hwnds[i - 1]}"
                )

    def test_realign_windows_with_invalid_window(
        self,
        manager: WindowManager,
        mock_window: Mock,
    ) -> None:
        """Test realignment with a window that has no hwnd attribute."""
        invalid_window = Mock(spec=[])
        # Don't set hwnd attribute

        manager.active_windows = [mock_window, invalid_window]

        with (
            patch("win32api.GetSystemMetrics", return_value=1920),
            patch(
                "win32gui.GetWindowRect", return_value=(0, 0, 300, 200)
            ) as mock_get_rect,
            patch("win32gui.MoveWindow") as mock_move,
        ):
            # Should not raise exception
            manager.realign_windows()

            # Should only process the valid window
            mock_get_rect.assert_called_once_with(mock_window.hwnd)
            assert mock_move.call_count == 1


class TestOverlayManager:
    @pytest.fixture(autouse=True)
    def reset_singleton(self, monkeypatch):
        # Reset singleton before each test
        OverlayManager._instance = None
        # Prevent actual thread starting
        monkeypatch.setattr(OverlayManager, "start_thread", lambda self: None)
        monkeypatch.setattr(OverlayManager, "start_pipe_server", lambda self: None)
        yield
        # Cleanup
        OverlayManager._instance = None

    @pytest.fixture
    def om_manager(self):
        # Provide fresh instance
        return OverlayManager()

    def test_singleton_behavior(self, om_manager: OverlayManager):
        # __new__ enforces singleton
        other = OverlayManager()
        assert om_manager is other

    def test_create_countdown_command_queued(self, om_manager: OverlayManager):
        om_manager.command_queue = queue.Queue()
        om_manager.create_countdown_window("Test", 5)
        cmd = om_manager.command_queue.get_nowait()
        assert cmd == ("create_countdown", "Test", 5)

    def test_create_qrcode_command_queued(self, om_manager: OverlayManager):
        om_manager.command_queue = queue.Queue()
        om_manager.create_qrcode_window("data", 10, "caption")
        cmd = om_manager.command_queue.get_nowait()
        assert cmd == ("create_qrcode", "data", 10, "caption")

    def test_create_highlight_command_queued(self, om_manager: OverlayManager):
        om_manager.command_queue = queue.Queue()
        rect = (1, 2, 3, 4)
        om_manager.create_highlight_window(rect, timeout_seconds=7)
        cmd = om_manager.command_queue.get_nowait()
        assert cmd == ("create_highlight", rect, 7)

    def test_create_elapsed_time_window_success(self, om_manager: OverlayManager):
        # Simulate response available
        om_manager.response_queue = queue.Queue()
        om_manager.response_queue.put(42)
        ctrl = om_manager.create_elapsed_time_window("Hello")
        assert isinstance(ctrl, ElapsedTimeWindowControl)
        assert ctrl.window_id == 42
        assert ctrl.overlay_manager is om_manager

    def test_create_elapsed_time_window_timeout(self, om_manager: OverlayManager):
        # Empty response queue yields None
        om_manager.response_queue = queue.Queue()
        ctrl = om_manager.create_elapsed_time_window("Hello")
        assert ctrl is None

    def test_close_window_queues_command(self, om_manager: OverlayManager):
        om_manager.command_queue = queue.Queue()
        om_manager.close_window(99)
        cmd = om_manager.command_queue.get_nowait()
        assert cmd == ("close_window", 99)

    def test_update_window_message_queues_command(self, om_manager: OverlayManager):
        om_manager.command_queue = queue.Queue()
        om_manager.update_window_message(7, "New")
        cmd = om_manager.command_queue.get_nowait()
        assert cmd == ("update_message", 7, "New")

    def test_take_break_success(self, om_manager: OverlayManager):
        om_manager.command_queue = queue.Queue()
        om_manager.response_queue = queue.Queue()
        om_manager.response_queue.put("break_started")
        result = om_manager.take_break(15)
        # Break command is queued
        cmd = om_manager.command_queue.get_nowait()
        assert cmd == ("take_break", 15)
        assert result is True

    def test_take_break_timeout(self, om_manager: OverlayManager):
        om_manager.command_queue = queue.Queue()
        om_manager.response_queue = queue.Queue()
        result = om_manager.take_break(10)
        assert result is False

    def test_cancel_break_success(self, om_manager: OverlayManager):
        om_manager.command_queue = queue.Queue()
        om_manager.response_queue = queue.Queue()
        om_manager.response_queue.put("break_canceled")
        result = om_manager.cancel_break()
        cmd = om_manager.command_queue.get_nowait()
        assert cmd == ("cancel_break",)
        assert result is True

    def test_cancel_break_timeout(self, om_manager: OverlayManager):
        om_manager.command_queue = queue.Queue()
        om_manager.response_queue = queue.Queue()
        result = om_manager.cancel_break()
        assert result is False

    def test_shutdown_closes_threads(self, om_manager: OverlayManager):
        # Create mock threads
        mock_thread = Mock()
        mock_thread.is_alive.return_value = True
        mock_pipe = Mock()
        mock_pipe.is_alive.return_value = True
        om_manager.thread = mock_thread
        om_manager.pipe_thread = mock_pipe
        om_manager.command_queue = queue.Queue()
        # Perform shutdown
        om_manager.shutdown()
        # Shutdown event set
        assert om_manager.shutdown_event.is_set()
        # Shutdown should send None
        assert om_manager.command_queue.get_nowait() is None
        # Threads join called
        mock_thread.join.assert_called()
        mock_pipe.join.assert_called()
