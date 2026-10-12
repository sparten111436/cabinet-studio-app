"""Educational ladder print SVG — nested-OR-aware branch geometry (v0.3.5+ / v0.3.8 packing).

v0.3.6: ONS / OSR / OSF one-shot symbols, multi-line rung comment blocks
(Do-more / Studio-style rung documentation), and instruction notes printed
under each symbol.

Builds print sheets from IR element lists so nested parallel branches draw
true fork/join rails (matching the on-screen Programming canvas), not a
flattened single-level parallel zone. Ideas only from public ladder print
layouts — no proprietary assets.
"""

from __future__ import annotations

import html
from typing import Any

from cabinet_studio.services.ladder_ir import (
    clean_elements,
    elements_have_nested_or,
    program_rung_to_elements,
)

# Geometry (aligned with programming_viewer constants)
LADDER_BG = "#d8d4cc"
LADDER_RAIL = "#1a1a22"
LADDER_WIRE = "#2a2a32"
LADDER_SYMBOL = "#0d0d0f"
LADDER_LABEL = "#1c1c22"
LADDER_MUTED = "#5a5a66"
LADDER_COIL = "#0b5e4a"
LADDER_TIMER = "#5b3d8a"
LADDER_COUNTER = "#8a4b12"
LADDER_COMPARE = "#0a5a7a"
LADDER_MATH = "#5a3a0a"
LADDER_ONESHOT = "#7a1f5c"
LADDER_JSR = "#1a4a6e"
LADDER_NOTE = "#3d4a5c"

CONTACT_HALF_H = 18
CONTACT_GAP = 8  # v0.3.11: tighter so wires meet contact bars
CONTACT_COL_W = 120
BRANCH_ROW_H = 96  # v0.3.11: less overlap with title band
TITLE_BAND = 28  # v0.3.11: keep OR forks below title
BOTTOM_PAD = 16
COIL_RADIUS = 22
TIMER_BOX_W, TIMER_BOX_H = 92, 56
COUNTER_BOX_W, COUNTER_BOX_H = 92, 64
COMPARE_BOX_W, COMPARE_BOX_H = 100, 56
MATH_BOX_W, MATH_BOX_H = 110, 64
ONESHOT_BOX_W, ONESHOT_BOX_H = 76, 44
ONESHOT_OUT_BOX_W, ONESHOT_OUT_BOX_H = 96, 56
JSR_BOX_W, JSR_BOX_H = 100, 48
RET_BOX_W, RET_BOX_H = 64, 40
SBR_BOX_W, SBR_BOX_H = 100, 40
COMMENT_LINE_H = 14
COMMENT_WRAP = 110
COMMENT_MAX_LINES = 5
NOTE_CHARS = 22
RAIL_INSET = 68
INTER_RUNG_GAP = 18


def or_branch_rows(els: list | None) -> int:
    rows = 1
    for el in els or []:
        if not isinstance(el, dict):
            continue
        if str(el.get("kind") or "").lower() != "or":
            continue
        branch_rows = 0
        for br in el.get("branches") or []:
            branch_rows += max(1, or_branch_rows(br))
        rows = max(rows, max(1, branch_rows))
    return rows


def comment_lines(comment: str | None, *, wrap: int = COMMENT_WRAP, max_lines: int = COMMENT_MAX_LINES) -> list[str]:
    """Wrap a (multi-line) rung comment into print lines; first line is the title."""
    import textwrap

    lines: list[str] = []
    for para in str(comment or "").replace("\r\n", "\n").split("\n"):
        para = para.strip()
        if not para:
            if lines:
                lines.append("")
            continue
        lines.extend(textwrap.wrap(para, width=wrap) or [""])
    while lines and not lines[-1]:
        lines.pop()
    if len(lines) > max_lines:
        lines = lines[: max_lines - 1] + [lines[max_lines - 1][: wrap - 1] + "…"]
    return lines


def comment_extra_height(comment: str | None) -> float:
    """Extra band (px) for comment lines beyond the title line."""
    return max(0, len(comment_lines(comment)) - 1) * COMMENT_LINE_H


def rung_block_height_from_elements(elements: list | None, comment: str = "") -> float:
    return TITLE_BAND + comment_extra_height(comment) + or_branch_rows(elements) * BRANCH_ROW_H + BOTTOM_PAD


