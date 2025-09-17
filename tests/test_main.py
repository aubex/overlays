from unittest.mock import patch
import sys
import pytest

from overlays import main


def test_exits_on_non_windows_platform(capsys):
    # Mock platform.system to return a non-Windows platform
    with patch("platform.system", return_value="Linux"):
        # Expect SystemExit to be raised with code 1
        with pytest.raises(SystemExit) as exc_info:
            main.cross_platform_helper()  # Call the main function directly

        # Verify the exit code is 1
        assert exc_info.value.code == 1

        # Capture the output and verify the error message
        captured = capsys.readouterr()
        assert (
            "❌ Error: This application is designed to run on Windows only."
            in captured.out
        )


def test_calls_main_with_arg_when_two_args():
    with patch.object(sys, "argv", ["main.py", r"\\.\pipe\overlay_manager_arg"]):
        with patch("overlays.manager.main") as mock_main:
            main.cross_platform_helper()
            mock_main.assert_called_once_with(r"\\.\pipe\overlay_manager_arg")


def test_calls_main_without_args_when_more_than_two_args():
    with patch.object(
        sys, "argv", ["main.py", r"\\.\pipe\overlay_manager_arg", "--help"]
    ):
        with patch("overlays.manager.main") as mock_main:
            main.cross_platform_helper()
            mock_main.assert_called_once_with()


def test_calls_main_without_args():
    with patch("overlays.manager.main") as mock_main:
        with patch.object(sys, "argv", ["main.py"]):
            main.cross_platform_helper()
            mock_main.assert_called_once_with()
