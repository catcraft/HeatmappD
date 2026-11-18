"""Serve the Heatmap card and load it on every dashboard.

Only the card's JavaScript files are served; nothing else in this folder is
reachable over HTTP. The card is loaded through the frontend's public
``add_extra_js_url`` API, so no Lovelace resource entry is needed and YAML-mode
dashboards work too. The editor is not loaded up front: the card imports it
when a dashboard editor asks for it.
"""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any

from homeassistant.components.frontend import add_extra_js_url, remove_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant, callback
from homeassistant.util.hass_dict import HassKey

from ..const import CARD_FILENAME, DOMAIN, INTEGRATION_VERSION, JSMODULES, URL_BASE

_LOGGER = logging.getLogger(__name__)

_FRONTEND_STATE: HassKey[dict[str, Any]] = HassKey(f"{DOMAIN}_frontend")
_FILES_DIR = Path(__file__).parent
_MODULE_URLS = {f"{URL_BASE}/{m['filename']}" for m in JSMODULES}

# Versions before 1.0.3 registered "<url>?v=<version>" as dashboard resources.
_LEGACY_QUERY = re.compile(r"v=\d+(\.\d+)*")


def _files_hash() -> str:
    """Short hash over all card files (runs in the executor).

    The card imports the editor with its own query string, so one hash over
    both files makes both URLs change whenever either file changes.
    """
    digest = hashlib.sha256()
    for module in JSMODULES:
        digest.update((_FILES_DIR / module["filename"]).read_bytes())
    return digest.hexdigest()[:12]


def _card_url(files_hash: str) -> str:
    """URL that changes whenever a file's content changes.

    The files are served with long-lived cache headers, so the query string
    must change on every code change, not only on a version bump.
    """
    return f"{URL_BASE}/{CARD_FILENAME}?v={INTEGRATION_VERSION}-{files_hash}"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the card files and add the card to the frontend (idempotent)."""
    state = hass.data.setdefault(
        _FRONTEND_STATE, {"static": False, "js_loaded": False, "url": None}
    )

    if not state["static"]:
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    f"{URL_BASE}/{module['filename']}",
                    str(_FILES_DIR / module["filename"]),
                    True,
                )
                for module in JSMODULES
            ]
        )
        state["static"] = True

    if not state["js_loaded"]:
        if not state["url"]:
            state["url"] = _card_url(await hass.async_add_executor_job(_files_hash))
        add_extra_js_url(hass, state["url"])
        state["js_loaded"] = True


@callback
def async_unregister_frontend(hass: HomeAssistant) -> None:
    """Stop loading the card (called when the last entry is removed)."""
    state = hass.data.get(_FRONTEND_STATE)
    if not state or not state["js_loaded"]:
        return
    remove_extra_js_url(hass, state["url"])
    state["js_loaded"] = False


def _is_legacy_resource(url: str) -> bool:
    """Return True for a resource that versions before 1.0.3 registered.

    A resource the user added by hand (for example for Cast) has no
    ``?v=<version>`` query and is kept.
    """
    path, _, query = url.partition("?")
    return path in _MODULE_URLS and _LEGACY_QUERY.fullmatch(query) is not None


async def async_remove_legacy_resources(hass: HomeAssistant) -> None:
    """Remove dashboard resources that versions before 1.0.3 registered.

    Those entries would load the card a second time. Lovelace does not offer a
    public API for this, so any failure is only logged and never blocks setup.
    """
    try:
        lovelace = hass.data.get("lovelace")
        resources = getattr(lovelace, "resources", None)
        if resources is None or not hasattr(resources, "async_delete_item"):
            return  # YAML mode: resources are managed by the user.
        await resources.async_get_info()  # Loads the collection if needed.
        for item in list(resources.async_items()):
            if _is_legacy_resource(str(item.get("url", ""))):
                await resources.async_delete_item(item["id"])
                _LOGGER.info("Removed old dashboard resource %s", item["url"])
    except Exception:  # noqa: BLE001 - best effort cleanup of old installs
        _LOGGER.debug("Could not clean up old dashboard resources", exc_info=True)
