"""Check that the built image can import LiteLLM and our extension namespace."""

import importlib

for module_name in ("litellm", "litellm_gateway"):
    module = importlib.import_module(module_name)
    print(f"Imported {module_name} from {module.__file__}")
