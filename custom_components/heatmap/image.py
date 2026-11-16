"""Image platform for the Heatmap integration."""
from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ENTITY_ID,
    CONF_LABEL,
    CONF_MARKER_RADIUS,
    CONF_SENSORS,
    CONF_SHOW_MARKERS,
    CONF_X,
    CONF_Y,
    DEFAULT_MARKER_RADIUS,
    DOMAIN,
)
from .coordinator import HeatmapCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([HeatmapImage(hass, coordinator, entry)])


class HeatmapImage(CoordinatorEntity[HeatmapCoordinator], ImageEntity):
    _attr_content_type = "image/png"
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, hass, coordinator, entry):
        CoordinatorEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, hass)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_heatmap"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Heatmap",
            model="Thermal floorplan",
        )
        self._attr_image_last_updated = coordinator.last_updated

    @property
    def extra_state_attributes(self):
        return {
            "floorplan_width": self._entry.data.get("floorplan_width", 0),
            "floorplan_height": self._entry.data.get("floorplan_height", 0),
            "marker_radius": int(
                self._entry.options.get(CONF_MARKER_RADIUS, DEFAULT_MARKER_RADIUS)
            ),
            "show_markers": bool(self._entry.options.get(CONF_SHOW_MARKERS, True)),
            "markers": [
                {
                    "entity_id": sensor.get(CONF_ENTITY_ID),
                    "x": int(sensor.get(CONF_X, 0)),
                    "y": int(sensor.get(CONF_Y, 0)),
                    "label": sensor.get(CONF_LABEL) or sensor.get(CONF_ENTITY_ID),
                }
                for sensor in self._entry.options.get(CONF_SENSORS, [])
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
