"""Local-only SMTP plus Inbox HTTP sidecar for deterministic Harbor tasks."""

from __future__ import annotations

import email
import html
import json
import os
import re
import socket
import socketserver
import signal
import sys
import threading
import urllib.parse
from dataclasses import dataclass, field
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


_NAMESPACE = re.compile(r"^[a-zA-Z0-9._-]{1,160}$")
_OTP = re.compile(r"(?<!\d)(\d{4,8})(?!\d)")
_MAX_MESSAGE_BYTES = 1024 * 1024
_MAX_MESSAGES_PER_NAMESPACE = 32
_MAX_STORED_BYTES_PER_NAMESPACE = 2 * 1024 * 1024
_MAX_RECIPIENTS = 16
_MAX_COMMANDS_PER_CONNECTION = 256
_CONNECTION_TIMEOUT_SECONDS = 10
_MAX_CONNECTION_LIFETIME_SECONDS = 30
_MAX_CONCURRENT_CONNECTIONS = 16
_LOG_SECRET = re.compile(
    r"(?i)(?:bearer\s+[^\s\"']+|"
    r"(?:authorization|cookie|credential|password|secret|token|otp|"
    r"verification[-_ ]?code|card[-_ ]?number)\s*[:=]\s*"
    r"(?:bearer\s+)?[^\s,;]+)"
)


def redact_text(value: str) -> str:
    """Redact secret-like log fragments without retaining the matched value."""

    return _LOG_SECRET.sub("[REDACTED]", value)


def redact_log_file(path: str) -> None:
    """Sanitize one UTF-8 verifier log in place before it is published."""

    from pathlib import Path

    target = Path(path)
    if not target.is_file():
        return
    value = target.read_text(encoding="utf-8", errors="replace")
    target.write_text(redact_text(value), encoding="utf-8", newline="\n")


