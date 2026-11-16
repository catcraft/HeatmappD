"""HeatmapCoordinator."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util
import logging
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path

from .const import *
from .render import render_heatmap

_LOGGER = logging.getLogger(__name__)


class HeatmapCoordinator(DataUpdateCoordinator[bytes]):
    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, floorplan_path: Path
    ) -> None:
        
        self.entry = entry
        self.floorplan_path = floorplan_path
        interval = int(entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=interval) if interval > 0 else None,
        )
        self.last_updated: datetime = dt_util.utcnow()
        self._unsub_state = None
        self._debouncer: Debouncer | None = None

    async def _async_setup(self) -> None:
        self._debouncer = Debouncer(
            self.hass,
            _LOGGER,
            cooldown=STATE_CHANGE_DEBOUNCE,
            immediate=False,
            function=self.async_request_refresh,
        )
        self._resubscribe_state()

    def async_shutdown(self) -> None:
        if self._unsub_state is not None:
            self._unsub_state()
            self._unsub_state = None
        super().async_shutdown()

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
        if self._debouncer:
            self.hass.async_create_task(self._debouncer.async_call())

    @callback
    def async_reconfigure(self) -> None:
        interval = int(
            self.entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        )
        self.update_interval = timedelta(seconds=interval) if interval > 0 else None
        self._resubscribe_state()
        self.hass.async_create_task(self.async_request_refresh())

    async def _async_update_data(self) -> bytes:
        opts = self.entry.options
        sensors = []
        for s in opts.get(CONF_SENSORS, []):
            state: State | None = self.hass.states.get(s[CONF_ENTITY_ID])
            if state is None or state.state in ("unknown", "unavailable"):
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

        render = partial(
            render_heatmap,
            self.floorplan_path,
            sensors,
            vmin=float(opts.get(CONF_VMIN, DEFAULT_VMIN)),
            vmax=float(opts.get(CONF_VMAX, DEFAULT_VMAX)),
            power=float(opts.get(CONF_POWER, DEFAULT_POWER)),
            opacity=float(opts.get(CONF_OPACITY, DEFAULT_OPACITY)),
            colormap=str(opts.get(CONF_COLORMAP, DEFAULT_COLORMAP)),
            wall_threshold=int(opts.get(CONF_WALL_THRESHOLD, DEFAULT_WALL_THRESHOLD)),
            debug_walls=bool(opts.get(CONF_DEBUG_WALLS, DEFAULT_DEBUG_WALLS)),
            downscale=int(opts.get(CONF_DOWNSCALE, DEFAULT_DOWNSCALE)),
            show_markers=bool(opts.get(CONF_SHOW_MARKERS, DEFAULT_SHOW_MARKERS)),
            marker_radius=int(opts.get(CONF_MARKER_RADIUS, DEFAULT_MARKER_RADIUS)),
            font_size=int(opts.get(CONF_FONT_SIZE, DEFAULT_FONT_SIZE)),
            auto_text_color=bool(
                opts.get(CONF_AUTO_TEXT_COLOR, DEFAULT_AUTO_TEXT_COLOR)
            ),
        )
        img_bytes = await self.hass.async_add_executor_job(render)
        self.last_updated = dt_util.utcnow()
        
        return img_bytes