def rung_elements(rung: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(rung.get("elements"), list) and rung.get("elements"):
        return clean_elements(rung.get("elements"))
    return program_rung_to_elements(rung)


def _line(x1: float, y1: float, x2: float, y2: float, *, stroke: str = LADDER_WIRE, width: float = 2) -> str:
    return (
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
        f'stroke="{stroke}" stroke-width="{width}"/>'
    )


def _text(x: float, y: float, text: str, *, fill: str = LADDER_LABEL, size: int = 11, anchor: str = "middle", bold: bool = False) -> str:
    weight = ' font-weight="bold"' if bold else ""
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" fill="{fill}" '
        f'font-size="{size}"{weight} font-family="Consolas, Segoe UI, Arial">'
        f"{html.escape(text)}</text>"
    )


def svg_contact(x: float, y: float, el: dict[str, Any]) -> list[str]:
    tag = str(el.get("var") or el.get("tag") or "").strip() or "?"
    nc = str(el.get("form", "NO")).upper() == "NC" or bool(el.get("normally_closed"))
    h, gap = CONTACT_HALF_H, CONTACT_GAP
    out = [
        _line(x - gap / 2, y - h, x - gap / 2, y + h, stroke=LADDER_SYMBOL, width=3),
        _line(x + gap / 2, y - h, x + gap / 2, y + h, stroke=LADDER_SYMBOL, width=3),
    ]
    if nc:
        out.append(_line(x - gap / 2 - 2, y + h - 2, x + gap / 2 + 2, y - h + 2, stroke=LADDER_SYMBOL, width=2))
    out.append(_text(x, y - h - 6, tag, fill=LADDER_LABEL, size=11, bold=True))
    return out


def svg_coil(x: float, y: float, el: dict[str, Any]) -> list[str]:
    tag = str(el.get("var") or "").strip() or "?"
    form = str(el.get("form") or "normal").lower()
    r = COIL_RADIUS
    mark = ""
    if form in {"negated", "not", "nc"}:
        mark = "/"
    elif form in {"set", "s"}:
        mark = "S"
    elif form in {"reset", "r"}:
        mark = "R"
    out = [
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{LADDER_BG}" '
        f'stroke="{LADDER_COIL}" stroke-width="2.5"/>',
        _text(x, y - r - 6, tag, fill=LADDER_COIL, size=11, bold=True),
    ]
    if mark:
        out.append(_text(x, y + 5, mark, fill=LADDER_COIL, size=14, bold=True))
    return out


def svg_timer(x: float, y: float, el: dict[str, Any]) -> list[str]:
    tag = str(el.get("var") or "").strip() or "?"
    block = str(el.get("block") or "TON").upper()
    pt = int(el.get("pt_ms") or 0)
    w, h = TIMER_BOX_W, TIMER_BOX_H
    return [
        f'<rect x="{x - w / 2:.1f}" y="{y - h / 2:.1f}" width="{w}" height="{h}" '
        f'fill="{LADDER_BG}" stroke="{LADDER_TIMER}" stroke-width="2"/>',
        _text(x, y - h / 2 - 6, tag, fill=LADDER_TIMER, size=11, bold=True),
        _text(x, y - 4, block, fill=LADDER_LABEL, size=12, bold=True),
        _text(x, y + 14, (f"PT {el.get('pt_tag')}" if str(el.get("pt_tag") or "").strip() else f"PT {pt}ms"), fill=LADDER_MUTED, size=10),
    ]


def svg_counter(x: float, y: float, el: dict[str, Any]) -> list[str]:
    tag = str(el.get("var") or "").strip() or "?"
    block = str(el.get("block") or "CTU").upper()
    pv = int(el.get("pv") or 0)
    w, h = COUNTER_BOX_W, COUNTER_BOX_H
    return [
        f'<rect x="{x - w / 2:.1f}" y="{y - h / 2:.1f}" width="{w}" height="{h}" '
        f'fill="{LADDER_BG}" stroke="{LADDER_COUNTER}" stroke-width="2"/>',
        _text(x, y - h / 2 - 6, tag, fill=LADDER_COUNTER, size=11, bold=True),
        _text(x, y - 6, block, fill=LADDER_LABEL, size=12, bold=True),
        _text(x, y + 12, (f"PRE {el.get('pv_tag')}" if str(el.get("pv_tag") or "").strip() else f"PRE {pv}"), fill=LADDER_MUTED, size=10),
    ]