def redact_evidence(value: Any) -> Any:
    """Remove credentials and sensitive form values from retained evidence."""

    sensitive = re.compile(
        r"(?:authorization|cookie|credential|password|secret|token|otp|code|payment|card)",
        re.IGNORECASE,
    )
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]"
            if sensitive.search(str(key))
            else redact_evidence(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [redact_evidence(child) for child in value]
    return value


@dataclass
class MailboxStore:
    _messages: list[dict[str, Any]] = field(default_factory=list)
    _capabilities: dict[str, str] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def register(self, namespace: str, capability: str) -> None:
        if not _NAMESPACE.fullmatch(namespace) or len(capability) < 32:
            raise ValueError("invalid mailbox namespace capability")
        with self._lock:
            existing = self._capabilities.get(namespace)
            if existing is not None and existing != capability:
                raise ValueError("mailbox namespace is already registered")
            self._capabilities[namespace] = capability

    def authorized(self, namespace: str, capability: str | None) -> bool:
        import hmac

        with self._lock:
            expected = self._capabilities.get(namespace)
        return (
            expected is not None
            and capability is not None
            and hmac.compare_digest(expected, capability)
        )

    def deliver(self, raw: bytes, envelope_from: str, recipients: list[str]) -> bool:
        message = email.message_from_bytes(raw, policy=default)
        namespace = str(message.get("X-WebsiteBench-Namespace", "default"))
        capability = str(message.get("X-WebsiteBench-Capability", ""))
        if not _NAMESPACE.fullmatch(namespace) or not self.authorized(
            namespace, capability
        ):
            return False
        if message.is_multipart():
            text = "\n".join(
                str(part.get_content())
                for part in message.walk()
                if part.get_content_type() == "text/plain"
                and part.get_content_disposition() != "attachment"
            )
        else:
            text = str(message.get_content())
        match = _OTP.search(text)
        with self._lock:
            existing = [
                item for item in self._messages if item["namespace"] == namespace
            ]
            stored_bytes = sum(int(item["stored_bytes"]) for item in existing)
            message_bytes = len(text.encode("utf-8", "replace"))
            if (
                len(existing) >= _MAX_MESSAGES_PER_NAMESPACE
                or stored_bytes + message_bytes > _MAX_STORED_BYTES_PER_NAMESPACE
            ):
                return False
            self._messages.append(
                {
                    "id": len(self._messages) + 1,
                    "namespace": namespace,
                    "envelope_from": envelope_from,
                    "recipients": recipients,
                    "subject": str(message.get("Subject", "")),
                    "text": text,
                    "otp": match.group(1) if match else None,
                    "stored_bytes": message_bytes,
                }
            )
        return True

    def messages(
        self, namespace: str, recipient: str | None = None
    ) -> list[dict[str, Any]]:
        with self._lock:
            values = [
                item.copy() for item in self._messages if item["namespace"] == namespace
            ]
        if recipient:
            values = [item for item in values if recipient in item["recipients"]]
        for item in values:
            item.pop("stored_bytes", None)
        return values


class _SmtpHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        timer = threading.Timer(
            _MAX_CONNECTION_LIFETIME_SECONDS, self._expire_connection
        )
        timer.daemon = True
        timer.start()
        try:
            self._handle_session()
        finally:
            timer.cancel()

    def _expire_connection(self) -> None:
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def _handle_session(self) -> None:
        store: MailboxStore = self.server.store  # type: ignore[attr-defined]
        self.connection.settimeout(_CONNECTION_TIMEOUT_SECONDS)
        self.wfile.write(b"220 websitebench.local ESMTP\r\n")
        envelope_from = ""
        recipients: list[str] = []
        for _command_count in range(_MAX_COMMANDS_PER_CONNECTION):
            try:
                line = self.rfile.readline(65537)
            except (TimeoutError, socket.timeout):
                return
            if not line:
                return
            if len(line) > 65536:
                self.wfile.write(b"500 Command line too long\r\n")
                return
            command = line.decode("utf-8", "replace").rstrip("\r\n")
            upper = command.upper()
            if upper.startswith(("EHLO", "HELO")):
                self.wfile.write(
                    b"250-websitebench.local\r\n250 SIZE 1048576\r\n"
                )
            elif upper.startswith("MAIL FROM:"):
                envelope_from = command.split(":", 1)[1].strip().strip("<>")
                recipients = []
                self.wfile.write(b"250 OK\r\n")
            elif upper.startswith("RCPT TO:"):
                if len(recipients) >= _MAX_RECIPIENTS:
                    self.wfile.write(b"452 Too many recipients\r\n")
                    continue
                recipients.append(command.split(":", 1)[1].strip().strip("<>"))
                self.wfile.write(b"250 OK\r\n")
            elif upper == "DATA":
                self.wfile.write(b"354 End data with <CR><LF>.<CR><LF>\r\n")
                chunks = bytearray()
                oversized = False
                while True:
                    try:
                        data_line = self.rfile.readline(65537)
                    except (TimeoutError, socket.timeout):
                        return
                    if data_line in {b".\r\n", b".\n", b""}:
                        break
                    if len(data_line) > 65536:
                        oversized = True
                    value = data_line[1:] if data_line.startswith(b"..") else data_line
                    if len(chunks) + len(value) > _MAX_MESSAGE_BYTES:
                        oversized = True
                    elif not oversized:
                        chunks.extend(value)
                if oversized:
                    self.wfile.write(b"552 Message exceeds fixed local limit\r\n")
                    continue
                accepted = store.deliver(bytes(chunks), envelope_from, recipients)
                self.wfile.write(
                    b"250 Stored locally\r\n"
                    if accepted
                    else b"550 Invalid namespace capability\r\n"
                )
            elif upper == "RSET":
                envelope_from, recipients = "", []
                self.wfile.write(b"250 OK\r\n")
            elif upper == "NOOP":
                self.wfile.write(b"250 OK\r\n")
            elif upper == "QUIT":
                self.wfile.write(b"221 Bye\r\n")
                return
            else:
                self.wfile.write(b"502 Command not implemented\r\n")
        self.wfile.write(b"421 Command limit exceeded\r\n")


class _SmtpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], store: MailboxStore) -> None:
        self.store = store
        self._connection_slots = threading.BoundedSemaphore(
            _MAX_CONCURRENT_CONNECTIONS
        )
        super().__init__(address, _SmtpHandler)

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self._connection_slots.acquire(blocking=False):
            request.close()
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._connection_slots.release()


class _HttpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], handler: Any) -> None:
        self._connection_slots = threading.BoundedSemaphore(
            _MAX_CONCURRENT_CONNECTIONS
        )
        super().__init__(address, handler)

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self._connection_slots.acquire(blocking=False):
            request.close()
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        def expire() -> None:
            try:
                request.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        timer = threading.Timer(_MAX_CONNECTION_LIFETIME_SECONDS, expire)
        timer.daemon = True
        timer.start()
        try:
            request.settimeout(_CONNECTION_TIMEOUT_SECONDS)
            super().process_request_thread(request, client_address)
        finally:
            timer.cancel()
            self._connection_slots.release()


