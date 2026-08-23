"""Dynamic source-module resolution, shared by main.py's CLI-facing source
registry and pipeline/enrich.py's per-item source lookup."""

from __future__ import annotations

import importlib
import inspect
import logging

from sources.base import Source

logger = logging.getLogger(__name__)


def get_source_class(module_path: str) -> type[Source] | None:
    """Import module_path and return the Source subclass defined in it, or
    None (logged) if the module fails to import or defines none."""
    try:
        module = importlib.import_module(module_path)
    except Exception:
        logger.error("failed to import source module %s", module_path, exc_info=True)
        return None

    for _, obj in inspect.getmembers(module, inspect.isclass):
        if obj.__module__ == module_path and issubclass(obj, Source) and obj is not Source:
            return obj

    logger.error("no Source subclass found in %s", module_path)
    return None
