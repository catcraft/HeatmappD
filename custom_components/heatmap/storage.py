"""Floorplan storage helpers."""
from __future__ import annotations

from homeassistant.components.file_upload import process_uploaded_file
from homeassistant.core import HomeAssistant
from pathlib import Path
from .const import FLOORPLAN_FILENAME, STORAGE_SUBDIR

def floorplan_dir(hass: HomeAssistant, entry_id: str) -> Path:
    return Path(hass.config.path(".storage", STORAGE_SUBDIR, entry_id))

def floorplan_path(hass: HomeAssistant, entry_id: str) -> Path:
    return floorplan_dir(hass, entry_id) / FLOORPLAN_FILENAME

async def async_save_uploaded_floorplan(
    hass: HomeAssistant, entry_id: str, file_id: str) -> tuple[Path, int, int]:
    """Move an uploaded file into our storage directory and return (path, w, h)."""
    from PIL import Image

    dest_dir = floorplan_dir(hass, entry_id)
    dest = dest_dir / FLOORPLAN_FILENAME

    def _copy_and_normalize(src: Path) -> tuple[int, int]:
        dest_dir.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as img:
            img = img.convert("RGB")
            img.save(dest, format="PNG", optimize=True)
            return img.size

    with process_uploaded_file(hass, file_id) as src_path:
        w, h = await hass.async_add_executor_job(_copy_and_normalize, src_path)
    return dest, w, h


def async_remove_floorplan(hass: HomeAssistant, entry_id: str) -> None:
    import shutil

    shutil.rmtree(floorplan_dir(hass, entry_id), ignore_errors=True)