def _http_handler(store: MailboxStore) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _authorized(self, namespace: str) -> bool:
            prefix = "Bearer "
            header = self.headers.get("Authorization", "")
            capability = header[len(prefix) :] if header.startswith(prefix) else None
            if store.authorized(namespace, capability):
                return True
            self._json(403, {"error": "forbidden"})
            return False

        def _json(self, status: int, value: Any) -> None:
            body = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path == "/healthz":
                self._json(200, {"status": "ok"})
                return
            parts = parsed.path.strip("/").split("/")
            if (
                len(parts) >= 4
                and parts[:2] == ["api", "namespaces"]
                and parts[3] == "messages"
            ):
                namespace = urllib.parse.unquote(parts[2])
                if not _NAMESPACE.fullmatch(namespace):
                    self._json(400, {"error": "invalid_namespace"})
                    return
                if not self._authorized(namespace):
                    return
                recipient = urllib.parse.parse_qs(parsed.query).get(
                    "recipient", [None]
                )[0]
                values = store.messages(namespace, recipient)
                if len(parts) == 5 and parts[4] == "latest":
                    if not values:
                        self._json(404, {"error": "message_not_found"})
                    else:
                        self._json(200, values[-1])
                else:
                    self._json(200, {"messages": values})
                return
            if len(parts) == 2 and parts[0] == "inbox":
                namespace = urllib.parse.unquote(parts[1])
                if not _NAMESPACE.fullmatch(namespace):
                    self._json(400, {"error": "invalid_namespace"})
                    return
                if not self._authorized(namespace):
                    return
                values = store.messages(namespace)
                rows = "".join(
                    f"<article><h2>{html.escape(item['subject'])}</h2>"
                    f"<pre>{html.escape(item['text'])}</pre></article>"
                    for item in values
                )
                body = (
                    "<!doctype html><meta charset=utf-8><title>Local Inbox</title>"
                    + rows
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._json(404, {"error": "not_found"})

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


class LocalMailboxSidecar:
    """A loopback-only SMTP and Inbox API pair with namespace isolation."""

    def __init__(
        self, *, smtp_port: int = 0, http_port: int = 0, bind_host: str = "127.0.0.1"
    ) -> None:
        self.store = MailboxStore()
        self.smtp = _SmtpServer((bind_host, smtp_port), self.store)
        self.http = _HttpServer(
            (bind_host, http_port), _http_handler(self.store)
        )
        self._threads: list[threading.Thread] = []

    @property
    def smtp_port(self) -> int:
        return int(self.smtp.server_address[1])

    @property
    def http_port(self) -> int:
        return int(self.http.server_address[1])

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.http_port}"

    def register_namespace(self, namespace: str, capability: str) -> None:
        """Bind one opaque namespace to its unguessable per-worker capability."""

        self.store.register(namespace, capability)

    def start(self) -> "LocalMailboxSidecar":
        for server in (self.smtp, self.http):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self._threads.append(thread)
        return self

    def close(self) -> None:
        for server in (self.smtp, self.http):
            server.shutdown()
            server.server_close()
        for thread in self._threads:
            thread.join(timeout=5)
        self._threads.clear()

    def __enter__(self) -> "LocalMailboxSidecar":
        return self.start()

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="websitebench-local-mailbox")
    parser.add_argument("--smtp-port", type=int, default=1025)
    parser.add_argument("--http-port", type=int, default=8025)
    parser.add_argument("--bind-host", default="127.0.0.1")
    args = parser.parse_args(argv)
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda _signum, _frame: stopped.set())
    signal.signal(signal.SIGINT, lambda _signum, _frame: stopped.set())
    sidecar = LocalMailboxSidecar(
        smtp_port=args.smtp_port,
        http_port=args.http_port,
        bind_host=args.bind_host,
    ).start()
    initial_namespace = os.environ.get("WEBSITEBENCH_MAILBOX_INITIAL_NAMESPACE")
    initial_capability = os.environ.get("WEBSITEBENCH_MAILBOX_INITIAL_CAPABILITY")
    if initial_namespace or initial_capability:
        if not initial_namespace or not initial_capability:
            sidecar.close()
            raise SystemExit("both initial mailbox capability values are required")
        sidecar.register_namespace(initial_namespace, initial_capability)
    try:
        stopped.wait()
    finally:
        sidecar.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
