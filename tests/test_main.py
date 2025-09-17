from unittest.mock import patch
from click.testing import CliRunner

import pytest

from overlays import main, manager


def test_exits_on_non_windows_platform(capsys):
    # Mock platform.system to return a non-Windows platform
    with patch("platform.system", return_value="Linux"):
        # Expect SystemExit to be raised with code 1
        with pytest.raises(SystemExit) as exc_info:
            main.cross_platform_helper("")  # Call the main function directly

        # Verify the exit code is 1
        assert exc_info.value.code == 1

        # Capture the output and verify the error message
        captured = capsys.readouterr()
        assert (
            "❌ Error: This application is designed to run on Windows only."
            in captured.out
        )


def test_cli_calls_main_with_option():
    runner = CliRunner()
    with (
        patch("platform.system", return_value="Windows"),
        patch.object(manager, "main") as mock_main,
    ):
        # IMPORTANT: use the exact flag string you declared: --pipe_name
        result = runner.invoke(
            main.cross_platform_helper,
            ["--pipe_name", r"\\.\pipe\overlay_manager_arg"],
        )

    # If it didn't run, result.output will often have Click usage text
    assert result.exit_code == 0, result.output
    mock_main.assert_called_once_with(r"\\.\pipe\overlay_manager_arg")


def test_calls_main_without_args():
    runner = CliRunner()
    with (
        patch("platform.system", return_value="Windows"),
        patch.object(manager, "main") as mock_main,
    ):
        # IMPORTANT: use the exact flag string you declared: --pipe_name
        result = runner.invoke(
            main.cross_platform_helper,
            [],
        )

    # If it didn't run, result.output will often have Click usage text
    assert result.exit_code == 0, result.output
    mock_main.assert_called_once_with(r"\\.\pipe\overlay_manager")
