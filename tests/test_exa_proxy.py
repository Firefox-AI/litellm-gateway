"""One smoke test through a real LiteLLM proxy and a loopback Exa server."""

import json
import os
import socket
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import httpx
from support import (
    API_KEY,
    CITATIONS,
    MESSAGES,
    PACKAGE_DIR,
    citation_deltas,
    event,
    json_response,
    loopback_only,
    mock_exa,
    sse,
    text_from,
)


def respond(body):
    if body.get("stream"):
        wire = sse(
            [
                event({"content": "Answer"}),
                event({"content": "", "citations": CITATIONS}),
            ]
        )
        return 200, "text/event-stream", wire
    return 200, "application/json", json.dumps(json_response()).encode()


def proxy_config(upstream):
    return {
        "model_list": [
            {
                "model_name": "exa",
                "litellm_params": {
                    "model": "exa_citations/exa",
                    "api_key": API_KEY,
                    "api_base": upstream,
                    "timeout": 10,
                    "num_retries": 0,
                },
            }
        ],
        "litellm_settings": {
            "custom_provider_map": [
                {
                    "provider": "exa_citations",
                    "custom_handler": "litellm_gateway.exa_handler.exa_llm",
                }
            ],
            "callbacks": ["litellm_gateway.custom_callbacks.proxy_handler_instance"],
        },
    }


def wait_ready(client, process, log):
    deadline = time.monotonic() + 90
    while process.poll() is None and time.monotonic() < deadline:
        try:
            if client.get("/health/liveliness").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    log.seek(0)
    raise AssertionError("LiteLLM did not become ready: " + log.read())


@contextmanager
def proxy():
    with TemporaryDirectory() as directory, mock_exa(respond) as (upstream, requests):
        tmp_path = Path(directory)
        config = tmp_path / "config.yaml"
        config.write_text(json.dumps(proxy_config(upstream)))
        # LiteLLM resolves handlers beside its config; use the package in the image.
        (tmp_path / "litellm_gateway").symlink_to(PACKAGE_DIR, target_is_directory=True)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        # Do not inherit database URLs or provider credentials from the shell.
        env = {
            key: os.environ[key]
            for key in ("PATH", "HOME", "TMPDIR")
            if key in os.environ
        }
        env.update(
            PYTHONPATH=str(PACKAGE_DIR.parent),
            LITELLM_LOG="ERROR",
            LITELLM_LOCAL_MODEL_COST_MAP="True",
            DO_NOT_TRACK="True",
        )
        with (tmp_path / "proxy.log").open("w+") as log:
            process = subprocess.Popen(
                ["litellm", "--config", str(config), "--port", str(port)],
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                with httpx.Client(
                    base_url=f"http://127.0.0.1:{port}",
                    timeout=10,
                    trust_env=False,
                ) as client:
                    wait_ready(client, process, log)
                    yield client, requests
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


class ExaProxyTests(TestCase):
    def setUp(self):
        self.enterContext(loopback_only())

    def test_proxy(self):
        with proxy() as (client, requests):
            url = "/v1/chat/completions"
            body = {"model": "exa", "messages": MESSAGES}
            response = client.post(url, json=body)
            self.assertEqual(response.status_code, 200, response.text)
            message = response.json()["choices"][0]["message"]
            self.assertEqual(message["content"], "Answer")
            self.assertEqual(
                message["provider_specific_fields"]["citations"], CITATIONS
            )

            chunks, done = [], False
            with client.stream("POST", url, json={**body, "stream": True}) as response:
                response.raise_for_status()
                self.assertTrue(
                    response.headers["content-type"].startswith("text/event-stream")
                )
                for line in response.iter_lines():
                    if line == "data: [DONE]":
                        done = True
                    elif line.startswith("data: "):
                        chunks.append(json.loads(line[6:]))
            self.assertTrue(done, "Missing [DONE]")
            self.assertEqual(text_from(chunks), "Answer")
            self.assertEqual(citation_deltas(chunks), [CITATIONS])
            self.assertTrue(
                any(
                    choice.get("finish_reason") == "stop"
                    for chunk in chunks
                    for choice in chunk.get("choices", [])
                ),
                "Missing stop",
            )
            self.assertEqual(len(requests), 2)
            for path, headers, request in requests:
                self.assertEqual(path, "/chat/completions")
                self.assertEqual(request["model"], "exa")
                self.assertEqual(headers["authorization"], f"Bearer {API_KEY}")
                self.assertEqual(request["messages"], MESSAGES)
            self.assertEqual(
                [request["stream"] for _, _, request in requests], [False, True]
            )
