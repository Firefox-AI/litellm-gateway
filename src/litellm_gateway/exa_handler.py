"""Use the OpenAI SDK to preserve Exa citations on LiteLLM 1.84.4.

The SDK handles HTTP/SSE; LiteLLM handles the resulting generic stream.
Citation-only deltas survive through provider_specific_fields.
"""

from contextlib import contextmanager

import httpx
import litellm
import openai
from litellm.llms.custom_httpx.http_handler import (
    _get_httpx_client,
    get_async_httpx_client,
)
from litellm.llms.custom_llm import CustomLLM
from litellm.secret_managers.main import get_secret_str
from litellm.types.utils import GenericStreamingChunk, ModelResponse

from litellm_gateway.config import EXA_DEFAULT_API_BASE, EXA_DEFAULT_TIMEOUT

PROVIDER = "exa_citations"


def _client(api_base, api_key, kwargs, *, asynchronous=False):
    key = api_key or get_secret_str("EXA_API_KEY")
    if not key:
        raise litellm.APIError(
            status_code=401,
            message="Exa requires EXA_API_KEY or api_key",
            model="exa",
            llm_provider=PROVIDER,
        )
    transport = kwargs.get("client")
    if transport is None:
        transport = (
            get_async_httpx_client(llm_provider=litellm.LlmProviders.CUSTOM_OPENAI)
            if asynchronous
            else _get_httpx_client()
        ).client
    sdk = openai.AsyncOpenAI if asynchronous else openai.OpenAI
    # LiteLLM owns the pooled transport and retries. Close individual streams,
    # not the SDK client (which would also close the shared transport).
    return sdk(
        api_key=key,
        base_url=api_base or EXA_DEFAULT_API_BASE,
        http_client=transport,
        max_retries=0,
        timeout=kwargs.get("timeout") or EXA_DEFAULT_TIMEOUT,
        default_headers=kwargs.get("headers"),
        _strict_response_validation=True,
    )


def _params(model, messages, optional_params, stream):
    params = dict(optional_params or {})
    params.pop("max_retries", None)
    return {**params, "model": model, "messages": messages, "stream": stream}


def _fields(delta):
    fields = dict(getattr(delta, "provider_specific_fields", None) or {})
    if "citations" in delta.model_fields_set:
        fields["citations"] = delta.citations
    return fields or None


def _completion(response):
    if not response.choices:
        raise ValueError("Exa returned no completion choices")
    raw = response.model_dump()
    for choice, raw_choice in zip(response.choices, raw["choices"]):
        raw_choice["message"].pop("citations", None)
        raw_choice["message"]["provider_specific_fields"] = _fields(choice.message)
    return ModelResponse(**raw)


def _chunks(chunk):
    usage = chunk.usage.model_dump() if chunk.usage else None
    if not chunk.choices and usage is not None:
        yield GenericStreamingChunk(
            text="",
            tool_use=None,
            is_finished=False,
            finish_reason="",
            usage=usage,
            index=0,
        )
    for i, choice in enumerate(chunk.choices):
        yield GenericStreamingChunk(
            text=choice.delta.content or "",
            tool_use=None,
            is_finished=choice.finish_reason is not None,
            finish_reason=choice.finish_reason or "",
            usage=usage if i == 0 else None,
            index=choice.index,
            provider_specific_fields=_fields(choice.delta),
        )


@contextmanager
def _errors(model):
    # CustomLLMError loses HTTP status in LiteLLM 1.84.4; use LiteLLM errors.
    try:
        yield
    except (openai.APITimeoutError, httpx.TimeoutException) as exc:
        raise litellm.Timeout(
            message="Exa request timed out", model=model, llm_provider=PROVIDER
        ) from exc
    except (openai.APIConnectionError, httpx.RequestError) as exc:
        raise litellm.APIConnectionError(
            message="Could not connect to Exa", model=model, llm_provider=PROVIDER
        ) from exc
    except openai.APIStatusError as exc:
        if exc.status_code == 429:
            raise litellm.RateLimitError(
                message="Exa rejected the request",
                model=model,
                llm_provider=PROVIDER,
                response=exc.response,
            ) from exc
        raise litellm.APIError(
            status_code=exc.status_code,
            message="Exa rejected the request",
            model=model,
            llm_provider=PROVIDER,
        ) from exc
    except (openai.APIError, ValueError, TypeError) as exc:
        raise litellm.APIError(
            status_code=502,
            message="Exa returned an invalid response",
            model=model,
            llm_provider=PROVIDER,
        ) from exc


class ExaLLM(CustomLLM):
    def completion(self, model, messages, api_base, api_key, optional_params, **kwargs):
        with _errors(model):
            client = _client(api_base, api_key, kwargs)
            return _completion(
                client.chat.completions.create(
                    **_params(model, messages, optional_params, False)
                )
            )

    async def acompletion(
        self, model, messages, api_base, api_key, optional_params, **kwargs
    ):
        with _errors(model):
            client = _client(api_base, api_key, kwargs, asynchronous=True)
            return _completion(
                await client.chat.completions.create(
                    **_params(model, messages, optional_params, False)
                )
            )

    def streaming(self, model, messages, api_base, api_key, optional_params, **kwargs):
        with _errors(model):
            client = _client(api_base, api_key, kwargs)
            with client.chat.completions.create(
                **_params(model, messages, optional_params, True)
            ) as stream:
                for chunk in stream:
                    yield from _chunks(chunk)

    async def astreaming(
        self, model, messages, api_base, api_key, optional_params, **kwargs
    ):
        with _errors(model):
            client = _client(api_base, api_key, kwargs, asynchronous=True)
            async with await client.chat.completions.create(
                **_params(model, messages, optional_params, True)
            ) as stream:
                async for chunk in stream:
                    for result in _chunks(chunk):
                        yield result


exa_llm = ExaLLM()