def svg_compare(x: float, y: float, el: dict[str, Any]) -> list[str]:
    op = str(el.get("op") or "EQU").upper()
    a = str(el.get("source_a") or el.get("a") or "?").strip()
    b = str(el.get("source_b") or el.get("b") or "?").strip()
    c = str(el.get("source_c") or el.get("c") or "").strip()
    w, h = COMPARE_BOX_W, COMPARE_BOX_H
    if op == "LIM":
        detail = f"{b}≤{a}≤{c}" if c else f"{b}≤{a}"
    elif op == "MEQ":
        detail = f"{a}&{b}=={c}&{b}" if c else f"{a}&{b}"
    else:
        detail = b
    return [
        f'<rect x="{x - w / 2:.1f}" y="{y - h / 2:.1f}" width="{w}" height="{h}" '
        f'fill="{LADDER_BG}" stroke="{LADDER_COMPARE}" stroke-width="2"/>',
        _text(x, y - h / 2 - 6, op, fill=LADDER_COMPARE, size=11, bold=True),
        _text(x, y - 2, a if op not in {"LIM", "MEQ"} else detail[:18], fill=LADDER_LABEL, size=10, bold=True),
        _text(x, y + 14, detail if op in {"LIM", "MEQ"} else b, fill=LADDER_MUTED, size=9 if op in {"LIM", "MEQ"} else 10),
    ]


def svg_math(x: float, y: float, el: dict[str, Any]) -> list[str]:
    op = str(el.get("op") or "ADD").upper()
    dest = str(el.get("dest") or "?").strip()
    a = str(el.get("source_a") or el.get("a") or "").strip()
    b = str(el.get("source_b") or el.get("b") or "").strip()
    w, h = MATH_BOX_W, MATH_BOX_H
    if op == "MOV":
        detail = f"{a}→{dest}"
    elif op == "CPT":
        detail = str(el.get("expression") or a)[:18]
    elif op == "NOT":
        detail = f"~{a}"
    elif op in {"AND", "OR", "XOR"}:
        detail = f"{a},{b}"
    else:
        detail = f"{a},{b}"
    return [
        f'<rect x="{x - w / 2:.1f}" y="{y - h / 2:.1f}" width="{w}" height="{h}" '
        f'fill="{LADDER_BG}" stroke="{LADDER_MATH}" stroke-width="2"/>',
        _text(x, y - h / 2 - 6, dest, fill=LADDER_MATH, size=11, bold=True),
        _text(x, y - 4, op, fill=LADDER_LABEL, size=12, bold=True),
        _text(x, y + 14, detail, fill=LADDER_MUTED, size=9),
    ]


def svg_oneshot(x: float, y: float, el: dict[str, Any]) -> list[str]:
    block = str(el.get("block") or "ONS").upper()
    storage = str(el.get("var") or "?").strip()
    output = str(el.get("output") or "").strip()
    if block == "ONS":
        w, h = ONESHOT_BOX_W, ONESHOT_BOX_H
        return [
            f'<rect x="{x - w / 2:.1f}" y="{y - h / 2:.1f}" width="{w}" height="{h}" '
            f'fill="{LADDER_BG}" stroke="{LADDER_ONESHOT}" stroke-width="2"/>',
            _text(x, y - h / 2 - 6, storage, fill=LADDER_ONESHOT, size=11, bold=True),
            _text(x, y + 5, "ONS", fill=LADDER_LABEL, size=12, bold=True),
        ]
    w, h = ONESHOT_OUT_BOX_W, ONESHOT_OUT_BOX_H
    edge = "rising" if block == "OSR" else "falling"
    return [
        f'<rect x="{x - w / 2:.1f}" y="{y - h / 2:.1f}" width="{w}" height="{h}" '
        f'fill="{LADDER_BG}" stroke="{LADDER_ONESHOT}" stroke-width="2"/>',
        _text(x, y - h / 2 - 6, f"{block} ({edge})", fill=LADDER_ONESHOT, size=11, bold=True),
        _text(x, y - 4, f"S {storage}", fill=LADDER_LABEL, size=10, bold=True),
        _text(x, y + 14, f"O {output or '?'}", fill=LADDER_MUTED, size=10),
    ]


def svg_note(x: float, y: float, el: dict[str, Any], *, below: float) -> list[str]:
    note = str(el.get("desc") or "").strip()
    if not note:
        return []
    short = note if len(note) <= NOTE_CHARS else note[: NOTE_CHARS - 1] + "…"
    return [
        f'<text x="{x:.1f}" y="{y + below:.1f}" text-anchor="middle" fill="{LADDER_NOTE}" '
        f'font-size="9" font-style="italic" font-family="Segoe UI, Arial">{html.escape(short)}</text>'
    ]



