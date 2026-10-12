"""I/O LIST drawing sheets (appended after the Wire Schedule by drawings.build_sheets).

One row per PLC point from services.io_assign: tag, device, type, address, module, terminal, wire #.
The title block (drawings._title_markup) adds the disclaimer once per sheet.
"""

from __future__ import annotations

from html import escape

from cabinet_studio.services.drawings import (
    PAGE_W,
    TITLE_TOP,
    WIRE_SCHEDULE_ROW_PITCH,
    WIRE_SCHEDULE_ROWS,
    WIRE_SCHEDULE_TOP,
    Sheet,
    _clip,
    _num,
)
from cabinet_studio.services.io_assign import SAFETY_NOTE, IoReport, assign_io

IO_LIST_KIND = "io-list"
FONT = "Segoe UI, Liberation Sans, sans-serif"
MONO = "Consolas, Liberation Mono, monospace"
COLUMNS = [
    ("Tag", 36.0, 190.0),
    ("Device", 226.0, 150.0),
    ("Type", 376.0, 60.0),
    ("Address", 436.0, 290.0),
    ("Module", 726.0, 300.0),
    ("Terminal", 1026.0, 120.0),
    ("Wire #", 1146.0, 90.0),
    ("Description", 1236.0, 430.0),
]


def _report(project) -> IoReport:
    return assign_io(project, write=False)


def io_list_sheets(project) -> list[Sheet]:
    report = _report(project)
    if report.profile is None or not report.rows:
        return []
    pages = max(1, -(-len(report.rows) // WIRE_SCHEDULE_ROWS))
    out: list[Sheet] = []
    for page in range(1, pages + 1):
        title = "I/O LIST" + (f"  ·  {page}/{pages}" if pages > 1 else "")
        sheet = Sheet(kind=IO_LIST_KIND, title=title, notes=[*report.shortages, SAFETY_NOTE])
        sheet.schedule_page = page
        sheet.schedule_pages = pages
        out.append(sheet)
    return out


def io_list_markup(sheet: Sheet, project) -> str:
    report = _report(project)
    page = sheet.schedule_page or 1
    pages = sheet.schedule_pages or 1
    rows = report.rows[(page - 1) * WIRE_SCHEDULE_ROWS: page * WIRE_SCHEDULE_ROWS]
    p = report.profile
    top = WIRE_SCHEDULE_TOP
    pitch = WIRE_SCHEDULE_ROW_PITCH
    header = f"I/O LIST — {(project.name or 'Cabinet').strip() or 'Cabinet'}" + (f"    {page}/{pages}" if pages > 1 else "")
    plc = f"PLC {p.tag}: {p.maker} {p.label} {p.catalog}".strip() if p else ""
    parts = [
        f'<g class="io-list" data-page="{page}" data-pages="{pages}">',
        f'<text x="36" y="{_num(top)}" font-family="{FONT}" font-size="18" font-weight="700" fill="#000000">'
        f"{escape(header)}</text>",
        f'<text x="36" y="{_num(top + 22)}" font-family="{FONT}" font-size="11" fill="#333333">'
        f"{escape(_clip(plc, 200))}</text>",
    ]
    header_y = top + 48.0
    row0 = header_y + pitch
    table_bottom = TITLE_TOP - 12.0
    parts.append(f'<rect x="28" y="{_num(header_y - 16)}" width="{_num(PAGE_W - 56)}" height="{_num(pitch)}" '
                 f'fill="#f0f0f0" stroke="#000000" stroke-width="0.8"/>')
    for label, x, _w in COLUMNS:
        parts.append(f'<text class="io-list-colhead" x="{_num(x)}" y="{_num(header_y)}" font-family="{FONT}" '
                     f'font-size="12" font-weight="700" fill="#000000">{escape(label)}</text>')
    frame_h = min(table_bottom, row0 + WIRE_SCHEDULE_ROWS * pitch) - (header_y - 16)
    parts.append(f'<rect x="28" y="{_num(header_y - 16)}" width="{_num(PAGE_W - 56)}" height="{_num(frame_h)}" '
                 f'fill="none" stroke="#000000" stroke-width="1.1"/>')
    for index, row in enumerate(rows):
        y = row0 + index * pitch
        if y > table_bottom:
            break
        parts.append(f'<line x1="28" y1="{_num(y + 6)}" x2="{_num(PAGE_W - 28)}" y2="{_num(y + 6)}" '
                     f'stroke="#cccccc" stroke-width="0.6"/>')
        values = [row.tag, row.device, row.kind, row.address, row.module, row.terminal, row.wire, row.description]
        for (label, x, width), value in zip(COLUMNS, values):
            mono = label in {"Address", "Terminal", "Wire #", "Type"}
            parts.append(
                f'<text class="io-list-cell" data-col="{escape(label)}" x="{_num(x)}" y="{_num(y)}" '
                f'font-family="{MONO if mono else FONT}" font-size="11" fill="#000000">'
                f"{escape(_clip(str(value or ''), max(6, int(width / 7))))}</text>")
    parts.append("</g>")
    return "".join(parts)
