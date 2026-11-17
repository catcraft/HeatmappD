"""The Heatmap integration."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import config_validation as cv
from pathlib import Path
from .const import *
from .coordinator import HeatmapCoordinator
from .frontend import JSModuleRegistration
from .storage import async_remove_floorplan, async_save_uploaded_floorplan
from .websocket import async_register_websocket_commands


CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    async_register_websocket_commands(hass)

    async def _setup_frontend(_event=None):
        await JSModuleRegistration(hass).async_register()

    if hass.state == CoreState.running:
        await _setup_frontend()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _setup_frontend)
    return True


async def async_setup_entry(hass, entry):
    if "pending_file_id" in entry.data:
        path, w, h = await async_save_uploaded_floorplan(
            hass, entry.entry_id, entry.data["pending_file_id"]
        )
        new_data = {k: v for k, v in entry.data.items() if k != "pending_file_id"}
        new_data.update(
            {
                CONF_FLOORPLAN_PATH: str(path),
                CONF_FLOORPLAN_WIDTH: w,
                CONF_FLOORPLAN_HEIGHT: h,
            }
        )
        hass.config_entries.async_update_entry(entry, data=new_data)
    path = Path(entry.data[CONF_FLOORPLAN_PATH])
    if not path.is_file():
        raise RuntimeError(f"Floorplan not found: {path}")
    
    coordinator = HeatmapCoordinator(hass, entry, path)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass, entry):
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        coord = hass.data[DOMAIN].pop(entry.entry_id, None)
        if coord:
            coord.async_shutdown()
    return ok


async def async_remove_entry(hass, entry):
    async_remove_floorplan(hass, entry.entry_id)


async def _async_options_updated(hass, entry):
    coord = hass.data[DOMAIN].get(entry.entry_id)
    if coord:
        coord.async_reconfigure()