"""HeatmapCoordinator."""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util
from PIL import Image

from .const import (
    CONF_AUTO_TEXT_COLOR,
    CONF_COLORMAP,
    CONF_DEBUG_WALLS,
    CONF_DOWNSCALE,
    CONF_ENTITY_ID,
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
    DEFAULT_VMIN,
    DEFAULT_WALL_THRESHOLD,
    DOMAIN,
    PREVIEW_MAX_SIDE,
    STATE_CHANGE_DEBOUNCE,
)
from .render import Floorplan, floorplan_key, load_floorplan, render_heatmap

_LOGGER = logging.getLogger(__name__)

type HeatmapConfigEntry = ConfigEntry[HeatmapCoordinator]


class HeatmapCoordinator(DataUpdateCoordinator[bytes]):
    config_entry: HeatmapConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: HeatmapConfigEntry, floorplan_path: Path
    ) -> None:
        self.entry = entry
        self.floorplan_path = floorplan_path
        interval = int(entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=interval) if interval > 0 else None,
            # Sensor changes often arrive in bursts; collect them into one render.
            request_refresh_debouncer=Debouncer(
                hass, _LOGGER, cooldown=STATE_CHANGE_DEBOUNCE, immediate=False
            ),
            # A render that gives the same image (e.g. a sensor reported the
            # same value again) must not write a new state to the recorder.
            always_update=False,
        )
        self.last_updated: datetime = dt_util.utcnow()
        self._unsub_state: Callable[[], None] | None = None
        # Downscaled floorplan and wall masks, reused until the file or the
        # wall threshold / downscale settings change.
        self._floorplan: Floorplan | None = None

    async def _async_setup(self) -> None:
        self._resubscribe_state()

    async def async_shutdown(self) -> None:
        if self._unsub_state is not None:
            self._unsub_state()
            self._unsub_state = None
        await super().async_shutdown()

    @callback
    def _resubscribe_state(self) -> None:
        entity_ids = [
            s[CONF_ENTITY_ID]
            for s in self.entry.options.get(CONF_SENSORS, [])
            if s.get(CONF_ENTITY_ID)
        ]
        if self._unsub_state is not None:
            self._unsub_state()
            self._unsub_state = None
        if entity_ids:
            self._unsub_state = async_track_state_change_event(
                self.hass, entity_ids, self._handle_state_change
            )

    @callback
    def _handle_state_change(self, _event: Event) -> None:
        self.config_entry.async_create_background_task(
            self.hass, self.async_request_refresh(), f"{DOMAIN} state refresh"
        )

    @callback
    def async_reconfigure(self) -> None:
        interval = int(
            self.entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        )
        self.update_interval = timedelta(seconds=interval) if interval > 0 else None
        self._resubscribe_state()
        self.config_entry.async_create_background_task(
            self.hass, self.async_request_refresh(), f"{DOMAIN} reconfigure refresh"
        )

    def _render_job(self, **overrides: Any) -> Callable[[], bytes]:
        """Return a function that renders the current state (in the executor).

        ``overrides`` replace render settings, e.g. ``show_markers=False``.
        """
        opts = self.entry.options
        sensors = []
        for s in opts.get(CONF_SENSORS, []):
            state: State | None = self.hass.states.get(s[CONF_ENTITY_ID])
            if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                continue
            try:
                value = float(state.state)
            except (TypeError, ValueError):
                continue
            sensors.append(
                {
                    "x": int(s[CONF_X]),
                    "y": int(s[CONF_Y]),
                    "value": value,
                    "label": s.get(CONF_LABEL) or f"{value:.1f}",
                }
            )

        wall_threshold = int(opts.get(CONF_WALL_THRESHOLD, DEFAULT_WALL_THRESHOLD))
        downscale = float(opts.get(CONF_DOWNSCALE, DEFAULT_DOWNSCALE))
        settings: dict[str, Any] = {
            "vmin": float(opts.get(CONF_VMIN, DEFAULT_VMIN)),
            "vmax": float(opts.get(CONF_VMAX, DEFAULT_VMAX)),
            "power": float(opts.get(CONF_POWER, DEFAULT_POWER)),
            "opacity": float(opts.get(CONF_OPACITY, DEFAULT_OPACITY)),
            "colormap": str(opts.get(CONF_COLORMAP, DEFAULT_COLORMAP)),
            "debug_walls": bool(opts.get(CONF_DEBUG_WALLS, DEFAULT_DEBUG_WALLS)),
            "show_markers": bool(opts.get(CONF_SHOW_MARKERS, DEFAULT_SHOW_MARKERS)),
            "marker_radius": int(opts.get(CONF_MARKER_RADIUS, DEFAULT_MARKER_RADIUS)),
            "font_size": int(opts.get(CONF_FONT_SIZE, DEFAULT_FONT_SIZE)),
            "auto_text_color": bool(
                opts.get(CONF_AUTO_TEXT_COLOR, DEFAULT_AUTO_TEXT_COLOR)
            ),
        }
        settings.update(overrides)
        draw = partial(render_heatmap, sensors=sensors, **settings)

        def render() -> bytes:
            # Runs in the executor. Two renders may overlap (timer, state
            # change, editor preview); the cache is only ever swapped as a
            # whole and its arrays are read-only, so the worst case is loading
            # it twice.
            path = self.floorplan_path
            floorplan = self._floorplan
            if floorplan is None or floorplan.key != floorplan_key(
                path, wall_threshold, downscale
            ):
                floorplan = load_floorplan(path, wall_threshold, downscale)
                self._floorplan = floorplan
            return draw(floorplan)

        return render

    async def _async_render(self, **overrides: Any) -> bytes:
        try:
            return await self.hass.async_add_executor_job(
                self._render_job(**overrides)
            )
        except (
            OSError,
            ValueError,
            MemoryError,
            Image.DecompressionBombError,
        ) as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="render_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async def async_render_preview(self) -> bytes:
        """Render the heatmap without markers, small enough for the editor.

        The card editor draws its own draggable markers; markers baked into
        the image would show the old positions underneath.
        """
        return await self._async_render(
            show_markers=False, max_side=PREVIEW_MAX_SIDE
        )

    async def _async_update_data(self) -> bytes:
        img_bytes = await self._async_render()
        if img_bytes != self.data:
            self.last_updated = dt_util.utcnow()
        return img_bytes
