import asyncio
from typing import Final

import pytest
from pydantic import JsonValue, TypeAdapter

import litellm
from litellm.router_utils.add_retry_fallback_headers import get_hidden_params_dict
from litellm.types.utils import ModelResponse
from tests.test_litellm_rust.support.recording_server import RecordingServer, ResponseSpec

pytestmark = pytest.mark.requires_rust_extension
_OBJECT: Final = TypeAdapter(dict[str, object])
_RESPONSE: Final[dict[str, JsonValue]] = {
    "id": "chatcmpl-native-test",
    "object": "chat.completion",
    "created": 1,
    "model": "local-model",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", (False, True))
@pytest.mark.parametrize("provider", ("openai_like", "openai"))
async def test_public_chat_respects_native_provider_boundary(
    recording_server: RecordingServer,
    monkeypatch: pytest.MonkeyPatch,
    asynchronous: bool,
    provider: str,
) -> None:
    monkeypatch.setenv("LITELLM_RUST", "true")
    recording_server.default_response = ResponseSpec(body=_RESPONSE)
    kwargs: Final = {
        "model": "local-model",
        "custom_llm_provider": provider,
        "api_base": f"{recording_server.base_url}/v1",
        "api_key": "test-key",
        "messages": [{"role": "user", "content": "hello"}],
        "max_tokens": 16,
    }
    response: Final = (
        await litellm.acompletion(**kwargs) if asynchronous else await asyncio.to_thread(litellm.completion, **kwargs)
    )
    assert isinstance(response, ModelResponse)
    assert response.choices[0].message.content == "hello"
    headers: Final = _OBJECT.validate_python(get_hidden_params_dict(response).get("additional_headers", {}))
    assert (headers.get("x-litellm-rust") == "true") is (provider == "openai_like")
    assert len(recording_server.requests) == 1
    sent: Final = recording_server.requests[0]
    assert sent.path == "/v1/chat/completions"
    body: Final = _OBJECT.validate_python(sent.body)
    assert body["model"] == "local-model"
    assert body["max_tokens"] == 16


@pytest.mark.asyncio
async def test_native_openai_like_http_error_does_not_replay_on_python(
    recording_server: RecordingServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LITELLM_RUST", "true")
    recording_server.default_response = ResponseSpec(
        status=429, body={"error": {"message": "test rate limit", "type": "rate_limit_error"}}
    )
    with pytest.raises(litellm.RateLimitError):
        await litellm.acompletion(
            model="local-model",
            custom_llm_provider="openai_like",
            api_base=f"{recording_server.base_url}/v1",
            api_key="test-key",
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=16,
            num_retries=0,
        )
    assert len(recording_server.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("unsupported", ("tools", "stream"))
async def test_unsupported_requests_fail_before_sending_a_request(
    recording_server: RecordingServer, monkeypatch: pytest.MonkeyPatch, unsupported: str
) -> None:
    monkeypatch.setenv("LITELLM_RUST", "true")
    recording_server.default_response = ResponseSpec(body=_RESPONSE)
    recording_server.expected_requests = 0
    options: Final = (
        {"stream": True}
        if unsupported == "stream"
        else {"tools": [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}]}
    )
    with pytest.raises(litellm.APIConnectionError, match="unsupported by the rust path"):
        await litellm.acompletion(
            model="local-model",
            custom_llm_provider="openai_like",
            api_base=f"{recording_server.base_url}/v1",
            api_key="test-key",
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=16,
            **options,
        )
    assert not recording_server.requests
