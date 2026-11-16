"""Constants for the Heatmap integration."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Final

DOMAIN: Final = "heatmap"
PLATFORMS: Final = ["image"]
_MANIFEST = json.loads(
    (Path(__file__).parent / "manifest.json").read_text(encoding="utf-8")
)
INTEGRATION_VERSION: Final[str] = _MANIFEST.get("version", "0.0.0")
URL_BASE: Final = "/heatmap"

JSMODULES: Final = [
    {
        "name": "Heatmap Card",
        "filename": "heatmap-card.js",
        "version": INTEGRATION_VERSION,
    },
    {
        "name": "Heatmap Card Editor",
        "filename": "heatmap-card-editor.js",
        "version": INTEGRATION_VERSION,
    },
]

CONF_SENSORS: Final = "sensors"
CONF_ENTITY_ID: Final = "entity_id"
CONF_X: Final = "x"
CONF_Y: Final = "y"
CONF_LABEL: Final = "label"
CONF_FLOORPLAN_FILE_ID: Final = "floorplan_file_id"
CONF_FLOORPLAN_PATH: Final = "floorplan_path"
CONF_FLOORPLAN_WIDTH: Final = "floorplan_width"
CONF_FLOORPLAN_HEIGHT: Final = "floorplan_height"
CONF_VMIN: Final = "vmin"
CONF_VMAX: Final = "vmax"
CONF_POWER: Final = "power"
CONF_OPACITY: Final = "opacity"
CONF_COLORMAP: Final = "colormap"
CONF_DEBUG_WALLS: Final = "debug_walls"
CONF_WALL_THRESHOLD: Final = "wall_threshold"
CONF_DOWNSCALE: Final = "downscale"
CONF_SHOW_MARKERS: Final = "show_markers"
CONF_MARKER_RADIUS: Final = "marker_radius"
CONF_UPDATE_INTERVAL: Final = "update_interval"
CONF_FONT_SIZE: Final = "font_size"
CONF_AUTO_TEXT_COLOR: Final = "auto_text_color"
DEFAULT_VMIN: Final = 18.0
DEFAULT_VMAX: Final = 28.0
DEFAULT_POWER: Final = 2.0
DEFAULT_OPACITY: Final = 0.9
DEFAULT_COLORMAP: Final = "jet"
DEFAULT_DEBUG_WALLS: Final = False
DEFAULT_WALL_THRESHOLD: Final = 200
DEFAULT_DOWNSCALE: Final = 2
DEFAULT_SHOW_MARKERS: Final = True
DEFAULT_MARKER_RADIUS: Final = 20
DEFAULT_UPDATE_INTERVAL: Final = 60
DEFAULT_FONT_SIZE: Final = 14
DEFAULT_AUTO_TEXT_COLOR: Final = True
STATE_CHANGE_DEBOUNCE: Final = 2.0
VALID_COLORMAPS: Final = ("jet", "coolwarm", "turbo", "viridis", "plasma", "inferno")
STORAGE_SUBDIR: Final = "heatmap"
FLOORPLAN_FILENAME: Final = "floorplan.png"
