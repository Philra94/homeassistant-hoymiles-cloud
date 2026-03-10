"""Helpers to load integration modules without Home Assistant installed."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "custom_components" / "hoymiles_cloud"


def load_integration_module(module_name: str):
    """Load a custom component submodule directly from disk."""
    sys.modules.setdefault("custom_components", types.ModuleType("custom_components"))

    package = sys.modules.get("custom_components.hoymiles_cloud")
    if package is None:
        package = types.ModuleType("custom_components.hoymiles_cloud")
        package.__path__ = [str(PACKAGE_ROOT)]
        sys.modules["custom_components.hoymiles_cloud"] = package

    full_name = f"custom_components.hoymiles_cloud.{module_name}"
    if full_name in sys.modules:
        return sys.modules[full_name]

    spec = importlib.util.spec_from_file_location(
        full_name,
        PACKAGE_ROOT / f"{module_name}.py",
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load module {full_name}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module
