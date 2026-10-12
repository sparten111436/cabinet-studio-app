"""Tile positions on the cabinet elevation."""

from __future__ import annotations

from cabinet_studio.models.project import NAMEPLATE_CLEARANCE
from cabinet_studio.models.schema import Library

GRID = 8.0
MIN_X = 16.0
MIN_Y = NAMEPLATE_CLEARANCE
EDGE = 12.0


def snap(value: float, grid: float = GRID) -> float:
    return round(float(value) / grid) * grid


def tile_size(library: Library, type_id: str) -> tuple[float, float]:
    equipment = library.types.get(type_id)
    if equipment is None:
        return (168.0, 92.0)
    return (float(equipment.tile_w), float(equipment.tile_h))


def rects_overlap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
    pad: float = 0.0,
) -> bool:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    return not (
        ax + aw + pad <= bx
        or bx + bw + pad <= ax
        or ay + ah + pad <= by
        or by + bh + pad <= ay
    )


def clamp_position(
    x: float,
    y: float,
    tile_w: float,
    tile_h: float,
    cabinet_width: float,
    cabinet_height: float,
) -> tuple[float, float]:
    max_x = max(MIN_X, cabinet_width - tile_w - EDGE)
    max_y = max(MIN_Y, cabinet_height - tile_h - EDGE)
    snapped_x = min(max(MIN_X, snap(x)), snap(max_x))
    snapped_y = min(max(MIN_Y, snap(y)), snap(max_y))
    snapped_x = min(max(MIN_X, snapped_x), max_x)
    snapped_y = min(max(MIN_Y, snapped_y), max_y)
    return snapped_x, snapped_y


def _occupied(
    project,
    library: Library,
    x: float,
    y: float,
    tile_w: float,
    tile_h: float,
) -> bool:
    proposed = (x, y, tile_w, tile_h)
    for item in project.items:
        other_w, other_h = tile_size(library, item.type_id)
        if rects_overlap(proposed, (item.x, item.y, other_w, other_h), pad=8):
            return True
    return False


def next_free_position(project, library: Library, type_id: str) -> tuple[float, float]:
    tile_w, tile_h = tile_size(library, type_id)
    y = MIN_Y
    while y + tile_h <= project.cabinet_height - EDGE:
        x = 24.0
        while x + tile_w <= project.cabinet_width - EDGE:
            if not _occupied(project, library, x, y, tile_w, tile_h):
                return clamp_position(
                    x, y, tile_w, tile_h, project.cabinet_width, project.cabinet_height
                )
            x += tile_w + 16
        y += tile_h + 16
    return clamp_position(24, MIN_Y, tile_w, tile_h, project.cabinet_width, project.cabinet_height)
