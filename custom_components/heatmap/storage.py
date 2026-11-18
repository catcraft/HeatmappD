"""Floorplan storage helpers.

Floorplans live in ``<config>/.storage/heatmap/<folder>/floorplan.png``. Config
entries store only ``<folder>``, never an absolute path, so a backup restored on
an installation with a different config directory keeps working.

That folder is not served over HTTP; the rendered heatmap is only exposed
through the authenticated image entity.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

from homeassistant.components.file_upload import process_uploaded_file
from homeassistant.core import HomeAssistant

from .const import FLOORPLAN_FILENAME, MAX_FLOORPLAN_PIXELS, STORAGE_SUBDIR


class FloorplanTooLarge(ValueError):
    """The uploaded image has more pixels than a floorplan may have."""


def storage_root(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(".storage", STORAGE_SUBDIR))


def new_floorplan_folder() -> str:
    """Return a fresh, unused folder name for a new floorplan."""
    return uuid4().hex


def is_valid_folder(folder: object) -> bool:
    """Return True if ``folder`` is a plain folder name (no path parts)."""
    return (
        isinstance(folder, str)
        and folder not in ("", ".", "..")
        and Path(folder).name == folder
        and "/" not in folder
        and "\\" not in folder
    )


def floorplan_path(hass: HomeAssistant, folder: str) -> Path:
    """Return the floorplan image path for ``folder``."""
    if not is_valid_folder(folder):
        raise ValueError(f"Invalid floorplan folder: {folder!r}")
    return storage_root(hass) / folder / FLOORPLAN_FILENAME


async def async_save_uploaded_floorplan(
    hass: HomeAssistant, folder: str, file_id: str
) -> tuple[int, int]:
    """Store an uploaded image as PNG in ``folder`` and return (width, height).

    Raises ``OSError`` (including ``PIL.UnidentifiedImageError``) if the upload
    is not a readable image, ``FloorplanTooLarge`` if it has more than
    ``MAX_FLOORPLAN_PIXELS`` pixels and ``ValueError`` if the upload id is
    unknown.
    """
    dest = floorplan_path(hass, folder)
    dest_dir = dest.parent

    def _copy_and_normalize(src: Path) -> tuple[int, int]:
        from PIL import Image

        from .render import flatten_to_rgb

        dest_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=dest_dir, suffix=".png")
        os.close(fd)
        try:
            try:
                img_file = Image.open(src)
            except Image.DecompressionBombError as err:
                raise FloorplanTooLarge(str(err)) from err
            with img_file as img:
                # open() only reads the header, so this check runs before
                # the pixels are decoded into memory.
                width, height = img.size
                if width * height > MAX_FLOORPLAN_PIXELS:
                    raise FloorplanTooLarge(f"{width}x{height} pixels")
                img = flatten_to_rgb(img)
                img.save(tmp_name, format="PNG", optimize=True)
                size = img.size
            os.replace(tmp_name, dest)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        return size

    with process_uploaded_file(hass, file_id) as src_path:
        return await hass.async_add_executor_job(_copy_and_normalize, src_path)


async def async_remove_floorplan(hass: HomeAssistant, folder: str) -> None:
    """Delete the floorplan folder (only a direct child of our storage root)."""
    if not is_valid_folder(folder):
        return
    target = storage_root(hass) / folder

    def _remove() -> None:
        root = storage_root(hass).resolve()
        if target.resolve().parent == root:
            shutil.rmtree(target, ignore_errors=True)

    await hass.async_add_executor_job(_remove)


async def async_remove_orphaned_floorplans(
    hass: HomeAssistant, keep: set[str]
) -> None:
    """Remove floorplan folders that no config entry references any more.

    Covers config flows that were abandoned after the image was uploaded.
    ``keep`` holds folder names, not paths.
    """
    root = storage_root(hass)

    def _cleanup() -> None:
        if not root.is_dir():
            return
        for child in root.iterdir():
            if child.is_dir() and not child.is_symlink() and child.name not in keep:
                shutil.rmtree(child, ignore_errors=True)

    await hass.async_add_executor_job(_cleanup)