def svg_jsr(x: float, y: float, el: dict[str, Any]) -> list[str]:
    w, h = JSR_BOX_W, JSR_BOX_H
    target = html.escape(str(el.get("target") or ""))
    return [
        f'<rect x="{x - w / 2:.1f}" y="{y - h / 2:.1f}" width="{w}" height="{h}" '
        f'fill="none" stroke="{LADDER_JSR}" stroke-width="2"/>',
        _text(x, y - 8, "JSR", fill=LADDER_JSR, size=11, bold=True),
        _text(x, y + 10, target, fill=LADDER_LABEL, size=10),
    ]


def svg_sbr(x: float, y: float, el: dict[str, Any]) -> list[str]:
    w, h = SBR_BOX_W, SBR_BOX_H
    name = html.escape(str(el.get("name") or ""))
    return [
        f'<rect x="{x - w / 2:.1f}" y="{y - h / 2:.1f}" width="{w}" height="{h}" '
        f'fill="none" stroke="{LADDER_JSR}" stroke-width="1.5" stroke-dasharray="4 3"/>',
        _text(x, y - 6, "SBR", fill=LADDER_JSR, size=10, bold=True),
        _text(x, y + 10, name, fill=LADDER_LABEL, size=10),
    ]


def svg_ret(x: float, y: float, el: dict[str, Any] | None = None) -> list[str]:
    w, h = RET_BOX_W, RET_BOX_H
    return [
        f'<rect x="{x - w / 2:.1f}" y="{y - h / 2:.1f}" width="{w}" height="{h}" '
        f'fill="none" stroke="{LADDER_JSR}" stroke-width="2"/>',
        _text(x, y, "RET", fill=LADDER_JSR, size=11, bold=True),
    ]


def _symbol_half_h(el: dict[str, Any]) -> float:
    kind = str(el.get("kind") or "").lower()
    return {
        "contact": CONTACT_HALF_H,
        "coil": COIL_RADIUS,
        "timer": TIMER_BOX_H / 2,
        "counter": COUNTER_BOX_H / 2,
        "compare": COMPARE_BOX_H / 2,
        "math": MATH_BOX_H / 2,
        "oneshot": (ONESHOT_BOX_H if str(el.get("block") or "ONS").upper() == "ONS" else ONESHOT_OUT_BOX_H) / 2,
    }.get(kind, 20)


def _oneshot_w(el: dict[str, Any]) -> float:
    return ONESHOT_BOX_W if str(el.get("block") or "ONS").upper() == "ONS" else ONESHOT_OUT_BOX_W


def _emit_el(el: dict[str, Any], x: float, y: float) -> tuple[list[str], float, float]:
    """Return (svg parts, width used, center x of symbol)."""
    parts, width, cx = _emit_el_core(el, x, y)
    parts = parts + svg_note(cx, y, el, below=_symbol_half_h(el) + 14)
    return parts, width, cx


def _emit_el_core(el: dict[str, Any], x: float, y: float) -> tuple[list[str], float, float]:
    kind = str(el.get("kind") or "").lower()
    if kind == "oneshot":
        return svg_oneshot(x, y, el), _oneshot_w(el) + 16, x
    if kind == "contact":
        return svg_contact(x, y, el), CONTACT_COL_W, x
    if kind == "coil":
        return svg_coil(x, y, el), COIL_RADIUS * 2 + 24, x
    if kind == "timer":
        return svg_timer(x, y, el), TIMER_BOX_W + 16, x
    if kind == "counter":
        return svg_counter(x, y, el), COUNTER_BOX_W + 16, x
    if kind == "compare":
        return svg_compare(x, y, el), COMPARE_BOX_W + 16, x
    if kind == "math":
        return svg_math(x, y, el), MATH_BOX_W + 16, x
    if kind == "jsr":
        return svg_jsr(x, y, el), JSR_BOX_W + 16, x
    if kind == "sbr":
        return svg_sbr(x, y, el), SBR_BOX_W + 16, x
    if kind == "ret":
        return svg_ret(x, y, el), RET_BOX_W + 16, x
    return [], 40.0, x


