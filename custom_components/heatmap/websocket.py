"""WebSocket commands for the Heatmap integration."""
import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import callback

from .const import *

@callback
def async_register_websocket_commands(hass):
    for command in (ws_version, ws_list_entries, ws_get_entry, ws_set_sensors):
        websocket_api.async_register_command(hass, command)

@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/version"})
@callback
def ws_version(hass, connection, msg):
    connection.send_result(msg["id"], {"version": INTEGRATION_VERSION})

@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/list_entries"})
@callback
def ws_list_entries(hass, connection, msg):
    connection.send_result(
        msg["id"],
        [
            {"entry_id": eid, "title": c.entry.title}
            for eid, c in hass.data.get(DOMAIN, {}).items()
        ],
    )

@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/get_entry", vol.Required("entry_id"): str}
)
@callback
def ws_get_entry(hass, connection, msg):
    coord = hass.data.get(DOMAIN, {}).get(msg["entry_id"])
    if not coord:
        connection.send_error(msg["id"], "not_found", "Heatmap entry not found")
        return
    e = coord.entry
    connection.send_result(
        msg["id"],
        {
            "entry_id": e.entry_id,
            "title": e.title,
            "options": dict(e.options),
            "floorplan": {
                "width": e.data.get(CONF_FLOORPLAN_WIDTH),
                "height": e.data.get(CONF_FLOORPLAN_HEIGHT),
            },
        },
    )

@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_sensors",
        vol.Required("entry_id"): str,
        vol.Required("sensors"): [
            {
                vol.Required(CONF_ENTITY_ID): str,
                vol.Required(CONF_X): vol.Coerce(int),
                vol.Required(CONF_Y): vol.Coerce(int),
                vol.Optional(CONF_LABEL, default=""): str,
            }
        ],
    }
)

@websocket_api.async_response
async def ws_set_sensors(hass, connection, msg):
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if not entry:
        connection.send_error(msg["id"], "not_found", "Config entry not found")
        return
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_SENSORS: msg["sensors"]}
    )
    connection.send_result(msg["id"], {"ok": True})
