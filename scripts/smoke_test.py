"""Load mounted configuration and packaged handlers in the built runtime image."""

import asyncio
import importlib
import os
from pathlib import Path

import litellm
from litellm.proxy.proxy_server import ProxyConfig

for module_name in (
    "litellm",
    "litellm_gateway.custom_callbacks",
    "litellm_gateway.liner_handler",
    "litellm_gateway.exa_handler",
):
    module = importlib.import_module(module_name)
    print(f"Imported {module_name} from {module.__file__}")

assert os.getuid() != 0, "The gateway must preserve the deployed non-root runtime"
assert Path("/app/config.yaml").resolve() == Path("/etc/litellm/config.yaml")
asyncio.run(ProxyConfig().load_config(router=None, config_file_path="/app/config.yaml"))
assert any(
    type(callback).__name__ == "MyCustomHandler" for callback in litellm.callbacks
)
assert any(
    item["provider"] == "liner" and type(item["custom_handler"]).__name__ == "LinerLLM"
    for item in litellm.custom_provider_map
)
assert any(
    item["provider"] == "exa_citations"
    and type(item["custom_handler"]).__name__ == "ExaLLM"
    for item in litellm.custom_provider_map
)
print("Mounted configuration loaded the billing callback and Liner/Exa providers")