def _svg_or(el: dict[str, Any], x0: float, y0: float) -> tuple[list[str], float]:
    """Draw nested OR with fork/join; return (parts, join_x)."""
    parts: list[str] = []
    branches = list(el.get("branches") or []) or [[]]
    n = len(branches)
    # Compute vertical span accounting for nested OR height
    def branch_span(br: list) -> int:
        return max(1, or_branch_rows(br))

    spans = [branch_span(br) for br in branches]
    total_rows = sum(spans)
    # v0.3.11: grow downward from the bus so top branch does not hit the title.
    row_cursor = 0.0
    branch_ys: list[float] = []
    branch_end_xs: list[float] = []
    for bi, branch in enumerate(branches):
        span = spans[bi]
        # middle row of this branch group
        mid_offset = row_cursor + (span - 1) / 2.0
        by = y0 + mid_offset * BRANCH_ROW_H
        branch_ys.append(by)
        parts.append(_line(x0, y0, x0, by))
        parts.append(_line(x0, by, x0 + 16, by))
        cx = x0 + 16 + 56
        last_end = x0 + 16
        for item in branch:
            kind = str(item.get("kind") or "").lower()
            if kind == "or":
                sub_parts, join = _svg_or(item, cx - 40, by)
                parts.extend(sub_parts)
                cx = join + 20
                last_end = join
            else:
                parts.append(_line(cx - 56, by, cx - CONTACT_GAP / 2, by))
                el_parts, width, _ = _emit_el(item, cx, by)
                parts.extend(el_parts)
                last_end = cx + CONTACT_GAP / 2 + 2
                cx += max(width, CONTACT_COL_W)
        branch_end_xs.append(last_end)
        row_cursor += span

    join_x = (max(branch_end_xs) if branch_end_xs else x0 + 80) + 24
    if len(branch_ys) > 1:
        parts.append(_line(join_x, branch_ys[0], join_x, branch_ys[-1]))
    for by, ex in zip(branch_ys, branch_end_xs):
        parts.append(_line(ex, by, join_x, by))
    return parts, join_x


