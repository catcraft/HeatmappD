"""Config and Options flows for Heatmap."""
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from typing import Any
import voluptuous as vol
from .const import *
from .storage import async_save_uploaded_floorplan

_FILE_SELECTOR = selector.FileSelector(
    selector.FileSelectorConfig(accept="image/png,image/jpeg,image/webp")
)
_SENSORS_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="sensor", multiple=True)
)


def _default_options(e):
    return {
        CONF_SENSORS: e.get(CONF_SENSORS, []),
        CONF_VMIN: e.get(CONF_VMIN, DEFAULT_VMIN),
        CONF_VMAX: e.get(CONF_VMAX, DEFAULT_VMAX),
        CONF_POWER: e.get(CONF_POWER, DEFAULT_POWER),
        CONF_OPACITY: e.get(CONF_OPACITY, DEFAULT_OPACITY),
        CONF_COLORMAP: e.get(CONF_COLORMAP, DEFAULT_COLORMAP),
        CONF_WALL_THRESHOLD: e.get(CONF_WALL_THRESHOLD, DEFAULT_WALL_THRESHOLD),
        CONF_DEBUG_WALLS: e.get(CONF_DEBUG_WALLS, DEFAULT_DEBUG_WALLS),
        CONF_DOWNSCALE: e.get(CONF_DOWNSCALE, DEFAULT_DOWNSCALE),
        CONF_SHOW_MARKERS: e.get(CONF_SHOW_MARKERS, DEFAULT_SHOW_MARKERS),
        CONF_MARKER_RADIUS: e.get(CONF_MARKER_RADIUS, DEFAULT_MARKER_RADIUS),
        CONF_UPDATE_INTERVAL: e.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
        CONF_FONT_SIZE: e.get(CONF_FONT_SIZE, DEFAULT_FONT_SIZE),
        CONF_AUTO_TEXT_COLOR: e.get(CONF_AUTO_TEXT_COLOR, DEFAULT_AUTO_TEXT_COLOR),
    }


class HeatmapConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._name = None
        self._file = None
        self._ids = []

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            self._name = user_input[CONF_NAME]
            self._file = user_input[CONF_FLOORPLAN_FILE_ID]
            return await self.async_step_sensors()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME): str,
                    vol.Required(CONF_FLOORPLAN_FILE_ID): _FILE_SELECTOR,
                }
            ),
        )

    async def async_step_sensors(self, user_input=None):
        if user_input is not None:
            self._ids = user_input.get(CONF_SENSORS, [])
            opts = _default_options({})
            opts[CONF_SENSORS] = [
                {CONF_ENTITY_ID: e, CONF_X: 0, CONF_Y: 0, CONF_LABEL: ""}
                for e in self._ids
            ]
            return self.async_create_entry(
                title=self._name or "Heatmap",
                data={"pending_file_id": self._file},
                options=opts,
            )
        return self.async_show_form(
            step_id="sensors",
            data_schema=vol.Schema(
                {vol.Optional(CONF_SENSORS, default=[]): _SENSORS_SELECTOR}
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry):
        return HeatmapOptionsFlow()


class HeatmapOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input=None):
        return self.async_show_menu(
            step_id="init", menu_options=["general", "sensors", "replace_floorplan"]
        )

    async def async_step_general(self, user_input=None):
        o = self.config_entry.options
        if user_input is not None:
            return self.async_create_entry(title="", data={**o, **user_input})
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_VMIN, default=o.get(CONF_VMIN, DEFAULT_VMIN)
                ): vol.Coerce(float),
                vol.Required(
                    CONF_VMAX, default=o.get(CONF_VMAX, DEFAULT_VMAX)
                ): vol.Coerce(float),
                vol.Required(
                    CONF_POWER, default=o.get(CONF_POWER, DEFAULT_POWER)
                ): vol.Coerce(float),
                vol.Required(
                    CONF_OPACITY, default=o.get(CONF_OPACITY, DEFAULT_OPACITY)
                ): vol.Coerce(float),
                vol.Required(
                    CONF_COLORMAP, default=o.get(CONF_COLORMAP, DEFAULT_COLORMAP)
                ): vol.In(VALID_COLORMAPS),
                vol.Required(
                    CONF_WALL_THRESHOLD,
                    default=o.get(CONF_WALL_THRESHOLD, DEFAULT_WALL_THRESHOLD),
                ): vol.Coerce(int),
                vol.Required(
                    CONF_DOWNSCALE, default=o.get(CONF_DOWNSCALE, DEFAULT_DOWNSCALE)
                ): vol.Coerce(int),
                vol.Required(
                    CONF_SHOW_MARKERS,
                    default=o.get(CONF_SHOW_MARKERS, DEFAULT_SHOW_MARKERS),
                ): bool,
                vol.Required(
                    CONF_MARKER_RADIUS,
                    default=o.get(CONF_MARKER_RADIUS, DEFAULT_MARKER_RADIUS),
                ): vol.Coerce(int),
                vol.Required(
                    CONF_FONT_SIZE, default=o.get(CONF_FONT_SIZE, DEFAULT_FONT_SIZE)
                ): vol.All(vol.Coerce(int), vol.Range(min=6, max=96)),
                vol.Required(
                    CONF_AUTO_TEXT_COLOR,
                    default=o.get(CONF_AUTO_TEXT_COLOR, DEFAULT_AUTO_TEXT_COLOR),
                ): bool,
                vol.Required(
                    CONF_UPDATE_INTERVAL,
                    default=o.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
                ): vol.Coerce(int),
                vol.Required(
                    CONF_DEBUG_WALLS,
                    default=o.get(CONF_DEBUG_WALLS, DEFAULT_DEBUG_WALLS),
                ): bool,
            }
        )
        return self.async_show_form(step_id="general", data_schema=schema)

    async def async_step_sensors(self, user_input=None):
        o = self.config_entry.options
        ids = [s[CONF_ENTITY_ID] for s in o.get(CONF_SENSORS, [])]
        if user_input is not None:
            by_id = {s[CONF_ENTITY_ID]: s for s in o.get(CONF_SENSORS, [])}
            sensors = [
                by_id.get(e, {CONF_ENTITY_ID: e, CONF_X: 0, CONF_Y: 0, CONF_LABEL: ""})
                for e in user_input.get(CONF_SENSORS, [])
            ]
            return self.async_create_entry(title="", data={**o, CONF_SENSORS: sensors})
        return self.async_show_form(
            step_id="sensors",
            data_schema=vol.Schema(
                {vol.Optional(CONF_SENSORS, default=ids): _SENSORS_SELECTOR}
            ),
        )

    async def async_step_replace_floorplan(self, user_input=None):
        if user_input is not None:
            path, w, h = await async_save_uploaded_floorplan(
                self.hass,
                self.config_entry.entry_id,
                user_input[CONF_FLOORPLAN_FILE_ID],
            )
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={
                    **self.config_entry.data,
                    CONF_FLOORPLAN_PATH: str(path),
                    CONF_FLOORPLAN_WIDTH: w,
                    CONF_FLOORPLAN_HEIGHT: h,
                },
            )
            return self.async_create_entry(
                title="", data=dict(self.config_entry.options)
            )
        return self.async_show_form(
            step_id="replace_floorplan",
            data_schema=vol.Schema(
                {vol.Required(CONF_FLOORPLAN_FILE_ID): _FILE_SELECTOR}
            ),
        )
