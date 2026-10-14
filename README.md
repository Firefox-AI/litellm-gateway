# LiteLLM Gateway

Mozilla AI Platform customizations, tests, and container build workflows for our
LiteLLM gateway. Tenant-specific Python code and CI live here; infrastructure and
Helm deployment configuration remain in [mozilla/dataservices-infra](https://github.com/mozilla/dataservices-infra/)

This repository is a temporary home for our LiteLLM integration while the team
plans to move away from LiteLLM in 2027. It extends the official image with custom hooks
rather than maintaining a LiteLLM fork.

## Initial scaffold

- `src/litellm_gateway/`: namespace for custom callbacks and other gateway code.
- `pyproject.toml`: isolated Python project and development dependencies.
- `Dockerfile`: versioned upstream LiteLLM image with our extension namespace.
- `scripts/smoke_test.py`: verifies imports inside the resulting image.
- `.github/workflows/ci.yml`: Python lint/format/syntax checks and an amd64 image
  build with a runtime import smoke test on pull requests and pushes to `main`.
- `.github/workflows/publish.yml`: manually publishes a tested image to our GAR.

Custom callbacks and their unit tests have not been migrated yet. No gateway
configuration, credentials, or production deployment changes are included.

## Local development

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
python -m compileall -q src scripts

docker build --platform linux/amd64 -t litellm-gateway:local .
docker run --rm --platform linux/amd64 --network none --entrypoint python \
  --volume "$PWD/scripts/smoke_test.py:/tmp/smoke_test.py:ro" \
  --env PYTHONPATH=/app \
  litellm-gateway:local /tmp/smoke_test.py
```

Add callback unit tests under `tests/` when migrating custom code, and add
`pytest` to the Python CI job at that point. The development extra already includes
pytest. LiteLLM is provided by the container; the local Python project does not
install another copy of LiteLLM or change its runtime dependencies.

## Publishing to Google Artifact Registry

The manual **Publish to GAR** workflow runs checks, builds and smoke-tests a
candidate, then pushes that same local image with a `sha-<commit>` tag to:

```text
us-docker.pkg.dev/moz-fx-llm-proxy-prod-b0b8/llm-proxy-prod/litellm-gateway
```

Before publishing, coordinate with MozCloud to authorize
`Firefox-AI/litellm-gateway` in the tenant's Workload Identity Federation setup and
allow the deploy service account to write to the registry. Configure these GitHub
Actions repository variables:

| Variable | Value |
| --- | --- |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Full `projects/.../locations/global/workloadIdentityPools/.../providers/...` provider name |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | Tenant deploy service account email |

Authentication uses GitHub OIDC; no service account key is needed. Publishing is
manual and restricted to `main`. It does not deploy the image. Promote a reviewed
image digest through the tenant's Helm configuration separately.

The initial upstream tag, `v1.84.4`, matches MLPA's current local Compose setup; it
has not been established as the production version. The Dockerfile pins the resolved upstream digest. Confirm the intended upstream
version before production adoption. Dependabot opens upstream
image and dependency update PRs for review.
