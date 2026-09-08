import pytest

import overlays.client as client_module


@pytest.fixture(autouse=True)
def isolate_overlay_pipe_env(monkeypatch):
    monkeypatch.delenv("OVERLAY_PIPE_NAME", raising=False)


@pytest.fixture(autouse=True)
def reset_overlay_client_state(monkeypatch):
    client_module._reset_backoff_state()
    monkeypatch.setattr(client_module, "_overlay_client", None)
    monkeypatch.setattr(client_module, "_server_unavailable_warning_emitted", False)
    yield
    client_module._reset_backoff_state()
