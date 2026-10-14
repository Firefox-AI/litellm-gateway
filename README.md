# LiteLLM Gateway

Mozilla AI Platform customizations, tests, and container build workflows for our
LiteLLM gateway. Tenant-specific Python code and CI live here; infrastructure and
Helm deployment configuration remain in [mozilla/dataservices-infra](https://github.com/mozilla/dataservices-infra/)

This repository is a temporary home for our LiteLLM integration while the team
plans to move away from LiteLLM in 2027. It extends the official image with custom hooks
rather than maintaining a LiteLLM fork.
