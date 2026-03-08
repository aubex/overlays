import pytest


@pytest.fixture(autouse=True)
def isolate_overlay_pipe_env(monkeypatch):
    monkeypatch.delenv("OVERLAY_PIPE_NAME", raising=False)
