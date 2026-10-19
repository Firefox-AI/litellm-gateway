# LiteLLM Gateway

Custom LiteLLM image for Mozilla AI Platform, including Exa and Liner providers and
Exa/Liner flat-rate billing callback in `src/litellm_gateway/`.

## Build and test

```bash
docker build --platform linux/amd64 -t litellm-gateway:local .
docker run --rm --platform linux/amd64 --network none --entrypoint python \
  -v "$PWD/tests:/tmp/tests:ro" \
  -e LITELLM_LOCAL_MODEL_COST_MAP=True -e DO_NOT_TRACK=True \
  litellm-gateway:local -m unittest discover -s /tmp/tests -v
```

Tests use Python's built-in `unittest` and run directly in the gateway image.
They use synthetic responses and a local fake Exa server, with external networking
disabled. [CI](.github/workflows/ci.yml) also checks lint, formatting, and configuration
loading.

## Configuration

Mount your configuration at `/etc/litellm/config.yaml` and start LiteLLM with
`--config /app/config.yaml` so it can find the packaged handlers. Register them
alongside your model settings:

```yaml
litellm_settings:
  callbacks: litellm_gateway.custom_callbacks.proxy_handler_instance
  custom_provider_map:
    - provider: liner
      custom_handler: litellm_gateway.liner_handler.liner_llm
    - provider: exa_citations
      custom_handler: litellm_gateway.exa_handler.exa_llm
```

## Publishing

After checks pass, pushes to `main` publish a short commit-SHA tag and `latest`.
Use the commit tag or image digest to pin a deployment.

To build and test a branch without publishing:

```bash
gh workflow run publish.yml --repo Firefox-AI/litellm-gateway --ref <branch>
```

Add `-F publish_candidate=true` to publish a unique candidate tag after tests pass,
without updating `latest`.
