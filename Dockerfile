# Use LiteLLM's non-root runtime to limit process privileges.
# Pin the digest so builds use the same reviewed base image.
FROM ghcr.io/berriai/litellm-non_root:v1.106.5@sha256:1228c608814093f6c030d7788a1c8595cd175328d028a5ea4e878e1f88d6d1da

# Keep upstream's entrypoint and command. Tenant configuration is supplied at deployment.
WORKDIR /app
COPY src/litellm_gateway/ /app/litellm_gateway/
ENV PYTHONPATH=/app

# LiteLLM loads handlers relative to the supplied config path. Keep that path
# beside the package while Kubernetes mounts only configuration under /etc.
RUN ln -sfn /etc/litellm/config.yaml /app/config.yaml