def svg_rung_from_elements(
    elements: list[dict[str, Any]],
    *,
    index: int = 1,
    left: float = RAIL_INSET,
    right: float = 1000 - RAIL_INSET,
    y: float = 36.0,
    comment: str = "",
) -> tuple[list[str], float]:
    """Render one rung; return (svg parts, block height)."""
    elements = clean_elements(elements)
    block_h = rung_block_height_from_elements(elements, comment)
    out: list[str] = [
        _line(left, y, left, y + block_h, stroke=LADDER_RAIL, width=4),
        _line(right, y, right, y + block_h, stroke=LADDER_RAIL, width=4),
    ]
    lines = comment_lines(comment)
    title = f"Rung {index}"
    if lines:
        title = f"Rung {index}: {lines[0][:COMMENT_WRAP]}"
    out.append(_text(left + 10, y + 16, title, fill=LADDER_MUTED, size=11, anchor="start", bold=bool(lines)))
    for li, line in enumerate(lines[1:], start=1):
        out.append(
            f'<text x="{left + 22:.1f}" y="{y + 16 + li * COMMENT_LINE_H:.1f}" text-anchor="start" '
            f'fill="{LADDER_NOTE}" font-size="10" font-style="italic" '
            f'font-family="Segoe UI, Arial">{html.escape(line)}</text>'
        )
    extra = comment_extra_height(comment)
    if extra:
        out.append(
            f'<rect x="{left + 6:.1f}" y="{y + 3:.1f}" width="{min(right - left - 12, 760):.1f}" '
            f'height="{18 + extra:.1f}" fill="none" stroke="{LADDER_NOTE}" stroke-width="0.6" '
            f'stroke-dasharray="3,2"/>'
        )

    bus_y = y + TITLE_BAND + extra + BRANCH_ROW_H / 2
    cursor = left + 24
    out.append(_line(left, bus_y, cursor, bus_y))

    for el in elements:
        kind = str(el.get("kind") or "").lower()
        if kind == "or":
            parts, join = _svg_or(el, cursor, bus_y)
            out.extend(parts)
            cursor = join + 12
        elif kind == "oneshot":
            w = _oneshot_w(el)
            out.append(_line(cursor, bus_y, cursor + 20, bus_y))
            out.extend(svg_oneshot(cursor + 20 + w / 2, bus_y, el))
            out.extend(svg_note(cursor + 20 + w / 2, bus_y, el, below=_symbol_half_h(el) + 14))
            cursor = cursor + 20 + w + 12
        elif kind == "contact":
            out.append(_line(cursor, bus_y, cursor + 40 - CONTACT_GAP / 2, bus_y))
            out.extend(svg_contact(cursor + 56, bus_y, el))
            out.extend(svg_note(cursor + 56, bus_y, el, below=CONTACT_HALF_H + 14))
            cursor = cursor + 56 + CONTACT_COL_W / 2
        elif kind == "coil":
            out.append(_line(cursor, bus_y, cursor + 40 - COIL_RADIUS, bus_y))
            out.extend(svg_coil(cursor + 40, bus_y, el))
            out.extend(svg_note(cursor + 40, bus_y, el, below=COIL_RADIUS + 14))
            cursor = cursor + 40 + COIL_RADIUS + 16
        elif kind == "timer":
            out.append(_line(cursor, bus_y, cursor + 20, bus_y))
            out.extend(svg_timer(cursor + 20 + TIMER_BOX_W / 2, bus_y, el))
            out.extend(svg_note(cursor + 20 + TIMER_BOX_W / 2, bus_y, el, below=_symbol_half_h(el) + 14))
            cursor = cursor + 20 + TIMER_BOX_W + 12
        elif kind == "counter":
            out.append(_line(cursor, bus_y, cursor + 20, bus_y))
            out.extend(svg_counter(cursor + 20 + COUNTER_BOX_W / 2, bus_y, el))
            out.extend(svg_note(cursor + 20 + COUNTER_BOX_W / 2, bus_y, el, below=_symbol_half_h(el) + 14))
            cursor = cursor + 20 + COUNTER_BOX_W + 12
        elif kind == "compare":
            out.append(_line(cursor, bus_y, cursor + 20, bus_y))
            out.extend(svg_compare(cursor + 20 + COMPARE_BOX_W / 2, bus_y, el))
            out.extend(svg_note(cursor + 20 + COMPARE_BOX_W / 2, bus_y, el, below=_symbol_half_h(el) + 14))
            cursor = cursor + 20 + COMPARE_BOX_W + 12
        elif kind == "math":
            out.append(_line(cursor, bus_y, cursor + 20, bus_y))
            out.extend(svg_math(cursor + 20 + MATH_BOX_W / 2, bus_y, el))
            out.extend(svg_note(cursor + 20 + MATH_BOX_W / 2, bus_y, el, below=_symbol_half_h(el) + 14))
            cursor = cursor + 20 + MATH_BOX_W + 12
        elif kind == "jsr":
            out.append(_line(cursor, bus_y, cursor + 20, bus_y))
            out.extend(svg_jsr(cursor + 20 + JSR_BOX_W / 2, bus_y, el))
            out.extend(svg_note(cursor + 20 + JSR_BOX_W / 2, bus_y, el, below=_symbol_half_h(el) + 14))
            cursor = cursor + 20 + JSR_BOX_W + 12
        elif kind == "sbr":
            out.append(_line(cursor, bus_y, cursor + 20, bus_y))
            out.extend(svg_sbr(cursor + 20 + SBR_BOX_W / 2, bus_y, el))
            out.extend(svg_note(cursor + 20 + SBR_BOX_W / 2, bus_y, el, below=_symbol_half_h(el) + 14))
            cursor = cursor + 20 + SBR_BOX_W + 12
        elif kind == "ret":
            out.append(_line(cursor, bus_y, cursor + 20, bus_y))
            out.extend(svg_ret(cursor + 20 + RET_BOX_W / 2, bus_y, el))
            out.extend(svg_note(cursor + 20 + RET_BOX_W / 2, bus_y, el, below=_symbol_half_h(el) + 14))
            cursor = cursor + 20 + RET_BOX_W + 12
    out.append(_line(cursor, bus_y, right, bus_y))
    if elements_have_nested_or(elements):
        out.append(_text(right - 8, y + 16, "nested-OR", fill=LADDER_MUTED, size=10, anchor="end"))
    return out, block_h


