"""The source registry — one dict, resolved by dynamic import.

Adding a catalog is: write src/collector/web/sources/<name>.py with exactly one
WebSource subclass, add one entry here, seed a source_channels row
(scripts/seed_web_sources.py). Nothing else in the codebase needs to know.

Two sites are deliberately absent and must stay absent unless the reason changes:

  doq.world  — its Terms of Service prohibit automated extraction and the
               republication of listings without prior written permission, and
               it states it embeds identifying markers. It has ~349 listings at
               /competitions/<slug> and would slot in here in a single file IF
               permission is obtained; they publish a contact address for
               exactly that. Getting that permission is the prerequisite, not
               an optimisation.
  pathwaystoscience.org — serves HTTP 500 to a plain client, paginates by
               ASP.NET __VIEWSTATE postback, and publishes no per-program URLs
               in its sitemap. Separately, its flagship REU programs are NSF
               funded and therefore restricted to US citizens, nationals and
               permanent residents by statute, so most of what it lists cannot
               be acted on by a Kazakh student at any price.
"""
import importlib
import inspect

from src.collector.web.base import WebSource

WEB_SOURCES: dict[str, dict] = {
    "extracurricularhub": {
        "module": "src.collector.web.sources.extracurricularhub",
        "enabled": True,
    },
    "sirel": {
        "module": "src.collector.web.sources.sirel",
        "enabled": True,
    },
}


def get_source_class(module_path: str) -> type[WebSource]:
    """The one WebSource subclass defined in this module.

    `obj.__module__ == module_path` excludes WebSource subclasses the module
    merely imported, so a source file may import helpers freely.
    """
    module = importlib.import_module(module_path)
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if (
            obj.__module__ == module_path
            and issubclass(obj, WebSource)
            and obj is not WebSource
        ):
            return obj
    raise LookupError(f"no WebSource subclass defined in {module_path}")


def enabled_sources() -> dict[str, dict]:
    return {k: v for k, v in WEB_SOURCES.items() if v.get("enabled")}
