"""Allow Windows asyncio's local wake-up pipe while blocking ordinary sockets."""

import socket
import sys
from collections.abc import Iterator

import pytest

_SOCKET = socket.socket


@pytest.fixture(scope="session", autouse=True)
def test_environment() -> Iterator[None]:
    """Prevent unrelated host application flags from changing test configuration."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("APP_ENV", "test")
        patch.setenv("DEBUG", "false")
        yield


def _local_socketpair(
    family: int = socket.AF_INET, type: int = socket.SOCK_STREAM, proto: int = 0
) -> tuple[socket.socket, socket.socket]:
    # Python 3.11 on Windows emulates socketpair using loopback TCP. Keep this
    # capability limited to the pair constructor; socket.socket stays blocked.
    if family not in (socket.AF_INET, socket.AF_INET6) or type != socket.SOCK_STREAM or proto:
        raise ValueError("Only a local TCP wake-up pair is supported")
    host = "127.0.0.1" if family == socket.AF_INET else "::1"
    with _SOCKET(family, type, proto) as listener:
        listener.bind((host, 0))
        listener.listen(1)
        client = _SOCKET(family, type, proto)
        try:
            client.connect(listener.getsockname())
            descriptor, _ = listener._accept()
            server = _SOCKET(family, type, proto, fileno=descriptor)
            if server.getpeername() != client.getsockname():
                server.close()
                raise ConnectionError("Unexpected local wake-up peer")
            return server, client
        except BaseException:
            client.close()
            raise


@pytest.fixture(autouse=True)
def windows_asyncio_wakeup_pair(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    if sys.platform == "win32":
        monkeypatch.setattr(socket, "socketpair", _local_socketpair)
    yield
