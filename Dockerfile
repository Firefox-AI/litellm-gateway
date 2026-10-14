# Match the non-root runtime deployed by dataservices-infra.
# Pin the upstream digest so builds use the reviewed artifact.
FROM ghcr.io/berriai/litellm-non_root:v1.84.4@sha256:b6a37a6812de94e55cb22ec45041361af46bb09d630a1cbf0203ac44201441b1

# Keep upstream's entrypoint and command. Tenant configuration is supplied at deployment.
WORKDIR /app
COPY src/litellm_gateway/ /app/litellm_gateway/
ENV PYTHONPATH=/app

# LiteLLM loads handlers relative to the supplied config path. Keep that path
# beside the package while Kubernetes mounts only configuration under /etc.
RUN ln -sfn /etc/litellm/config.yaml /app/config.yaml
