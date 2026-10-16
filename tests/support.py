"""Synthetic provider responses and a loopback Exa server."""

import json
import socket
import threading
from contextlib import ExitStack, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import litellm_gateway

PACKAGE_DIR = Path(litellm_gateway.__file__).parent

CITATIONS = [
    {
        "id": "source-1",
        "url": "https://example.org/one",
        "title": "Quantum 🔬",
        "author": "Author",
    },
    {"id": "source-2", "url": "https://example.org/two", "title": "Second source"},
]
USAGE = {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12}
MESSAGES = [{"role": "user", "content": "Replay"}]
API_KEY = "dummy-replay-key"  # pragma: allowlist secret


@contextmanager
def loopback_only():
    """Fail accidental outbound connections in this test process."""
    with ExitStack() as stack:
        for method in ("connect", "connect_ex"):
            original = getattr(socket.socket, method)

            def connect(sock, address, _original=original):
                if sock.family in (socket.AF_INET, socket.AF_INET6):
                    if address[0] not in {"127.0.0.1", "::1", "localhost"}:
                        raise AssertionError(
                            f"Tests may only connect to loopback, got {address[0]}"
                        )
                return _original(sock, address)

            stack.enter_context(patch.object(socket.socket, method, connect))
        yield


def event(delta, finish=None):
    return {
        "id": "replay-stream",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "exa",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


def json_response():
    return {
        "id": "replay-json",
        "object": "chat.completion",
        "created": 1,
        "model": "exa",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "Answer",
                    "citations": CITATIONS,
                },
            }
        ],
        "usage": USAGE,
    }


def sse(events):
    return (
        "".join("data: " + json.dumps(e, ensure_ascii=False) + "\n\n" for e in events)
        + "data: [DONE]\n\n"
    ).encode()


def text_from(events):
    return "".join(
        choice.get("delta", {}).get("content") or ""
        for item in events
        for choice in item.get("choices", [])
    )


def citation_deltas(events):
    return [
        fields["citations"]
        for item in events
        for choice in item.get("choices", [])
        if (fields := choice.get("delta", {}).get("provider_specific_fields") or {})
        and "citations" in fields
    ]


@contextmanager
def mock_exa(respond):
    """Serve respond(body) -> (status, content_type, bytes), recording each request."""
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(
                (
                    self.path,
                    {key.lower(): value for key, value in self.headers.items()},
                    body,
                )
            )
            status, content_type, wire = respond(body)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(wire)))
            self.end_headers()
            self.wfile.write(wire)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
