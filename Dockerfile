# Use LiteLLM's non-root runtime to limit process privileges.
# Pin the digest so builds use the same reviewed base image.
FROM ghcr.io/berriai/litellm-non_root:v1.106.2@sha256:07fabea33dfc2b127e865c03112dfc76936334b29028ec05cdd355af2385dc04

# Keep upstream's entrypoint and command. Tenant configuration is supplied at deployment.
WORKDIR /app
COPY src/litellm_gateway/ /app/litellm_gateway/
ENV PYTHONPATH=/app

# LiteLLM loads handlers relative to the supplied config path. Keep that path
# beside the package while Kubernetes mounts only configuration under /etc.
RUN ln -sfn /etc/litellm/config.yaml /app/config.yaml