def ladder_program_to_svg(
    rungs: list[dict[str, Any]] | None,
    *,
    width: int = 1000,
    start_index: int = 1,
    sheet_label: str = "",
    project_name: str = "",
) -> tuple[str, int, int]:
    """Full ladder sheet SVG body + dimensions."""
    left = float(RAIL_INSET)
    right = float(width - RAIL_INSET)
    parts: list[str] = [
        f'<rect x="0" y="0" width="{width}" height="9999" fill="{LADDER_BG}"/>',
        _text(
            left,
            18,
            "Ladder  |  [ ] NO  [/] NC  ( ) coil  (S)/(R) latch  [ONS]/[OSR]/[OSF]  [JSR]/[SBR]/[RET]  [CMP]  [MATH]  [TON]  [CTU]",
            fill=LADDER_MUTED,
            size=11,
            anchor="start",
        ),
    ]
    rungs = list(rungs or [])
    if not rungs:
        parts.append(
            _text(width / 2, 120, "No rungs yet", fill=LADDER_MUTED, size=14)
        )
        return "\n".join(parts), width, 240

    y = 36.0
    for index, rung in enumerate(rungs, start=max(1, int(start_index or 1))):
        els = rung_elements(rung)
        comment = str(rung.get("comment") or "")
        rung_parts, block_h = svg_rung_from_elements(
            els, index=index, left=left, right=right, y=y, comment=comment
        )
        parts.extend(rung_parts)
        y += block_h + INTER_RUNG_GAP
    # Title block + design-aid footer (v0.3.13: exact UL line once + NFPA/ISO note)
    from cabinet_studio.services.drawings import DISCLAIMER as UL_DESIGN_AID
    from cabinet_studio.services.ladder_templates import SAFETY_DESIGN_AID_NOTE

    footer_y = y + 8
    proj = (project_name or sheet_label or "Cabinet Studio").strip()
    parts.append(_text(left, footer_y, f"{proj}", fill=LADDER_MUTED, size=10, anchor="start"))
    parts.append(
        _text(
            right,
            footer_y,
            UL_DESIGN_AID,
            fill=LADDER_MUTED,
            size=9,
            anchor="end",
        )
    )
    parts.append(
        _text(
            left,
            footer_y + 14,
            SAFETY_DESIGN_AID_NOTE,
            fill=LADDER_MUTED,
            size=8,
            anchor="start",
        )
    )
    height = int(footer_y + 36)
    parts[0] = f'<rect x="0" y="0" width="{width}" height="{height}" fill="{LADDER_BG}"/>'
    return "\n".join(parts), width, height


