"""Config and Options flows for Heatmap."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_AUTO_TEXT_COLOR,
    CONF_COLORMAP,
    CONF_DEBUG_WALLS,
    CONF_DOWNSCALE,
    CONF_ENTITY_ID,
    CONF_FLOORPLAN_FILE_ID,
    CONF_FLOORPLAN_FOLDER,
    CONF_FLOORPLAN_HEIGHT,
    CONF_FLOORPLAN_WIDTH,
    CONF_FONT_SIZE,
    CONF_LABEL,
    CONF_MARKER_RADIUS,
    CONF_OPACITY,
    CONF_POWER,
    CONF_SENSORS,
    CONF_SHOW_MARKERS,
    CONF_UPDATE_INTERVAL,
    CONF_VMAX,
    CONF_VMIN,
    CONF_WALL_THRESHOLD,
    CONF_X,
    CONF_Y,
    DEFAULT_AUTO_TEXT_COLOR,
    DEFAULT_COLORMAP,
    DEFAULT_DEBUG_WALLS,
    DEFAULT_DOWNSCALE,
    DEFAULT_FONT_SIZE,
    DEFAULT_MARKER_RADIUS,
    DEFAULT_OPACITY,
    DEFAULT_POWER,
    DEFAULT_SHOW_MARKERS,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_VMAX,
    DEFAULT_VMAX_F,
    DEFAULT_VMIN,
    DEFAULT_VMIN_F,
    DEFAULT_WALL_THRESHOLD,
    DOMAIN,
    VALID_COLORMAPS,
)
from .storage import (
    FloorplanTooLarge,
    async_save_uploaded_floorplan,
    is_valid_folder,
    new_floorplan_folder,
)

_LOGGER = logging.getLogger(__name__)

_FILE_SELECTOR = selector.FileSelector(
    selector.FileSelectorConfig(accept="image/png,image/jpeg,image/webp")
)
_SENSORS_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="sensor", multiple=True)
)
_BOOL_SELECTOR = selector.BooleanSelector()
_COLORMAP_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=list(VALID_COLORMAPS),
        mode=selector.SelectSelectorMode.DROPDOWN,
        translation_key=CONF_COLORMAP,
    )
)


def _number(
    min_value: float,
    max_value: float,
    step: float | str = 1,
    unit: str | None = None,
    mode: selector.NumberSelectorMode = selector.NumberSelectorMode.BOX,
) -> selector.NumberSelector:
    config = selector.NumberSelectorConfig(
        min=min_value, max=max_value, step=step, mode=mode
    )
    # The selector rejects unit_of_measurement=None, so only set it when given.
    if unit is not None:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(config)


_SLIDER = selector.NumberSelectorMode.SLIDER

# Options that are stored as whole numbers (NumberSelector returns floats).
_INT_OPTIONS = (
    CONF_WALL_THRESHOLD,
    CONF_MARKER_RADIUS,
    CONF_FONT_SIZE,
    CONF_UPDATE_INTERVAL,
)


def _default_options(e: dict[str, Any]) -> dict[str, Any]:
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


def _initial_options(hass: HomeAssistant) -> dict[str, Any]:
    """Options for a new entry; the colour range follows the unit system."""
    opts = _default_options({})
    if hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT:
        opts[CONF_VMIN] = DEFAULT_VMIN_F
        opts[CONF_VMAX] = DEFAULT_VMAX_F
    return opts


def _rescale_sensors(
    sensors: list[dict[str, Any]],
    old_size: tuple[Any, Any],
    new_size: tuple[int, int],
) -> list[dict[str, Any]]:
    """Move marker positions to the same relative spot on a new floorplan.

    Positions are stored in image pixels, so a floorplan with a different
    resolution would otherwise put every marker in the wrong place. If the
    old size is unknown, the positions are only clamped to the new image.
    """
    old_w, old_h = old_size
    new_w, new_h = new_size
    scale = bool(old_w and old_h) and (old_w, old_h) != (new_w, new_h)
    result = []
    for sensor in sensors:
        x, y = int(sensor.get(CONF_X, 0)), int(sensor.get(CONF_Y, 0))
        if scale:
            x, y = round(x * new_w / old_w), round(y * new_h / old_h)
        result.append(
            {**sensor, CONF_X: min(max(x, 0), new_w), CONF_Y: min(max(y, 0), new_h)}
        )
    return result


async def _async_store_upload(
    flow: ConfigFlow | OptionsFlow, folder: str, file_id: str
) -> tuple[dict[str, Any] | None, dict[str, str]]:
    """Save an uploaded floorplan. Returns (data, errors)."""
    try:
        w, h = await async_save_uploaded_floorplan(flow.hass, folder, file_id)
    except FloorplanTooLarge:
        _LOGGER.debug("Uploaded floorplan is too large", exc_info=True)
        return None, {CONF_FLOORPLAN_FILE_ID: "image_too_large"}
    except (OSError, ValueError):
        _LOGGER.debug("Uploaded floorplan could not be read", exc_info=True)
        return None, {CONF_FLOORPLAN_FILE_ID: "invalid_image"}
    return {
        CONF_FLOORPLAN_FOLDER: folder,
        CONF_FLOORPLAN_WIDTH: w,
        CONF_FLOORPLAN_HEIGHT: h,
    }, {}


class HeatmapConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 2

    def __init__(self) -> None:
        self._name: str | None = None
        self._floorplan: dict[str, Any] | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._name = user_input[CONF_NAME]
            self._floorplan, errors = await _async_store_upload(
                self, new_floorplan_folder(), user_input[CONF_FLOORPLAN_FILE_ID]
            )
            if not errors:
                return await self.async_step_sensors()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME): str,
                    vol.Required(CONF_FLOORPLAN_FILE_ID): _FILE_SELECTOR,
                }
            ),
            errors=errors,
        )

    async def async_step_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            opts = _initial_options(self.hass)
            opts[CONF_SENSORS] = [
                {CONF_ENTITY_ID: e, CONF_X: 0, CONF_Y: 0, CONF_LABEL: ""}
                for e in user_input.get(CONF_SENSORS, [])
            ]
            return self.async_create_entry(
                title=self._name or "Heatmap",
                data=self._floorplan or {},
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
    def async_get_options_flow(entry: ConfigEntry) -> HeatmapOptionsFlow:
        return HeatmapOptionsFlow()


class HeatmapOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init", menu_options=["general", "sensors", "replace_floorplan"]
        )

    async def async_step_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        o = dict(self.config_entry.options)
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_VMIN] >= user_input[CONF_VMAX]:
                errors[CONF_VMAX] = "vmax_not_above_vmin"
            else:
                cleaned = {
                    **user_input,
                    **{k: int(user_input[k]) for k in _INT_OPTIONS if k in user_input},
                }
                return self.async_create_entry(title="", data={**o, **cleaned})
            # Keep what the user typed when re-showing the form.
            o.update(user_input)

        def req(key: str, default: Any) -> vol.Required:
            return vol.Required(key, default=o.get(key, default))

        schema = vol.Schema(
            {
                req(CONF_VMIN, DEFAULT_VMIN): _number(-1e6, 1e6, "any"),
                req(CONF_VMAX, DEFAULT_VMAX): _number(-1e6, 1e6, "any"),
                req(CONF_POWER, DEFAULT_POWER): _number(0.1, 10, 0.1, mode=_SLIDER),
                req(CONF_OPACITY, DEFAULT_OPACITY): _number(0, 1, 0.05, mode=_SLIDER),
                req(CONF_COLORMAP, DEFAULT_COLORMAP): _COLORMAP_SELECTOR,
                req(CONF_WALL_THRESHOLD, DEFAULT_WALL_THRESHOLD): _number(
                    0, 255, 1, mode=_SLIDER
                ),
                req(CONF_DOWNSCALE, DEFAULT_DOWNSCALE): _number(1, 16, 0.1),
                req(CONF_SHOW_MARKERS, DEFAULT_SHOW_MARKERS): _BOOL_SELECTOR,
                req(CONF_MARKER_RADIUS, DEFAULT_MARKER_RADIUS): _number(
                    1, 200, 1, "px"
                ),
                req(CONF_FONT_SIZE, DEFAULT_FONT_SIZE): _number(6, 96, 1, "px"),
                req(CONF_AUTO_TEXT_COLOR, DEFAULT_AUTO_TEXT_COLOR): _BOOL_SELECTOR,
                req(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL): _number(
                    0, 86400, 1, "s"
                ),
                req(CONF_DEBUG_WALLS, DEFAULT_DEBUG_WALLS): _BOOL_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="general", data_schema=schema, errors=errors
        )

    async def async_step_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
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

    async def async_step_replace_floorplan(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            entry = self.config_entry
            folder = entry.data.get(CONF_FLOORPLAN_FOLDER)
            if not is_valid_folder(folder):
                folder = new_floorplan_folder()
            floorplan, errors = await _async_store_upload(
                self, folder, user_input[CONF_FLOORPLAN_FILE_ID]
            )
            if floorplan is not None:
                options = {
                    **entry.options,
                    CONF_SENSORS: _rescale_sensors(
                        entry.options.get(CONF_SENSORS, []),
                        (
                            entry.data.get(CONF_FLOORPLAN_WIDTH),
                            entry.data.get(CONF_FLOORPLAN_HEIGHT),
                        ),
                        (floorplan[CONF_FLOORPLAN_WIDTH], floorplan[CONF_FLOORPLAN_HEIGHT]),
                    ),
                }
                self.hass.config_entries.async_update_entry(
                    entry, data={**entry.data, **floorplan}, options=options
                )
                if entry.state is not ConfigEntryState.LOADED:
                    # Setup failed because the floorplan was missing; retry now.
                    self.hass.config_entries.async_schedule_reload(entry.entry_id)
                return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="replace_floorplan",
            data_schema=vol.Schema(
                {vol.Required(CONF_FLOORPLAN_FILE_ID): _FILE_SELECTOR}
            ),
            errors=errors,
        )
