# Use LiteLLM's non-root runtime to limit process privileges.
# Pin the digest so builds use the same reviewed base image.
FROM ghcr.io/berriai/litellm-non_root:v1.108.0@sha256:08d313a00c46509c875d84f60c1448a260c478f399ade3c2abb940d358d5b724

# Keep upstream's entrypoint and command. Tenant configuration is supplied at deployment.
WORKDIR /app
COPY src/litellm_gateway/ /app/litellm_gateway/
ENV PYTHONPATH=/app

# LiteLLM loads handlers relative to the supplied config path. Keep that path
# beside the package while Kubernetes mounts only configuration under /etc.
RUN ln -sfn /etc/litellm/config.yaml /app/config.yaml
