"""Shared fixtures for the aprs_send tests."""

from __future__ import annotations

from collections.abc import Generator
import socket
import sys
from unittest.mock import MagicMock, patch

import pytest

if sys.platform == "win32":
    # asyncio's Windows event loop needs a loopback TCP socket pair for its
    # self-pipe, but the HA test plugin replaces socket.socket with a guard
    # that forbids creating any socket. Provide a socketpair() built on the
    # real socket class captured before the guard is installed. Outbound
    # connections stay restricted to 127.0.0.1 by pytest-socket's connect
    # guard, so tests still cannot reach the network.
    _RealSocket = socket.socket

    def _loopback_socketpair(
        family: int = socket.AF_INET, type: int = socket.SOCK_STREAM, proto: int = 0
    ) -> tuple[socket.socket, socket.socket]:
        lsock = _RealSocket(family, type, proto)
        try:
            lsock.bind(("127.0.0.1", 0))
            lsock.listen()
            csock = _RealSocket(family, type, proto)
            try:
                csock.setblocking(True)
                csock.connect(lsock.getsockname())
                # socket.accept() would instantiate the guarded class again,
                # so accept at the C level and wrap the fd ourselves.
                fd, _ = lsock._accept()  # noqa: SLF001
                ssock = _RealSocket(family, type, proto, fileno=fd)
            except Exception:
                csock.close()
                raise
        finally:
            lsock.close()
        return (ssock, csock)

    socket.socketpair = _loopback_socketpair


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading of custom integrations in every test."""


@pytest.fixture
def mock_send_packet() -> Generator[MagicMock]:
    """Replace the blocking APRS-IS send with a mock."""
    with patch("custom_components.aprs_send.sender.send_packet") as mock:
        yield mock


@pytest.fixture
def mock_test_connection() -> Generator[MagicMock]:
    """Replace the blocking APRS-IS test login with a mock."""
    with patch("custom_components.aprs_send.config_flow.test_connection") as mock:
        yield mock
