"""Pure NumPy/Pillow renderer for the Heatmap integration."""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Sequence

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


def flatten_to_rgb(img: Image.Image) -> Image.Image:
    """Return ``img`` as RGB, with transparent areas shown as white.

    A plain ``convert("RGB")`` drops the alpha channel and keeps whatever
    colour the transparent pixels hold, which is usually black. The whole
    background of a transparent floorplan would then count as wall.
    """
    if img.mode in ("RGBA", "LA", "PA") or (
        img.mode in ("P", "L", "RGB") and "transparency" in img.info
    ):
        rgba = img.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        background.alpha_composite(rgba)
        return background.convert("RGB")
    return img.convert("RGB")


@dataclass(frozen=True, eq=False)
class Floorplan:
    """The parts of a render that only depend on the floorplan.

    They are cached between renders; ``key`` says which file and settings
    they were made from. The arrays are read-only so a render cannot change
    the cached copy.
    """

    key: tuple
    full_size: tuple[int, int]
    scale: tuple[float, float]  # full size / work size, per axis
    work: np.ndarray  # (h, w, 3) uint8, downscaled floorplan
    walls: np.ndarray  # (h, w) bool
    inside: np.ndarray  # (h, w) bool, rooms enclosed by walls


def normalize_downscale(downscale: float) -> float:
    """Return a usable downscale factor (1 or more, one decimal)."""
    return round(max(1.0, float(downscale)), 1)


def floorplan_key(path: Path, wall_threshold: int, downscale: float) -> tuple:
    """Return the cache key for ``path`` with these settings.

    Replacing the floorplan writes a new file (``os.replace``), which changes
    the inode, mtime and usually the size.
    """
    st = path.stat()
    return (
        str(path),
        st.st_ino,
        st.st_mtime_ns,
        st.st_size,
        int(wall_threshold),
        normalize_downscale(downscale),
    )


def _inside_mask(walls: np.ndarray) -> np.ndarray:
    """Return the pixels that are neither wall nor connected to the border.

    The mask is padded with a one pixel non-wall frame before the flood fill,
    so the fill starts from every border pixel at once. A dark corner or a
    frame around the plan then no longer decides what counts as outside.
    """
    padded = np.pad(walls, 1, constant_values=False)
    # fromarray() returns a read-only image that shares the array's memory;
    # floodfill() silently changes nothing on it (seen on Pillow 12), so fill
    # a copy.
    fill_img = Image.fromarray(np.where(padded, 255, 0).astype(np.uint8)).copy()
    ImageDraw.floodfill(fill_img, xy=(0, 0), value=128, thresh=0)
    outside_or_wall = np.asarray(fill_img)[1:-1, 1:-1] != 0
    return ~outside_or_wall


def load_floorplan(path: Path, wall_threshold: int, downscale: float) -> Floorplan:
    """Read the floorplan and compute its wall and room masks.

    ``downscale`` may be fractional; the work grid is rounded to whole
    pixels and the exact per-axis factors are kept in ``Floorplan.scale``.
    """
    key = floorplan_key(path, wall_threshold, downscale)
    factor = key[-1]
    with Image.open(path) as src:
        rgb = flatten_to_rgb(src)
    full_w, full_h = rgb.size
    work_w = max(1, round(full_w / factor))
    work_h = max(1, round(full_h / factor))
    work_img = rgb.resize((work_w, work_h), Image.BILINEAR)
    work = np.array(work_img)
    walls = np.asarray(work_img.convert("L")) < int(wall_threshold)
    inside = _inside_mask(walls)
    for arr in (work, walls, inside):
        arr.setflags(write=False)
    return Floorplan(
        key, (full_w, full_h), (full_w / work_w, full_h / work_h), work, walls, inside
    )


def _idw(
    xx: np.ndarray,
    yy: np.ndarray,
    sensors: Sequence[tuple[float, float, float]],
    power: float,
) -> np.ndarray:
    """Inverse distance weighting.

    Every weight is divided by the weight of the nearest sensor, which does
    not change the result but keeps all weights in (0, 1] and their sum at
    1 or more. ``1 / d**power`` overflowed in float32 at higher powers and
    gave NaN at a sensor's own pixel (inf / inf) or far away (0 / 0).
    Distances below half a grid cell are treated as half a cell.
    """

    def dist(x: float, y: float) -> np.ndarray:
        return np.maximum(np.hypot(xx - x, yy - y), np.float32(0.5))

    nearest: np.ndarray | None = None
    for x, y, _ in sensors:
        d = dist(x, y)
        nearest = d if nearest is None else np.minimum(nearest, d, out=nearest)

    weight_sum = np.zeros_like(xx, dtype=np.float32)
    value_sum = np.zeros_like(xx, dtype=np.float32)
    for x, y, v in sensors:
        wt = (nearest / dist(x, y)) ** np.float32(power)
        weight_sum += wt
        value_sum += wt * np.float32(v)
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
    floorplan: Floorplan,
    sensors: list[dict],
    *,
    vmin: float,
    vmax: float,
    power: float,
    opacity: float,
    colormap: str,
    debug_walls: bool,
    show_markers: bool,
    marker_radius: int,
    font_size: int = 14,
    auto_text_color: bool = True,
    max_side: int | None = None,
) -> bytes:
    """Render the heatmap over a floorplan from ``load_floorplan``.

    With ``max_side`` the result is shrunk (keeping its aspect ratio) so its
    longest side is at most that many pixels.
    """
    full_w, full_h = floorplan.full_size
    scale_x, scale_y = floorplan.scale
    work_arr = floorplan.work
    work_h, work_w = work_arr.shape[:2]
    result_low = work_arr.copy()

    if sensors:
        yy, xx = np.mgrid[0:work_h, 0:work_w].astype(np.float32)
        scaled = [(s["x"] / scale_x, s["y"] / scale_y, s["value"]) for s in sensors]
        temp_map = _idw(xx, yy, scaled, power)
        span = vmax - vmin if vmax > vmin else 1e-6
        norm = np.clip((temp_map - vmin) / span, 0, 1)
        heat_rgb = get_colormap(colormap)[(norm * 255).astype(np.uint8)]
        inside = floorplan.inside
        alpha = min(1.0, max(0.0, float(opacity)))

        result_low[inside] = (
            alpha * heat_rgb[inside].astype(np.float32)
            + (1 - alpha) * work_arr[inside].astype(np.float32)
        ).astype(np.uint8)

    result_low[floorplan.walls] = [255, 0, 0] if debug_walls else [0, 0, 0]
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

    if max_side and max(composite.size) > max_side:
        composite.thumbnail((max_side, max_side), Image.BILINEAR)

    # optimize=True tried every filter at maximum compression on each render,
    # which is slow for large floorplans; the default level is a good trade.
    buf = BytesIO()
    composite.save(buf, format="PNG")
    return buf.getvalue()
