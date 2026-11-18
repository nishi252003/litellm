# Experimental native chat for a local OpenAI-compatible backend

This branch targets LiteLLM v1.105.1. It opts explicit `custom_llm_provider="openai_like"` chat calls into the existing native implementation when `LITELLM_RUST=true`. Other chat providers remain on their existing Python route

This is a non-streaming, text-only experiment. The literal `openai_like` provider has no Python chat implementation in this version. Disabling Rust or losing the extension does not provide a working Python fallback for that provider. Streaming, tools, and unsupported parameters fail before the provider request. Keep existing production model registrations unchanged

Python still runs the HTTP proxy, authentication, router, and callback boundary. The native extension prepares and sends the selected provider request and normalizes its response. The model itself still executes in vLLM

## Run in an isolated environment

The fork's `Qwen Rust experimental image` workflow builds `Dockerfile.qwen-rust` on pushes to `litellm_qwen_native_chat_experiment` that change the Dockerfile, rollout policy, sample configuration, or workflow. Enable GitHub Actions in the fork before pushing if GitHub has disabled inherited workflows. It uses the built-in `GITHUB_TOKEN` with package-write permission; no personal token is stored in this repository

The workflow publishes `ghcr.io/nishi252003/litellm-qwen-rust:<full-commit-sha>` only after checking the extension import and provider policy. Its run summary contains the immutable image digest to use for a separate test deployment. The checks do not contact a model or deploy to Kubernetes. Ensure the cluster can pull the GHCR package before deploying, using an approved image-pull secret if it is private

Use this branch's Python package together with the compiled v1.105.1 extension. A source checkout without the extension cannot run this experiment. Keep the existing Helm release, database, and PR #77 unchanged

The sample uses the backend model name `qwen2-5-coder-14b`, exposed by the proxy as `qwen-native-test`. Adjust the model name in the sample for a different deployment. Point `QWEN_API_BASE` at an already running vLLM service, including its `/v1` suffix. The sample's `unused` backend API key is only appropriate for a backend that does not require authentication

```bash
export QWEN_API_BASE=http://127.0.0.1:8000/v1
export LITELLM_RUST=true
export LITELLM_LOCAL_MODEL_COST_MAP=True
export LITELLM_MASTER_KEY="sk-$(openssl rand -hex 32)"
unset DATABASE_URL DIRECT_URL

litellm --host 127.0.0.1 --port 14077 \
  --config cookbook/litellm_proxy_server/rust_openai_like.yaml
```

Run the request from a terminal with the same test key, without printing or sharing it. Do not expose this experimental endpoint outside the test environment

```bash
curl --fail-with-body --include --noproxy '*' \
  --max-time 120 \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen-native-test",
    "messages": [{"role": "user", "content": "Reply with hello"}],
    "max_tokens": 16,
    "stream": false
  }' \
  http://127.0.0.1:14077/v1/chat/completions
```

Require both a successful response and `x-litellm-rust: true`. That response marker is added by the bridge after native handling; the environment flag or a generic HTTP access log alone does not establish native execution

## Validation

The native integration tests cover sync and async public calls, the execution marker, rejection of unsupported streaming and tools before any backend request, and a provider HTTP error without replay on Python. The catalog tests cover the global opt-in and provider boundary. These tests do not certify production guardrails, database migrations, load behavior, or every callback integration

```bash
LITELLM_RUST=1 pytest -q \
  tests/test_litellm_rust/test_openai_like.py \
  tests/unit/rust_bridge/test_catalog.py
```

The live check used an isolated copy of the package and the existing native extension from `ghcr.io/berriai/litellm@sha256:b7b9e2c306343721802253d0dd9436b9634a2eb4e14da7c7cf06c5c7b7530802`. An authenticated loopback HTTP request reached the existing Qwen/vLLM backend and returned:

```text
HTTP/1.1 200 OK
x-litellm-version: 1.105.1
x-litellm-rust: true
x-litellm-attempted-retries: 0
x-litellm-attempted-fallbacks: 0

"content": "Hello! How can I assist you today?"
```

This verifies the experimental provider execution, not a rollout of the production Helm release
