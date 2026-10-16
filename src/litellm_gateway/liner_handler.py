"""Forward requests to liner quick answers & receive response

Liner quick answers follows a unique URL path, which is not supported by litellm.
"""

import json
from collections.abc import AsyncIterator, Iterator
from functools import lru_cache

import litellm
from litellm.llms.custom_httpx.http_handler import (
    AsyncHTTPHandler,
    HTTPHandler,
    _get_httpx_client,
    get_async_httpx_client,
)
from litellm.llms.custom_llm import CustomLLM, CustomLLMError
from litellm.secret_managers.main import get_secret_str
from litellm.types.utils import GenericStreamingChunk, ModelResponse

from litellm_gateway.config import (
    LINER_COST_PER_REQUEST,
    LINER_DEFAULT_API_BASE,
    LINER_DEFAULT_TIMEOUT,
)

LINER_ROLES = ("user", "assistant")


def _resolve_api_base(api_base: str | None) -> str:
    return (
        api_base or get_secret_str("LINER_API_BASE") or LINER_DEFAULT_API_BASE
    ).rstrip("/")


@lru_cache(maxsize=1)
def _resolve_api_key(api_key: str | None) -> str:
    resolved = api_key or get_secret_str("LINER_API_KEY")
    if not resolved:
        raise CustomLLMError(
            status_code=401,
            message="Liner requires an API key. Set LINER_API_KEY or pass api_key.",
        )
    return resolved


def _resolve_headers(api_key: str | None, headers: dict | None = None) -> dict:
    return {
        **(headers or {}),
        "x-api-key": _resolve_api_key(api_key),
        "Content-Type": "application/json",
    }


