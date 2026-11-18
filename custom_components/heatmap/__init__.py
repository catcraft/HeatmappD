"""The Heatmap integration."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_FLOORPLAN_FOLDER,
    CONF_FLOORPLAN_HEIGHT,
    CONF_FLOORPLAN_PATH,
    CONF_FLOORPLAN_WIDTH,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import HeatmapConfigEntry, HeatmapCoordinator
from .frontend import (
    async_register_frontend,
    async_remove_legacy_resources,
    async_unregister_frontend,
)
from .storage import (
    async_remove_floorplan,
    async_remove_orphaned_floorplans,
    async_save_uploaded_floorplan,
    floorplan_path,
    is_valid_folder,
)
from .websocket import async_register_websocket_commands

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Entries created before 1.0.1 stored the upload id and saved the image on setup.
_LEGACY_PENDING_FILE_ID = "pending_file_id"


def _entry_folder(entry: ConfigEntry) -> str | None:
    """Return the floorplan folder of an entry, for current and legacy data."""
    if folder := entry.data.get(CONF_FLOORPLAN_FOLDER):
        return folder
    if legacy := entry.data.get(CONF_FLOORPLAN_PATH):
        return Path(legacy).parent.name
    return None


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_register_websocket_commands(hass)
    await async_register_frontend(hass)

    async def _remove_legacy_resources(_event: Event | None = None) -> None:
        await async_remove_legacy_resources(hass)

    if hass.state is CoreState.running:
        await _remove_legacy_resources()
    else:
        # Only clean up during startup, so no config flow can be in progress.
        keep: set[str] = set()
        for entry in hass.config_entries.async_entries(DOMAIN):
            # Pre-1.0.1 entries that are not migrated yet use their entry id.
            keep.add(entry.entry_id)
            if folder := _entry_folder(entry):
                keep.add(folder)
        await async_remove_orphaned_floorplans(hass, keep)
        hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STARTED, _remove_legacy_resources
        )
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old entries to store a folder name instead of an absolute path."""
    if entry.version > 1:
        # Downgrade from a future version.
        return False

    if entry.version == 1 and entry.minor_version < 2:
        new_data = dict(entry.data)

        if _LEGACY_PENDING_FILE_ID in new_data:
            file_id = new_data.pop(_LEGACY_PENDING_FILE_ID)
            folder = entry.entry_id
            try:
                w, h = await async_save_uploaded_floorplan(hass, folder, file_id)
            except (OSError, ValueError):
                # Uploads do not survive a restart. Setup will then report the
                # missing floorplan and ask the user to replace it.
                _LOGGER.warning(
                    "Pending floorplan upload of %s is gone; please replace "
                    "the floorplan in the integration options",
                    entry.title,
                )
            else:
                new_data[CONF_FLOORPLAN_WIDTH] = w
                new_data[CONF_FLOORPLAN_HEIGHT] = h
            new_data[CONF_FLOORPLAN_FOLDER] = folder
        elif CONF_FLOORPLAN_PATH in new_data:
            new_data[CONF_FLOORPLAN_FOLDER] = Path(
                new_data[CONF_FLOORPLAN_PATH]
            ).parent.name

        new_data.pop(CONF_FLOORPLAN_PATH, None)
        hass.config_entries.async_update_entry(
            entry, data=new_data, version=1, minor_version=2
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: HeatmapConfigEntry) -> bool:
    folder = entry.data.get(CONF_FLOORPLAN_FOLDER)
    path = floorplan_path(hass, folder) if is_valid_folder(folder) else None
    if path is None or not await hass.async_add_executor_job(path.is_file):
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="floorplan_missing",
            translation_placeholders={"path": str(path or folder)},
        )

    # The card may have been unregistered when the last entry was removed.
    await async_register_frontend(hass)

    coordinator = HeatmapCoordinator(hass, entry, path)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HeatmapConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.async_shutdown()
    return ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    if folder := _entry_folder(entry):
        await async_remove_floorplan(hass, folder)

    others = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.entry_id != entry.entry_id
    ]
    if not others:
        async_unregister_frontend(hass)


async def _async_options_updated(
    hass: HomeAssistant, entry: HeatmapConfigEntry
) -> None:
    entry.runtime_data.async_reconfigure()
