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

After CI passes, pushes to `main` publish the gateway image.

Images are tagged with the commit SHA, `latest`, and the upstream LiteLLM version.
Use the commit SHA to pin a deployment; the other tags move with new builds.

### Gateway releases

Use **Actions → Tag gateway release → Run workflow** on `main`:

1. Create a candidate: set `source_tag` to a published full commit SHA and
   `gateway_version` to `1.0.0-rc.1`. The upstream version is read from that
   commit's Dockerfile, producing `litellm-1.84.4-gateway-1.0.0-rc.1`.
2. Test that candidate with MLPA and in dev/stage.
3. Promote it: set `source_tag` to `litellm-1.84.4-gateway-1.0.0-rc.1` and
   `gateway_version` to `1.0.0`. This creates `litellm-1.84.4-gateway-1.0.0`
   pointing to the same image digest, without rebuilding.

Leave `dry_run` enabled to preview the tag and digest; disable it to publish.
Branch runs support dry runs only. Existing release tags cannot be overwritten
by this workflow. Promotion is a manual decision; it does not verify external
test results automatically.

Increment the gateway version for handler, packaging, or upstream changes; use
another RC number when revising a candidate. These tags are additional to the
existing SHA, `latest`, and upstream tags. Deployment pins still need an explicit
infra update; its current production validation accepts full SHA tags only.
