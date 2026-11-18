"""Image platform for the Heatmap integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ENTITY_ID,
    CONF_FLOORPLAN_HEIGHT,
    CONF_FLOORPLAN_WIDTH,
    CONF_LABEL,
    CONF_MARKER_RADIUS,
    CONF_SENSORS,
    CONF_SHOW_MARKERS,
    CONF_X,
    CONF_Y,
    DEFAULT_MARKER_RADIUS,
    DEFAULT_SHOW_MARKERS,
    DOMAIN,
)
from .coordinator import HeatmapConfigEntry, HeatmapCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HeatmapConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([HeatmapImage(hass, entry.runtime_data, entry)])


class HeatmapImage(CoordinatorEntity[HeatmapCoordinator], ImageEntity):
    _attr_content_type = "image/png"
    _attr_has_entity_name = True
    _attr_name = None
    # The state changes on every render; keep the layout out of the recorder.
    _unrecorded_attributes = frozenset(
        {"floorplan_width", "floorplan_height", "marker_radius", "show_markers", "markers"}
    )

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: HeatmapCoordinator,
        entry: HeatmapConfigEntry,
    ) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, hass)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_heatmap"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            entry_type=DeviceEntryType.SERVICE,
        )
        self._attr_image_last_updated = coordinator.last_updated

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        options = self._entry.options
        return {
            "floorplan_width": self._entry.data.get(CONF_FLOORPLAN_WIDTH, 0),
            "floorplan_height": self._entry.data.get(CONF_FLOORPLAN_HEIGHT, 0),
            "marker_radius": int(
                options.get(CONF_MARKER_RADIUS, DEFAULT_MARKER_RADIUS)
            ),
            "show_markers": bool(options.get(CONF_SHOW_MARKERS, DEFAULT_SHOW_MARKERS)),
            "markers": [
                {
                    "entity_id": sensor.get(CONF_ENTITY_ID),
                    "x": int(sensor.get(CONF_X, 0)),
                    "y": int(sensor.get(CONF_Y, 0)),
                    "label": sensor.get(CONF_LABEL) or sensor.get(CONF_ENTITY_ID),
                }
                for sensor in options.get(CONF_SENSORS, [])
                if sensor.get(CONF_ENTITY_ID)
            ],
        }

    async def async_image(self) -> bytes | None:
        return self.coordinator.data

    @callback
    def _handle_coordinator_update(self) -> None:
        self._attr_image_last_updated = self.coordinator.last_updated
        self._cached_image = None
        self.async_write_ha_state()
