from typing import Any

import stress_test_client as stress_module


class StubOverlayClient:
    def __init__(
        self,
        close_result: bool = False,
        update_result: bool = False,
    ) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.closed_windows: list[int] = []
        self.close_result = close_result
        self.update_result = update_result
        self.next_window_id = 40

    def is_available(self) -> bool:
        return True

    def close_window(self, window_id: int) -> bool:
        self.calls.append(("close_window", window_id))
        self.closed_windows.append(window_id)
        return self.close_result

    def update_window_message(self, window_id: int, new_message: str) -> bool:
        self.calls.append(("update_window_message", window_id, new_message))
        return self.update_result

    def create_countdown_window(self, message_text: str, countdown_seconds: int) -> bool:
        self.calls.append(("create_countdown_window", message_text, countdown_seconds))
        return True

    def create_elapsed_time_window(self, message_text: str) -> int | None:
        self.next_window_id += 1
        window_id = self.next_window_id
        self.calls.append(("create_elapsed_time_window", message_text, window_id))
        return window_id

    def create_highlight_window(
        self, rect: tuple[int, int, int, int], timeout_seconds: int
    ) -> bool:
        self.calls.append(("create_highlight_window", rect, timeout_seconds))
        return True

    def create_qrcode_window(
        self, data: str, duration: int = 5, caption: str | None = None
    ) -> int | None:
        self.next_window_id += 1
        window_id = self.next_window_id
        self.calls.append(("create_qrcode_window", data, duration, caption, window_id))
        return window_id


def test_edge_cases_expect_invalid_window_operations_to_fail_gracefully(monkeypatch):
    fake_client = StubOverlayClient()
    monkeypatch.setattr(stress_module, "get_overlay_client", lambda timeout: fake_client)

    stress_client = stress_module.StressTestClient()
    stress_client.test_edge_cases()

    results = {result.test_name: result for result in stress_client.results}
    assert results["Close Invalid Window ID"].success is True
    assert results["Close Invalid Window ID"].additional_data["returned"] is False
    assert results["Update Invalid Window Message"].success is True
    assert (
        results["Update Invalid Window Message"].additional_data["returned"] is False
    )


def test_cleanup_keeps_tracked_windows_when_close_fails(monkeypatch):
    fake_client = StubOverlayClient()
    monkeypatch.setattr(stress_module, "get_overlay_client", lambda timeout: fake_client)
    monkeypatch.setattr(stress_module.time, "sleep", lambda _: None)

    stress_client = stress_module.StressTestClient()
    stress_client.active_windows = [10, 11]
    stress_client.cleanup_remaining_windows()

    assert stress_client.active_windows == [10, 11]
    assert fake_client.closed_windows == [10, 11]


def test_rapid_requests_fail_when_elapsed_follow_up_operations_fail(monkeypatch):
    fake_client = StubOverlayClient(close_result=True)
    monkeypatch.setattr(stress_module, "get_overlay_client", lambda timeout: fake_client)
    monkeypatch.setattr(stress_module.time, "sleep", lambda _: None)

    def fake_choice(options):
        if options == ["countdown", "highlight", "elapsed"]:
            return "elapsed"
        if options == [True, False]:
            return True
        return options[0]

    monkeypatch.setattr(stress_module.random, "choice", fake_choice)

    stress_client = stress_module.StressTestClient()
    stress_client.test_rapid_requests(request_count=1)

    rapid_result = stress_client.results[-1]
    assert rapid_result.test_name == "⚡ Rapid Chaos Test"
    assert rapid_result.success is False
    assert rapid_result.additional_data["successful_requests"] == 0
    assert "elapsed update failed" in rapid_result.error_message
    assert fake_client.closed_windows == [41]
    assert stress_client.active_windows == []


def test_run_demo_uses_showcase_sequence(monkeypatch):
    fake_client = StubOverlayClient(close_result=True, update_result=True)
    monkeypatch.setattr(stress_module, "get_overlay_client", lambda timeout: fake_client)
    monkeypatch.setattr(stress_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        stress_module.StressTestClient,
        "_get_screen_size",
        lambda self: (1600, 900),
    )

    stress_client = stress_module.StressTestClient()
    stress_client.run_demo(repo_url="https://example.com/demo")

    scene_names = [result.test_name for result in stress_client.results]
    assert scene_names == [
        "✨ Spotlight Regions",
        "⏰ Countdown Overlay",
        "🔄 Live Timer Updates",
        "🔗 QR Code Share",
        "🎬 Overlay Finale",
    ]
    assert all(result.success for result in stress_client.results)
    assert [call[0] for call in fake_client.calls[:3]] == [
        "create_highlight_window",
        "create_highlight_window",
        "create_highlight_window",
    ]
    qr_call = next(call for call in fake_client.calls if call[0] == "create_qrcode_window")
    assert qr_call[1] == "https://example.com/demo"
