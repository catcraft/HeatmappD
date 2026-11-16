"""Pure NumPy/Pillow renderer for the Heatmap integration."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def _piecewise(x: np.ndarray, xp: Sequence[float], yp: Sequence[float]) -> np.ndarray:
    return np.interp(x, xp, yp)


def _make_jet_lut() -> np.ndarray:
    x = np.linspace(0, 1, 256)
    r = _piecewise(x, [0, 0.35, 0.66, 0.89, 1], [0, 0, 1, 1, 0.5])
    g = _piecewise(x, [0, 0.125, 0.375, 0.64, 0.91, 1], [0, 0, 1, 1, 0, 0])
    b = _piecewise(x, [0, 0.11, 0.34, 0.65, 1], [0.5, 1, 1, 0, 0])
    return (np.stack([r, g, b], axis=1) * 255).astype(np.uint8)


def _make_coolwarm_lut() -> np.ndarray:
    x = np.linspace(0, 1, 256)
    r = _piecewise(x, [0, 0.5, 1], [0.23, 0.87, 0.71])
    g = _piecewise(x, [0, 0.5, 1], [0.30, 0.87, 0.02])
    b = _piecewise(x, [0, 0.5, 1], [0.75, 0.87, 0.15])
    return (np.stack([r, g, b], axis=1) * 255).astype(np.uint8)


def _make_turbo_lut() -> np.ndarray:
    x = np.linspace(0, 1, 256)
    r = np.clip(1.5 - 4 * np.abs(x - 0.75), 0, 1)
    g = np.clip(1.5 - 4 * np.abs(x - 0.5), 0, 1)
    b = np.clip(1.5 - 4 * np.abs(x - 0.25), 0, 1)
    return (np.stack([r, g, b], axis=1) * 255).astype(np.uint8)


def _perceptual(xp, rp, gp, bp):
    x = np.linspace(0, 1, 256)
    return (
        np.stack(
            [_piecewise(x, xp, rp), _piecewise(x, xp, gp), _piecewise(x, xp, bp)],
            axis=1,
        )
        * 255
    ).astype(np.uint8)


_COLORMAPS = {
    "jet": _make_jet_lut(),
    "coolwarm": _make_coolwarm_lut(),
    "turbo": _make_turbo_lut(),
    "viridis": _perceptual(
        [0, 0.25, 0.5, 0.75, 1],
        [0.267, 0.229, 0.127, 0.369, 0.993],
        [0.005, 0.322, 0.567, 0.788, 0.906],
        [0.329, 0.545, 0.551, 0.383, 0.144],
    ),
    "plasma": _perceptual(
        [0, 0.25, 0.5, 0.75, 1],
        [0.050, 0.363, 0.708, 0.952, 0.940],
        [0.030, 0.008, 0.216, 0.520, 0.976],
        [0.528, 0.639, 0.475, 0.204, 0.131],
    ),
    "inferno": _perceptual(
        [0, 0.25, 0.5, 0.75, 1],
        [0.001, 0.258, 0.578, 0.865, 0.988],
        [0, 0.039, 0.148, 0.393, 0.998],
        [0.014, 0.408, 0.404, 0.129, 0.645],
    ),
}


def get_colormap(name: str) -> np.ndarray:
    return _COLORMAPS.get(name, _COLORMAPS["jet"])


def _inside_mask(
    gray: np.ndarray, wall_threshold: int) -> tuple[np.ndarray, np.ndarray]:
    walls = (gray < wall_threshold).astype(np.uint8) * 255
    fill_img = Image.fromarray(walls, mode="L")
    ImageDraw.floodfill(fill_img, xy=(0, 0), value=128, thresh=0)
    filled = np.asarray(fill_img)
    inside = np.where((filled == 0) & (walls == 0), 255, 0).astype(np.uint8)
    return walls, inside


def _idw(
    xx, yy, sensors: Iterable[tuple[float, float, float]], power: float) -> np.ndarray:
    weight_sum = np.zeros_like(xx, dtype=np.float32)
    value_sum = np.zeros_like(xx, dtype=np.float32)
    for x, y, v in sensors:
        d = np.sqrt((xx - x) ** 2 + (yy - y) ** 2) + 1e-5
        wt = 1.0 / (d**power)
        weight_sum += wt
        value_sum += wt * float(v)
    return value_sum / weight_sum


def _luminance(rgb: np.ndarray) -> np.ndarray:
    c = rgb.astype(np.float32) / 255.0
    c = np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * c[..., 0] + 0.7152 * c[..., 1] + 0.0722 * c[..., 2]


def _contrast_text_color(
    image: Image.Image, box: tuple[int, int, int, int]
) -> tuple[int, int, int]:
    """Return black or white, whichever contrasts better with the box area."""
    left, top, right, bottom = box
    left, top = max(0, left), max(0, top)
    right, bottom = min(image.width, right), min(image.height, bottom)
    if right <= left or bottom <= top:
        return (0, 0, 0)
    lum = float(_luminance(np.asarray(image.crop((left, top, right, bottom)))).mean())
    contrast_black = (lum + 0.05) / 0.05
    contrast_white = 1.05 / (lum + 0.05)
    return (0, 0, 0) if contrast_black >= contrast_white else (255, 255, 255)


def render_heatmap(
    floorplan_path: Path,
    sensors: list[dict],
    *,
    vmin: float,
    vmax: float,
    power: float,
    opacity: float,
    colormap: str,
    wall_threshold: int,
    debug_walls: bool,
    downscale: int,
    show_markers: bool,
    marker_radius: int,
    font_size: int = 14,
    auto_text_color: bool = True,
) -> bytes:
    
    with Image.open(floorplan_path) as src:
        src = src.convert("RGB")
        full_w, full_h = src.size
        scale = max(1, int(downscale))
        work_w, work_h = full_w // scale, full_h // scale
        work_img = src.resize((work_w, work_h), Image.BILINEAR)
    work_arr = np.asarray(work_img)
    gray = np.asarray(work_img.convert("L"))
    walls_mask, inside_mask = _inside_mask(gray, wall_threshold)
    result_low = work_arr.copy()

    if sensors:
        yy, xx = np.mgrid[0:work_h, 0:work_w].astype(np.float32)
        scaled = [(s["x"] / scale, s["y"] / scale, s["value"]) for s in sensors]
        temp_map = _idw(xx, yy, scaled, power)
        norm = np.clip((temp_map - vmin) / (vmax - vmin), 0, 1)
        heat_rgb = get_colormap(colormap)[(norm * 255).astype(np.uint8)]
        inside_bool = inside_mask == 255
        alpha = float(opacity)

        result_low[inside_bool] = (
            alpha * heat_rgb[inside_bool].astype(np.float32)
            + (1 - alpha) * work_arr[inside_bool].astype(np.float32)
        ).astype(np.uint8)

    result_low[walls_mask == 255] = [255, 0, 0] if debug_walls else [0, 0, 0]
    composite = Image.fromarray(result_low).resize((full_w, full_h), Image.NEAREST)

    if show_markers and sensors:
        draw = ImageDraw.Draw(composite)
        font = ImageFont.load_default(size=max(6, int(font_size)))
        r = int(marker_radius)
        inner = max(1, r - 5)
        for s in sensors:
            x, y = int(s["x"]), int(s["y"])
            draw.ellipse([x - r, y - r, x + r, y + r], fill=(0, 0, 0))
            draw.ellipse(
                [x - inner, y - inner, x + inner, y + inner], fill=(255, 255, 255)
            )
            label = s.get("label") or f'{s["value"]:.1f}'
            pos = (x + r + 4, y - int(font_size) // 2 - 1)
            fill = (0, 0, 0)
            if auto_text_color:
                box = draw.textbbox(pos, str(label), font=font)
                fill = _contrast_text_color(composite, box)
            draw.text(pos, str(label), fill=fill, font=font)
            
    buf = BytesIO()
    composite.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
