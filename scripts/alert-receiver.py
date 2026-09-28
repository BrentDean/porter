#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from typing import Any

_MAX_EVENTS = 1000
_EVENTS: list[dict[str, Any]] = []
_EVENTS_LOCK = Lock()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class AlertReceiverHandler(BaseHTTPRequestHandler):
    server_version = "PorterAlertReceiver/1.0"

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._write_json(HTTPStatus.OK, {"status": "ok"})
            return

        if self.path == "/events":
            with _EVENTS_LOCK:
                events = list(_EVENTS)
            self._write_json(HTTPStatus.OK, {"events": events})
            return

        self._write_json(HTTPStatus.NOT_FOUND, {"detail": "not found"})

    def do_POST(self) -> None:
        if self.path == "/reset":
            with _EVENTS_LOCK:
                _EVENTS.clear()
            self._write_json(HTTPStatus.OK, {"status": "reset"})
            return

        if self.path != "/alerts":
            self._write_json(HTTPStatus.NOT_FOUND, {"detail": "not found"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length)
            payload = json.loads(raw_body)
        except ValueError:
            self._write_json(HTTPStatus.BAD_REQUEST, {"detail": "invalid JSON"})
            return

        if not isinstance(payload, dict):
            self._write_json(
                HTTPStatus.BAD_REQUEST,
                {"detail": "Alertmanager webhook payload must be an object"},
            )
            return

        with _EVENTS_LOCK:
            _EVENTS.append(
                {
                    "received_at": _utc_now(),
                    "payload": payload,
                }
            )
            del _EVENTS[:-_MAX_EVENTS]

        self._write_json(HTTPStatus.ACCEPTED, {"status": "accepted"})

    def log_message(self, format: str, *args: object) -> None:
        return

    def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Receive and expose Alertmanager webhook events for local drills."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=9087, type=int)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), AlertReceiverHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