def _transform_messages(messages: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split messages into Liner turns and the messages Liner cannot accept.

    Returns `(turns, dropped)`. Dropped entries keep their original index so the
    caller can tell the user exactly which messages were not sent.
    """
    system_parts: list[str] = []
    turns: list[dict] = []
    dropped: list[dict] = []

    for i, message in enumerate(messages):
        content = message.get("content", "")
        if isinstance(content, list):
            content = "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )

        role = message.get("role")
        if not content:
            dropped.append(
                {"role": role, "content": "", "index": i, "reason": "empty_content"}
            )
            continue

        if role == "system":
            system_parts.append(content)
        elif role in LINER_ROLES:
            turns.append({"role": role, "content": content})
        else:
            dropped.append(
                {
                    "role": role,
                    "content": content,
                    "index": i,
                    "reason": "unsupported_role",
                }
            )

    # Liner 502s on the `system` role, so system content leads as a user turn.
    if system_parts:
        turns.insert(0, {"role": "user", "content": "\n\n".join(system_parts)})

    if not turns:
        raise CustomLLMError(
            status_code=400,
            message="Liner requires at least one user or assistant message.",
        )

    return turns, dropped


def _build_request(
    messages: list[dict],
    model: str,
    stream: bool = False,
    optional_params: dict | None = None,
) -> tuple[dict, list[dict]]:
    """Build the Liner request body, plus the messages that were left out of it."""
    params = {**(optional_params or {})}
    params.pop("stream", None)  # the explicit `stream` arg is authoritative
    extra_body = params.pop("extra_body", None) or {}
    turns, dropped = _transform_messages(messages)
    request_body = {
        **params,
        **extra_body,
        "messages": turns,
        "stream": stream,
        "model": model,
    }
    return request_body, dropped


def _to_generic_chunk(
    line: str, dropped: list[dict] | None = None
) -> GenericStreamingChunk | None:
    """Map one OpenAI-spec SSE chunk onto the GenericStreamingChunk that
    CustomStreamWrapper requires for custom providers."""
    if not line.startswith("data:"):
        return None
    payload = line[len("data:") :].strip()
    if not payload or payload == "[DONE]":
        return None

    try:
        raw = json.loads(payload)
    except Exception as e:
        raise CustomLLMError(
            status_code=500,
            message=f"Liner returned non-JSON: {e}. Body: {line[:500]}",
        )

    choice = (raw.get("choices") or [{}])[0]
    finish_reason = choice.get("finish_reason")
    is_finished = finish_reason is not None

    # Liner attaches `references` to the top level of its final chunk.
    references = raw.get("references")

    provider_specific_fields: dict = {}
    if references and isinstance(references, list):
        for reference in references:
            reference["favicon"] = reference.pop("faviconUrl", "")
            reference["image"] = reference.pop("imageUrl", "")

        provider_specific_fields["citations"] = references
    # Report dropped messages on the final chunk
    if is_finished and dropped:
        provider_specific_fields["dropped"] = dropped

    return GenericStreamingChunk(
        text=(choice.get("delta") or {}).get("content") or "",
        tool_use=None,
        is_finished=is_finished,
        finish_reason=finish_reason or "",
        usage=None,
        index=choice.get("index", 0),
        provider_specific_fields=provider_specific_fields or None,
    )


def _transform_response(
    response, model: str, dropped: list[dict], model_response: ModelResponse
) -> ModelResponse:
    try:
        raw = response.json()
    except Exception as e:
        raise CustomLLMError(
            status_code=500,
            message=f"Liner returned non-JSON: {e}. Body: {response.text[:500]}",
        )

    model_response.model = model
    model_response.choices[0].finish_reason = "stop"
    model_response._hidden_params["response_cost"] = LINER_COST_PER_REQUEST

    response_choices = raw.get("choices", [])
    response_references = raw.get("references")

    if len(response_choices) == 0:
        raise CustomLLMError(
            status_code=500,
            message="Liner quick answers did not return choices!",
        )

    response_content = response_choices[0].get("message", {}).get("content", "")
    if not response_content:
        raise CustomLLMError(
            status_code=500,
            message="Liner quick answers returned empty response!",
        )

    model_response.choices[0].message.content = response_content

    provider_specific_fields: dict = {}
    if response_references and isinstance(response_references, list):
        for reference in response_references:
            reference["favicon"] = reference.pop("faviconUrl", "")
            reference["image"] = reference.pop("imageUrl", "")

        provider_specific_fields["citations"] = response_references
    if dropped:
        provider_specific_fields["dropped"] = dropped

    if provider_specific_fields:
        model_response.choices[
            0
        ].message.provider_specific_fields = provider_specific_fields

    return model_response


class LinerLLM(CustomLLM):
    def completion(
        self,
        model: str,
        messages: list,
        api_base: str,
        custom_prompt_dict: dict,
        model_response: ModelResponse,
        print_verbose,
        encoding,
        api_key,
        logging_obj,
        optional_params: dict,
        acompletion=None,
        litellm_params=None,
        logger_fn=None,
        headers=None,
        timeout=None,
        client: HTTPHandler | None = None,
    ) -> ModelResponse:
        http_client = client or _get_httpx_client()
        request_body, dropped = _build_request(
            messages=messages,
            model=model,
            optional_params=optional_params,
        )
        response = http_client.post(
            url=_resolve_api_base(api_base),
            headers=_resolve_headers(api_key, headers),
            json=request_body,
            timeout=timeout or LINER_DEFAULT_TIMEOUT,
        )
        return _transform_response(response, model, dropped, model_response)

    async def acompletion(
        self,
        model: str,
        messages: list,
        api_base: str,
        custom_prompt_dict: dict,
        model_response: ModelResponse,
        print_verbose,
        encoding,
        api_key,
        logging_obj,
        optional_params: dict,
        acompletion=None,
        litellm_params=None,
        logger_fn=None,
        headers=None,
        timeout=None,
        client: AsyncHTTPHandler | None = None,
    ) -> ModelResponse:
        http_client = client or get_async_httpx_client(
            llm_provider=litellm.LlmProviders.CUSTOM_OPENAI
        )
        request_body, dropped = _build_request(
            messages=messages,
            model=model,
            optional_params=optional_params,
        )
        response = await http_client.post(
            url=_resolve_api_base(api_base),
            headers=_resolve_headers(api_key, headers),
            json=request_body,
            timeout=timeout or LINER_DEFAULT_TIMEOUT,
        )
        return _transform_response(response, model, dropped, model_response)

    def streaming(
        self,
        model: str,
        messages: list,
        api_base: str,
        custom_prompt_dict: dict,
        model_response: ModelResponse,
        print_verbose,
        encoding,
        api_key,
        logging_obj,
        optional_params: dict,
        acompletion=None,
        litellm_params=None,
        logger_fn=None,
        headers=None,
        timeout=None,
        client: HTTPHandler | None = None,
    ) -> Iterator[GenericStreamingChunk]:
        http_client = client or _get_httpx_client()
        request_body, dropped = _build_request(
            messages=messages,
            model=model,
            stream=True,
            optional_params=optional_params,
        )
        response = http_client.post(
            url=_resolve_api_base(api_base),
            headers=_resolve_headers(api_key, headers),
            json=request_body,
            timeout=timeout or LINER_DEFAULT_TIMEOUT,
            stream=True,
        )
        if response is None:
            raise Exception("Liner Streaming Response is None")
        for line in response.iter_lines():
            chunk = _to_generic_chunk(line, dropped)
            if chunk is not None:
                yield chunk

    async def astreaming(  # type: ignore[override]
        self,
        model: str,
        messages: list,
        api_base: str,
        custom_prompt_dict: dict,
        model_response: ModelResponse,
        print_verbose,
        encoding,
        api_key,
        logging_obj,
        optional_params: dict,
        acompletion=None,
        litellm_params=None,
        logger_fn=None,
        headers=None,
        timeout=None,
        client: AsyncHTTPHandler | None = None,
    ) -> AsyncIterator[GenericStreamingChunk]:
        http_client = client or get_async_httpx_client(
            llm_provider=litellm.LlmProviders.CUSTOM_OPENAI
        )
        request_body, dropped = _build_request(
            messages=messages,
            model=model,
            optional_params=optional_params,
            stream=True,
        )

        response = await http_client.post(
            url=_resolve_api_base(api_base),
            headers=_resolve_headers(api_key, headers),
            json=request_body,
            timeout=timeout or LINER_DEFAULT_TIMEOUT,
            stream=True,
        )
        if response is None:
            raise Exception("Liner Async Streaming Response is None")
        async for line in response.aiter_lines():
            chunk = _to_generic_chunk(line, dropped)
            if chunk is not None:
                yield chunk


liner_llm = LinerLLM()