def nested_or_geometry_metrics(elements: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Test helper: counts fork/join cues in generated SVG for nested OR."""
    parts, block_h = svg_rung_from_elements(clean_elements(elements or []), index=1)
    svg = "\n".join(parts)
    # Vertical join rails appear as lines with equal x1/x2 and different y
    import re

    vert = 0
    for m in re.finditer(
        r'<line x1="([\d.]+)" y1="([\d.]+)" x2="([\d.]+)" y2="([\d.]+)"',
        svg,
    ):
        x1, y1, x2, y2 = map(float, m.groups())
        if abs(x1 - x2) < 0.2 and abs(y1 - y2) > 1.0:
            vert += 1
    return {
        "block_h": block_h,
        "rows": or_branch_rows(elements),
        "vertical_rails": vert,
        "has_nested_marker": "nested-OR" in svg,
        "svg": svg,
    }

PAGE_CONTENT_H = 680  # v0.3.11: fits Letter with 0.6in margins (~720pt usable)


def pack_rungs_onto_pages(
    rungs: list[dict[str, Any]] | None,
    *,
    width: int = 1000,
    page_content_h: float = PAGE_CONTENT_H,
) -> list[list[dict[str, Any]]]:
    """Partition rungs into pages so each page's SVG body fits ``page_content_h``.

    Tighter TITLE_BAND / INTER_RUNG_GAP (v0.3.8) packs more rungs per sheet.
    """
    left = float(RAIL_INSET)
    right = float(width - RAIL_INSET)
    pages: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    y = 36.0  # legend band
    for rung in list(rungs or []):
        els = rung_elements(rung)
        comment = str(rung.get("comment") or "")
        block_h = rung_block_height_from_elements(els, comment)
        need = block_h + INTER_RUNG_GAP
        if current and y + need > page_content_h:
            pages.append(current)
            current = []
            y = 36.0
        current.append(rung)
        y += need
    if current or not pages:
        pages.append(current)
    return pages


def ladder_program_to_svg_pages(
    rungs: list[dict[str, Any]] | None,
    *,
    width: int = 1000,
    page_content_h: float = PAGE_CONTENT_H,
    project_name: str = "",
) -> list[tuple[str, int, int]]:
    """Return one (svg_body, w, h) per packed page with continuous rung numbers."""
    pages = pack_rungs_onto_pages(rungs, width=width, page_content_h=page_content_h)
    out: list[tuple[str, int, int]] = []
    cursor = 1
    for page in pages:
        out.append(
            ladder_program_to_svg(
                page, width=width, start_index=cursor, project_name=project_name
            )
        )
        cursor += len(page)
    return out


def packing_metrics(rungs: list[dict[str, Any]] | None, *, width: int = 1000) -> dict[str, Any]:
    """Test helper: how many pages / average rungs per page with current packing."""
    pages = pack_rungs_onto_pages(rungs, width=width)
    heights = [ladder_program_to_svg(page, width=width)[2] for page in pages]
    return {
        "pages": len(pages),
        "rungs": len(list(rungs or [])),
        "rungs_per_page": [len(p) for p in pages],
        "page_heights": heights,
        "inter_rung_gap": INTER_RUNG_GAP,
        "title_band": TITLE_BAND,
        "bottom_pad": BOTTOM_PAD,
        "branch_row_h": BRANCH_ROW_H,
    }



# ---------------------------------------------------------------------------
# v0.3.15 N-4: print appendix pagination by *visual* rows, not source lines.
# A 45-source-line chunk with long wrapping lines used to overflow onto a
# second physical page that had no UL / NFPA footer. We now hard-wrap each
# line at a column budget that fits a letter page in 9pt monospace and
# chunk by the resulting visual rows, so every chunk fits one sheet and the
# footer (emitted once per chunk) lands on every physical page.
# ---------------------------------------------------------------------------

PRINT_PLC_COLS = 92          # 7.5in printable / ~5.4pt per 9pt mono char ≈ 100; keep margin
PRINT_PLC_ROWS = 44          # ~58 rows fit under heading + footer; keep margin
PRINT_PLC_CONT_INDENT = "      "
PRINT_XREF_ROWS = 26         # weighted rows per cross-reference sheet
PRINT_XREF_CELL_CHARS = 38   # chars per visual line inside one xref cell


def wrap_print_line(line: str, cols: int = PRINT_PLC_COLS, indent: str = PRINT_PLC_CONT_INDENT) -> list[str]:
    """Hard-wrap one raw (unescaped) line into rows of at most ``cols`` chars."""
    line = str(line).rstrip("\r").expandtabs(4)
    if len(line) <= cols:
        return [line]

    def cut(text: str, width: int) -> int:
        # v0.3.16 (P3): break after the last space / separator so a tag is never split
        # mid-word; hard-break only when one token is longer than the whole row.
        if len(text) <= width:
            return len(text)
        for i in range(width, max(1, width // 3), -1):
            if text[i - 1] in " \t,;|)" :
                return i
        return width

    n = cut(line, cols)
    rows = [line[:n]]
    rest = line[n:]
    width = max(8, cols - len(indent))
    while rest:
        n = cut(rest, width)
        rows.append(indent + rest[:n])
        rest = rest[n:]
    return rows


def paginate_plain_text(
    text: str,
    *,
    cols: int = PRINT_PLC_COLS,
    rows_per_page: int = PRINT_PLC_ROWS,
    drop_lines: tuple[str, ...] = (),
) -> list[list[str]]:
    """Split raw text into pages of visual rows (each row ≤ ``cols`` chars).

    ``drop_lines`` removes exact lines (e.g. the UL disclaimer that the page
    footer already carries, so it appears exactly once per printed page).
    A single source line longer than one page is split across pages.
    """
    drop = {d.strip() for d in drop_lines if d and d.strip()}
    visual: list[str] = []
    for raw in str(text or "").splitlines():
        if raw.strip() and raw.strip() in drop:
            continue
        visual.extend(wrap_print_line(raw, cols))
    # trim leading blank rows left by dropped header lines
    while visual and not visual[0].strip():
        visual.pop(0)
    if not visual:
        return [[""]]
    rows_per_page = max(1, int(rows_per_page))
    return [visual[i : i + rows_per_page] for i in range(0, len(visual), rows_per_page)]


def xref_row_weight(tr_html: str, cell_chars: int = PRINT_XREF_CELL_CHARS) -> int:
    """Estimated visual lines one <tr> occupies (long cells wrap)."""
    import re as _re

    cells = _re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", str(tr_html or ""), flags=_re.DOTALL)
    longest = 0
    for c in cells:
        txt = html.unescape(_re.sub(r"<[^>]+>", "", c))
        longest = max(longest, len(txt.strip()))
    return max(1, -(-longest // max(1, cell_chars)))


def chunk_xref_rows(data_trs: list[str], budget: int = PRINT_XREF_ROWS) -> list[list[str]]:
    """Group xref <tr> rows so the weighted visual height fits one sheet."""
    chunks: list[list[str]] = []
    cur: list[str] = []
    used = 0
    for tr in data_trs:
        w = xref_row_weight(tr)
        if cur and used + w > budget:
            chunks.append(cur)
            cur, used = [], 0
        cur.append(tr)
        used += w
    if cur:
        chunks.append(cur)
    return chunks
