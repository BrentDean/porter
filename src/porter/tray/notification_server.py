from __future__ import annotations

import os
import socket
from collections.abc import Callable
from pathlib import Path

from PySide6.QtNetwork import QLocalServer, QLocalSocket

from porter.notifications import (
    TrayNotificationRequest,
    decode_tray_notification,
)


class TrayNotificationServer:
    """Receive local reminder presentation requests from Porter service."""

    def __init__(
        self,
        socket_path: Path,
        on_notification: Callable[[TrayNotificationRequest], None],
    ) -> None:
        self._socket_path = Path(socket_path)
        self._on_notification = on_notification
        self._server = QLocalServer()
        self._buffers: dict[QLocalSocket, bytearray] = {}

    @property
    def socket_path(self) -> Path:
        return self._socket_path

    def start(self) -> None:
        self._socket_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        os.chmod(self._socket_path.parent, 0o700)

        if self._socket_path.exists():
            if self._socket_is_active():
                raise RuntimeError("another Porter tray notification server is running")
            QLocalServer.removeServer(str(self._socket_path))

        self._server.newConnection.connect(self._accept_pending)
        if not self._server.listen(str(self._socket_path)):
            raise RuntimeError(
                f"could not listen for Porter tray notifications: {self._server.errorString()}"
            )

    def close(self) -> None:
        for client in tuple(self._buffers):
            client.abort()
        self._buffers.clear()
        self._server.close()
        QLocalServer.removeServer(str(self._socket_path))

    def _socket_is_active(self) -> bool:
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.settimeout(0.2)
        try:
            probe.connect(str(self._socket_path))
        except OSError:
            return False
        finally:
            probe.close()
        return True

    def _accept_pending(self) -> None:
        while self._server.hasPendingConnections():
            client = self._server.nextPendingConnection()
            if client is None:
                continue
            self._buffers[client] = bytearray()
            client.readyRead.connect(lambda client=client: self._read_client(client))
            client.disconnected.connect(
                lambda client=client: self._buffers.pop(client, None)
            )
            if client.bytesAvailable():
                self._read_client(client)

    def _read_client(self, client: QLocalSocket) -> None:
        buffer = self._buffers.get(client)
        if buffer is None:
            return
        buffer.extend(bytes(client.readAll()))
        if b"\n" not in buffer:
            return

        payload, _, _remaining = bytes(buffer).partition(b"\n")
        try:
            request = decode_tray_notification(payload)
            self._on_notification(request)
        except (RuntimeError, ValueError):
            client.write(b"ERROR\n")
        else:
            client.write(b"OK\n")
        client.flush()
        client.disconnectFromServer()
