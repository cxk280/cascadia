"""Import-level smoke for the uvicorn entry point.

`main()` blocks on uvicorn.run(), so we patch it to verify it gets called
with the right host/port without actually serving."""

from __future__ import annotations

from unittest.mock import patch

import pytest


def test_main_entrypoint_passes_host_and_port_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CASCADIA_DASHBOARD_HOST", "0.0.0.0")
    monkeypatch.setenv("CASCADIA_DASHBOARD_PORT", "9999")
    # Don't actually run the server — capture the args.
    with patch("cascadia_dashboard.main.uvicorn.run") as run:
        from cascadia_dashboard.main import main
        main()
        run.assert_called_once()
        kwargs = run.call_args.kwargs
        assert kwargs["host"] == "0.0.0.0"
        assert kwargs["port"] == 9999


def test_main_entrypoint_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CASCADIA_DASHBOARD_HOST", raising=False)
    monkeypatch.delenv("CASCADIA_DASHBOARD_PORT", raising=False)
    with patch("cascadia_dashboard.main.uvicorn.run") as run:
        from cascadia_dashboard.main import main
        main()
        kwargs = run.call_args.kwargs
        assert kwargs["host"] == "127.0.0.1"
        assert kwargs["port"] == 18082
