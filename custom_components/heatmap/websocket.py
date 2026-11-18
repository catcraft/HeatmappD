"""WebSocket commands for the Heatmap integration."""
from __future__ import annotations

from base64 import b64encode
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import (
    CONF_ENTITY_ID,
    CONF_FLOORPLAN_HEIGHT,
    CONF_FLOORPLAN_WIDTH,
    CONF_LABEL,
    CONF_SENSORS,
    CONF_X,
    CONF_Y,
    DOMAIN,
    INTEGRATION_VERSION,
)


@callback
def async_register_websocket_commands(hass: HomeAssistant) -> None:
    for command in (
        ws_version,
        ws_list_entries,
        ws_get_entry,
        ws_render_preview,
        ws_set_sensors,
    ):
        websocket_api.async_register_command(hass, command)


@callback
def _get_heatmap_entry(hass: HomeAssistant, entry_id: str) -> ConfigEntry | None:
    """Return the config entry only if it belongs to this integration."""
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        return None
    return entry


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/version"})
@callback
def ws_version(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    connection.send_result(msg["id"], {"version": INTEGRATION_VERSION})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/list_entries"})
@websocket_api.require_admin
@callback
def ws_list_entries(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """List loaded entries with the image entities that belong to them.

    The frontend's entity list does not carry config entry ids, so the card
    editor maps its image entity to an entry through this list.
    """
    registry = er.async_get(hass)
    connection.send_result(
        msg["id"],
        [
            {
                "entry_id": entry.entry_id,
                "title": entry.title,
                "entity_ids": [
                    reg_entry.entity_id
                    for reg_entry in er.async_entries_for_config_entry(
                        registry, entry.entry_id
                    )
                    if reg_entry.domain == "image"
                ],
            }
            for entry in hass.config_entries.async_loaded_entries(DOMAIN)
        ],
    )


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/get_entry", vol.Required("entry_id"): str}
)
@websocket_api.require_admin
@callback
def ws_get_entry(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    entry = _get_heatmap_entry(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "Heatmap entry not found"
        )
        return
    connection.send_result(
        msg["id"],
        {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "options": dict(entry.options),
            "floorplan": {
                "width": entry.data.get(CONF_FLOORPLAN_WIDTH),
                "height": entry.data.get(CONF_FLOORPLAN_HEIGHT),
            },
        },
    )


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/render_preview", vol.Required("entry_id"): str}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_render_preview(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the heatmap without markers as a base64 PNG for the editor."""
    entry = _get_heatmap_entry(hass, msg["entry_id"])
    if entry is None or entry.state is not ConfigEntryState.LOADED:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "Heatmap entry not loaded"
        )
        return
    try:
        image = await entry.runtime_data.async_render_preview()
    except UpdateFailed as err:
        connection.send_error(msg["id"], websocket_api.ERR_UNKNOWN_ERROR, str(err))
        return
    connection.send_result(
        msg["id"],
        {"content_type": "image/png", "data": b64encode(image).decode("ascii")},
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_sensors",
        vol.Required("entry_id"): str,
        vol.Required("sensors"): [
            {
                vol.Required(CONF_ENTITY_ID): cv.entity_id,
                vol.Required(CONF_X): vol.All(vol.Coerce(int), vol.Range(min=0)),
                vol.Required(CONF_Y): vol.All(vol.Coerce(int), vol.Range(min=0)),
                vol.Optional(CONF_LABEL): vol.All(str, vol.Length(max=100)),
            }
        ],
    }
)
@websocket_api.require_admin
@callback
def ws_set_sensors(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Update the positions (and labels) of the configured sensors.

    The sensor list itself belongs to the options flow. A layout sent from an
    older editor session must not add back or drop sensors that were changed
    there since, so unknown entity ids are ignored and sensors missing from
    the message keep their position.
    """
    entry = _get_heatmap_entry(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "Heatmap entry not found"
        )
        return

    sensors: list[dict[str, Any]] = msg["sensors"]
    width = entry.data.get(CONF_FLOORPLAN_WIDTH) or 0
    height = entry.data.get(CONF_FLOORPLAN_HEIGHT) or 0
    seen: set[str] = set()
    for sensor in sensors:
        entity_id = sensor[CONF_ENTITY_ID]
        if entity_id in seen:
            connection.send_error(
                msg["id"],
                websocket_api.ERR_INVALID_FORMAT,
                f"Duplicate sensor: {entity_id}",
            )
            return
        seen.add(entity_id)
        if (width and sensor[CONF_X] > width) or (height and sensor[CONF_Y] > height):
            connection.send_error(
                msg["id"],
                websocket_api.ERR_INVALID_FORMAT,
                f"Position of {entity_id} is outside the floorplan "
                f"({width}x{height})",
            )
            return

    updates = {sensor[CONF_ENTITY_ID]: sensor for sensor in sensors}
    current: list[dict[str, Any]] = entry.options.get(CONF_SENSORS, [])
    known = {sensor[CONF_ENTITY_ID] for sensor in current}
    merged = [
        {**sensor, **updates[sensor[CONF_ENTITY_ID]]}
        if sensor[CONF_ENTITY_ID] in updates
        else sensor
        for sensor in current
    ]

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_SENSORS: merged}
    )
    connection.send_result(
        msg["id"], {"ok": True, "ignored": sorted(updates.keys() - known)}
    )
