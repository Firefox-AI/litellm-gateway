"""SDK decoding, errors, retries, and resource ownership at the adapter boundary."""

import json
from contextlib import asynccontextmanager
from itertools import product
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

import httpx
import litellm
from support import API_KEY, CITATIONS, event, loopback_only, sse

from litellm_gateway import exa_handler

PARAMS = dict(
    model="exa",
    messages=[],
    api_base="http://example.invalid",
    api_key=API_KEY,
    optional_params={},
)


class Wire(httpx.SyncByteStream, httpx.AsyncByteStream):
    def __init__(self, data, failure=None):
        self.data, self.failure, self.closed = data, failure, False

    def __iter__(self):
        # Exercise UTF-8 and SSE fields split across network reads.
        for byte in self.data:
            yield bytes([byte])
        if self.failure:
            raise self.failure("broken stream")

    async def __aiter__(self):
        for part in self:
            yield part

    def close(self):
        self.closed = True

    async def aclose(self):
        self.close()


@asynccontextmanager
async def transport(asynchronous):
    state = SimpleNamespace(error=None, status=200, wire=None, calls=0)

    def respond(request):
        state.calls += 1
        if state.error:
            raise state.error("request failed", request=request)
        return httpx.Response(
            state.status,
            stream=state.wire,
            headers={"content-type": "text/event-stream"},
        )

    client_type = httpx.AsyncClient if asynchronous else httpx.Client
    client = client_type(transport=httpx.MockTransport(respond))
    try:
        yield client, state
    finally:
        if asynchronous:
            await client.aclose()
        else:
            client.close()


def stream_for(client):
    handler = exa_handler.exa_llm
    method = (
        handler.astreaming
        if isinstance(client, httpx.AsyncClient)
        else handler.streaming
    )
    return method(**PARAMS, client=client)


async def collect(client, streaming=True):
    handler = exa_handler.exa_llm
    if isinstance(client, httpx.AsyncClient):
        if streaming:
            return [chunk async for chunk in stream_for(client)]
        return await handler.acompletion(**PARAMS, client=client)
    if streaming:
        return list(stream_for(client))
    return handler.completion(**PARAMS, client=client)


PAYLOAD = json.dumps(event({"content": "", "citations": CITATIONS}), indent=2)
FORMATTED = (
    ": heartbeat\nevent: message\n"
    + "\n".join("data: " + line for line in PAYLOAD.splitlines())
    + "\n\ndata: [DONE]\n\n"
).encode()


class ExaTransportTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(loopback_only())

    async def test_request_error(self):
        errors = (
            (httpx.ReadTimeout, litellm.Timeout),
            (httpx.ConnectError, litellm.APIConnectionError),
        )
        for asynchronous, streaming, (error, expected) in product(
            (False, True), (False, True), errors
        ):
            with self.subTest(
                asynchronous=asynchronous, streaming=streaming, error=error.__name__
            ):
                async with transport(asynchronous) as (client, state):
                    state.error = error
                    with self.assertRaises(expected):
                        await collect(client, streaming)
                    self.assertEqual(state.calls, 1, "SDK must not retry")

    async def test_sse_decoding(self):
        for asynchronous, done in product((False, True), (False, True)):
            with self.subTest(asynchronous=asynchronous, done=done):
                async with transport(asynchronous) as (client, state):
                    data = (
                        FORMATTED
                        if done
                        else FORMATTED.removesuffix(b"data: [DONE]\n\n")
                    )
                    state.wire = Wire(data)
                    chunks = await collect(client)
                    self.assertEqual(len(chunks), 1)
                    self.assertEqual(
                        chunks[0]["provider_specific_fields"]["citations"], CITATIONS
                    )
                    self.assertEqual(state.calls, 1)
                    self.assertTrue(state.wire.closed)
                    self.assertFalse(client.is_closed)

    async def test_stream_error(self):
        cases = (
            ("invalid-JSON", 200, b"data: invalid\n\n", None, litellm.APIError),
            (
                "invalid-schema",
                200,
                b'data: {"choices": "invalid"}\n\n',
                None,
                litellm.APIError,
            ),
            (
                "in-band-error",
                200,
                b'data: {"error": {"message": "failed"}}\n\n',
                None,
                litellm.APIError,
            ),
            (
                "interrupted-stream",
                200,
                sse([event({"content": "Partial answer"})]).removesuffix(
                    b"data: [DONE]\n\n"
                ),
                httpx.RemoteProtocolError,
                litellm.APIConnectionError,
            ),
            (
                "rate-limit",
                429,
                b'{"error":{"message":"limited"}}',
                None,
                litellm.RateLimitError,
            ),
            (
                "unavailable",
                503,
                b'{"error":{"message":"unavailable"}}',
                None,
                litellm.APIError,
            ),
        )
        for asynchronous, (name, status, data, failure, expected) in product(
            (False, True), cases
        ):
            with self.subTest(asynchronous=asynchronous, case=name):
                async with transport(asynchronous) as (client, state):
                    state.status, state.wire = status, Wire(data, failure)
                    with self.assertRaises(expected) as caught:
                        await collect(client)
                    if expected in (litellm.APIError, litellm.RateLimitError):
                        self.assertEqual(
                            caught.exception.status_code,
                            status if status != 200 else 502,
                        )
                    self.assertEqual(state.calls, 1, "SDK must not retry")
                    self.assertTrue(state.wire.closed)
                    self.assertFalse(
                        client.is_closed, "Shared transport must remain reusable"
                    )

    async def test_early_close_preserves_shared_client(self):
        for asynchronous in (False, True):
            with self.subTest(asynchronous=asynchronous):
                async with transport(asynchronous) as (client, state):
                    state.wire = Wire(FORMATTED)
                    stream = stream_for(client)
                    if asynchronous:
                        await anext(stream)
                        await stream.aclose()
                    else:
                        next(stream)
                        stream.close()
                    self.assertTrue(state.wire.closed)
                    self.assertFalse(client.is_closed)

                    state.wire = Wire(FORMATTED)
                    chunks = await collect(client)
                    self.assertEqual(
                        chunks[0]["provider_specific_fields"]["citations"], CITATIONS
                    )
                    self.assertEqual(state.calls, 2)
                    self.assertTrue(state.wire.closed)
