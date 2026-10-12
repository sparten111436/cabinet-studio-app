"""Machine graphics for HMI prototyping, drawn from simple shapes (no copied artwork).

``symbol_shapes`` returns a list of drawing operations that the Tk editor and the
SVG drawing sheets both render, so the screen and the print match:
    ("rect", x0, y0, x1, y1, fill, outline, width)
    ("oval", x0, y0, x1, y1, fill, outline, width)
    ("line", [x, y, ...], color, width)
    ("poly", [x, y, ...], fill, outline, width)
    ("text", x, y, text, color, size)
``state`` drives animation: on (bool), phase (int, ticks), level (0..1), value (number), fault (bool).
Prints use the static default state.
"""

from __future__ import annotations

import math

# id -> name, help, size (cols, rows), anim default, words (tag wizard), types (device types), numeric
GRAPHICS: dict[str, dict] = {
    "g_conveyor": {"name": "Conveyor", "size": (10, 3), "anim": "run", "words": ("conv", "belt", "motor"),
                   "types": ("contactor", "motor", "vfd"), "help": "Belt with rollers. The belt moves while its run tag is ON."},
    "g_motor": {"name": "Motor", "size": (3, 3), "anim": "run", "words": ("motor", "m"),
                "types": ("contactor", "motor", "vfd"), "help": "Electric motor. The rotor spins while its run tag is ON."},
    "g_pump": {"name": "Pump", "size": (3, 3), "anim": "run", "words": ("pump", "p"),
               "types": ("contactor", "motor", "vfd"), "help": "Centrifugal pump. The impeller spins while ON."},
    "g_fan": {"name": "Fan", "size": (3, 3), "anim": "run", "words": ("fan", "blower"),
              "types": ("contactor", "motor"), "help": "Fan / blower. The blades turn while ON."},
    "g_tank": {"name": "Tank", "size": (3, 5), "anim": "level", "words": ("level", "tank", "lt"), "numeric": True,
               "types": ("transmitter", "sensor"), "help": "Tank with level. Fills from a 0-100 number, or rises while a fill tag is ON."},
    "g_valve": {"name": "Valve (2-way)", "size": (3, 3), "anim": "open", "words": ("valve", "sol", "yv"),
                "types": ("solenoid", "valve"), "help": "Two-way valve. Shows open while its tag is ON."},
    "g_cylinder": {"name": "Air cylinder", "size": (5, 2), "anim": "extend", "words": ("cyl", "extend", "sol", "clamp"),
                   "types": ("solenoid", "valve"), "help": "Pneumatic cylinder. The rod extends while its tag is ON."},
    "g_robot": {"name": "Robot arm", "size": (4, 4), "anim": "run", "words": ("robot", "arm", "place"),
                "types": ("relay", "io_module"), "help": "Simple robot arm. It swings while its run tag is ON."},
    "g_light_curtain": {"name": "Light curtain", "size": (3, 4), "anim": "fault", "words": ("curtain", "lc", "guard"),
                        "types": ("light_curtain",), "help": "Safety light curtain, status only. Beams turn red when the tag shows abnormal."},
    "g_stack_light": {"name": "Stack light", "size": (2, 4), "anim": "lights", "words": ("stk", "stack", "light"),
                      "types": ("light",), "help": "Stack light. Tag can be green,amber,red tags separated by commas; each tier lights."},
    "g_part": {"name": "Part / box", "size": (10, 1), "anim": "travel", "words": ("conv", "part", "motor"),
               "types": ("contactor", "motor", "vfd"), "help": "A box that travels across while its tag is ON. Stretch it to the conveyor length."},
    "g_pipe": {"name": "Pipe (straight)", "size": (4, 1), "anim": "run", "words": ("pump", "flow", "valve"),
               "types": ("contactor", "solenoid", "valve"), "help": "Straight pipe. Flow marks move while its tag is ON."},
    "g_pipe_elbow": {"name": "Pipe (elbow)", "size": (2, 2), "anim": "run", "words": ("pump", "flow"),
                     "types": ("contactor", "solenoid"), "help": "Pipe elbow (90 degree bend)."},
    "g_pipe_tee": {"name": "Pipe (tee)", "size": (3, 2), "anim": "run", "words": ("pump", "flow"),
                   "types": ("contactor", "solenoid"), "help": "Pipe tee (branch)."},
    "g_photo_eye": {"name": "Photo-eye", "size": (3, 2), "anim": "on", "words": ("pe", "photo", "eye", "sensor"),
                    "types": ("sensor",), "help": "Photo-eye sensor. The beam lights when the sensor is ON."},
    "g_prox": {"name": "Prox sensor", "size": (2, 2), "anim": "on", "words": ("prox", "px", "sensor"),
               "types": ("sensor",), "help": "Inductive proximity sensor. The LED lights when ON."},
    "g_heater": {"name": "Heater", "size": (3, 2), "anim": "on", "words": ("heat", "htr"),
                 "types": ("contactor", "relay"), "help": "Heater element. Highlights while ON."},
    "g_mixer": {"name": "Mixer", "size": (3, 4), "anim": "run", "words": ("mix", "agit"),
                "types": ("contactor", "motor", "vfd"), "help": "Mixing tank. The paddle turns while ON."},
    "g_press": {"name": "Press", "size": (3, 4), "anim": "extend", "words": ("press", "ram", "punch"),
                "types": ("solenoid", "valve", "contactor"), "help": "Press. The ram comes down while its tag is ON."},
    "g_gauge": {"name": "Gauge (dial)", "size": (3, 3), "anim": "needle", "words": ("speed", "press", "temp", "flow"),
                "numeric": True, "types": ("transmitter", "vfd"), "help": "Round dial. The needle follows a 0-100 number."},
    "g_bar": {"name": "Bar graph", "size": (2, 4), "anim": "bar", "words": ("level", "speed", "load"), "numeric": True,
              "types": ("transmitter", "vfd"), "help": "Bar graph. Fills from a 0-100 number."},
    "g_pushbutton": {"name": "Push-button picture", "size": (2, 2), "anim": "on", "words": ("pb", "start", "button"),
                     "types": ("pushbutton",), "help": "Picture of a push button on the door. Lights while its tag is ON (display only)."},
    "g_selector": {"name": "Selector switch picture", "size": (2, 2), "anim": "on", "words": ("ss", "sel", "mode", "hand"),
                   "types": ("selector",), "help": "Picture of a selector switch. The lever turns when its tag is ON (display only)."},
}
ANIMATIONS: dict[str, str] = {
    "none": "No animation",
    "run": "Moves / spins while tag ON",
    "on": "Lights while tag ON",
    "open": "Shows open while tag ON",
    "extend": "Extends while tag ON",
    "level": "Level from 0-100 number",
    "fill": "Fills while tag ON",
    "needle": "Needle follows number",
    "bar": "Bar follows number",
    "travel": "Part travels while tag ON",
    "lights": "Stack tiers light",
    "fault": "Red when tag ON (abnormal)",
}
NUMERIC_ANIMS = {"level", "needle", "bar"}
STATIC_STATE = {"on": False, "phase": 0, "level": 0.5, "value": 50.0, "fault": False, "tiers": (False, False, False)}

_GREEN, _AMBER, _RED = "#2e9d43", "#e0a100", "#d23a2a"


def palette(theme: str) -> dict[str, str]:
    """Base colors per HMI theme. ISA-101: gray; color only for abnormal."""
    if theme.startswith("ISA"):
        return {"body": "#bdbdbd", "dark": "#5a5a5a", "line": "#3a3a3a", "on": "#ffffff", "bg": "#d4d4d4",
                "fluid": "#7f9fbf", "text": "#000000"}
    if theme == "Dark":
        return {"body": "#4a4e58", "dark": "#2a2c33", "line": "#c8ccd4", "on": _GREEN, "bg": "#1f2126",
                "fluid": "#2f6bff", "text": "#ffffff"}
    return {"body": "#b8c2cc", "dark": "#56606b", "line": "#1b1b22", "on": _GREEN, "bg": "#ffffff",
            "fluid": "#2f6bff", "text": "#000000"}


def _rot(cx: float, cy: float, r: float, deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def symbol_shapes(kind: str, x: float, y: float, w: float, h: float, state: dict | None = None,
                  theme: str = "ISA-101 gray (high performance)") -> list[tuple]:
    s = {**STATIC_STATE, **(state or {})}
    p = palette(theme)
    on, phase, fault = bool(s["on"]), int(s["phase"]), bool(s["fault"])
    body = _RED if fault else p["body"]
    ln, lw = p["line"], max(1.0, min(w, h) / 40)
    cx, cy = x + w / 2, y + h / 2
    ops: list[tuple] = []
    spin = (phase * 30) % 360 if on else 0

    def spokes(r: float, n: int = 3) -> None:
        for i in range(n):
            ops.append(("line", [cx, cy, *_rot(cx, cy, r, spin + i * 360 / n)], ln, lw * 1.5))

    if kind == "g_conveyor":
        r = h * 0.28
        top, bot = cy - r, cy + r
        ops += [("rect", x + r, top, x + w - r, bot, body, ln, lw),
                ("oval", x, cy - r, x + 2 * r, cy + r, p["dark"], ln, lw),
                ("oval", x + w - 2 * r, cy - r, x + w, cy + r, p["dark"], ln, lw)]
        step = max(8.0, w / 10)
        off = (phase * step / 4) % step if on else 0
        mx = x + 2 * r + off
        while mx < x + w - 2 * r:
            ops.append(("line", [mx, top + 2, mx, bot - 2], p["on"] if on else ln, lw))
            mx += step
        for rx in (x + w * 0.35, x + w * 0.65):
            ops.append(("oval", rx - r * 0.35, bot + 1, rx + r * 0.35, bot + 1 + r * 0.7, p["dark"], ln, lw))
    elif kind in ("g_motor", "g_fan", "g_pump"):
        r = min(w, h) * 0.38
        if kind == "g_motor":
            ops += [("rect", x + w * 0.08, cy - r, x + w * 0.78, cy + r, body, ln, lw),
                    ("rect", x + w * 0.78, cy - r * 0.15, x + w * 0.95, cy + r * 0.15, p["dark"], ln, lw),
                    ("oval", cx - r * 0.55 - w * 0.07, cy - r * 0.55, cx + r * 0.55 - w * 0.07, cy + r * 0.55,
                     p["on"] if on else p["bg"], ln, lw)]
            cx -= w * 0.07
            spokes(r * 0.5)
        elif kind == "g_pump":
            ops += [("rect", cx, cy - r, x + w * 0.98, cy - r * 0.45, body, ln, lw),
                    ("oval", cx - r, cy - r, cx + r, cy + r, body, ln, lw),
                    ("oval", cx - r * 0.6, cy - r * 0.6, cx + r * 0.6, cy + r * 0.6, p["on"] if on else p["bg"], ln, lw)]
            spokes(r * 0.55, 4)
        else:
            ops.append(("oval", cx - r, cy - r, cx + r, cy + r, p["on"] if on else p["bg"], ln, lw))
            for i in range(3):
                a = spin + i * 120
                ops.append(("poly", [cx, cy, *_rot(cx, cy, r * 0.9, a - 18), *_rot(cx, cy, r * 0.9, a + 18)],
                            body, ln, lw))
    elif kind in ("g_tank", "g_mixer"):
        lvl = max(0.0, min(1.0, float(s["level"])))
        x0, x1, y0, y1 = x + w * 0.12, x + w * 0.88, y + h * 0.08, y + h * 0.95
        ops.append(("rect", x0, y0, x1, y1, p["bg"], ln, lw * 1.5))
        if lvl > 0:
            ops.append(("rect", x0 + lw, y1 - (y1 - y0) * lvl, x1 - lw, y1 - lw, p["fluid"], "", 0))
        if kind == "g_mixer":
            ops.append(("line", [cx, y - 1, cx, y1 - h * 0.18], ln, lw * 1.5))
            dx = (x1 - x0) * 0.35 * math.cos(math.radians(spin))
            ops.append(("line", [cx - dx, y1 - h * 0.18, cx + dx, y1 - h * 0.18], ln, lw * 2.5))
            ops.append(("rect", cx - w * 0.15, y - 1, cx + w * 0.15, y + h * 0.08, body, ln, lw))
        else:
            ops.append(("text", cx, y0 + 10, f"{lvl * 100:.0f}%", p["text"], 9))
    elif kind == "g_valve":
        fill = p["on"] if on else p["bg"]
        ops += [("poly", [x + w * 0.1, cy - h * 0.25, cx, cy, x + w * 0.1, cy + h * 0.25], fill, ln, lw),
                ("poly", [x + w * 0.9, cy - h * 0.25, cx, cy, x + w * 0.9, cy + h * 0.25], fill, ln, lw),
                ("line", [cx, cy, cx, y + h * 0.22], ln, lw),
                ("rect", cx - w * 0.18, y + h * 0.05, cx + w * 0.18, y + h * 0.22, body, ln, lw)]
    elif kind in ("g_cylinder", "g_press"):
        ext = 1.0 if on else 0.0
        if kind == "g_cylinder":
            bx1 = x + w * 0.55
            ops.append(("rect", x + 2, cy - h * 0.3, bx1, cy + h * 0.3, body, ln, lw))
            rod = bx1 + (w * 0.4) * (0.15 + 0.85 * ext)
            ops += [("rect", bx1, cy - h * 0.08, rod, cy + h * 0.08, p["dark"], ln, lw),
                    ("rect", rod, cy - h * 0.2, rod + w * 0.04, cy + h * 0.2, p["on"] if on else p["dark"], ln, lw)]
        else:
            ops += [("rect", x + w * 0.05, y + 2, x + w * 0.95, y + h * 0.15, body, ln, lw),
                    ("rect", x + w * 0.05, y + h * 0.9, x + w * 0.95, y + h - 2, body, ln, lw),
                    ("line", [x + w * 0.1, y + h * 0.15, x + w * 0.1, y + h * 0.9], ln, lw * 2),
                    ("line", [x + w * 0.9, y + h * 0.15, x + w * 0.9, y + h * 0.9], ln, lw * 2)]
            ram = y + h * 0.15 + h * (0.15 + 0.5 * ext)
            ops += [("rect", cx - w * 0.06, y + h * 0.15, cx + w * 0.06, ram, p["dark"], ln, lw),
                    ("rect", x + w * 0.25, ram, x + w * 0.75, ram + h * 0.08, p["on"] if on else p["dark"], ln, lw)]
    elif kind == "g_robot":
        a1 = -60 - (25 * math.sin(phase / 3) if on else 0)
        bx, by = x + w * 0.3, y + h * 0.85
        j1 = _rot(bx, by - h * 0.08, h * 0.45, a1)
        j2 = _rot(*j1, w * 0.45, a1 + 70 + (20 * math.cos(phase / 3) if on else 0))
        ops += [("rect", x + w * 0.1, by, x + w * 0.5, y + h - 2, body, ln, lw),
                ("line", [bx, by - h * 0.08, *j1], p["dark"], lw * 4), ("line", [*j1, *j2], p["dark"], lw * 3),
                ("oval", j1[0] - lw * 3, j1[1] - lw * 3, j1[0] + lw * 3, j1[1] + lw * 3, p["on"] if on else body, ln, lw),
                ("rect", j2[0] - lw * 3, j2[1] - lw * 2, j2[0] + lw * 3, j2[1] + lw * 4, body, ln, lw)]
    elif kind == "g_light_curtain":
        beam = _RED if (on or fault) else (p["line"] if theme.startswith("ISA") else _GREEN)
        ops += [("rect", x + 2, y + 2, x + w * 0.2, y + h - 2, p["dark"], ln, lw),
                ("rect", x + w * 0.8, y + 2, x + w - 2, y + h - 2, p["dark"], ln, lw)]
        for i in range(1, 6):
            yy = y + h * i / 6
            ops.append(("line", [x + w * 0.2, yy, x + w * 0.8, yy], beam, lw))
    elif kind == "g_stack_light":
        tiers = s.get("tiers") or (on, False, False)
        colors = (_GREEN, _AMBER, _RED)
        th = (h * 0.8) / 3
        for i, (lit, col) in enumerate(zip(reversed(tiers), reversed(colors))):
            ty = y + 2 + i * th
            ops.append(("rect", cx - w * 0.3, ty, cx + w * 0.3, ty + th - 2, col if lit else p["body"], ln, lw))
        ops += [("line", [cx, y + h * 0.8, cx, y + h - 4], ln, lw * 2),
                ("rect", cx - w * 0.35, y + h - 5, cx + w * 0.35, y + h - 1, p["dark"], ln, lw)]
    elif kind == "g_part":
        bw = min(h * 0.9, w * 0.25)
        travel = (phase * 0.06 % 1.0) if on else 0.0
        px = x + (w - bw) * travel
        ops.append(("rect", px, y + h - bw, px + bw, y + h - 1, "#c8a165" if not theme.startswith("ISA") else p["dark"],
                    ln, lw))
    elif kind in ("g_pipe", "g_pipe_elbow", "g_pipe_tee"):
        t = min(w, h) * (0.5 if kind == "g_pipe" else 0.3)
        pts = {"g_pipe": [[x, cy, x + w, cy]],
               "g_pipe_elbow": [[x, cy, cx, cy, cx, y + h]],
               "g_pipe_tee": [[x, cy, x + w, cy], [cx, cy, cx, y + h]]}[kind]
        for seg in pts:
            ops.append(("line", seg, ln, t + 2))
            ops.append(("line", seg, p["fluid"] if on else p["body"], t - 1))
        if on:
            off = (phase * 4) % 16
            mx = x + off
            while mx < x + w:
                ops.append(("line", [mx, cy, min(mx + 6, x + w), cy], p["on"], max(1.0, t / 4)))
                mx += 16
    elif kind == "g_photo_eye":
        ops += [("rect", x + 2, cy - h * 0.3, x + w * 0.3, cy + h * 0.3, body, ln, lw),
                ("line", [x + w * 0.3, cy, x + w * 0.95, cy], p["on"] if on else ln, lw * (2 if on else 1)),
                ("rect", x + w * 0.92, cy - h * 0.2, x + w - 1, cy + h * 0.2, p["dark"], ln, lw)]
    elif kind == "g_prox":
        ops += [("rect", x + w * 0.15, y + h * 0.2, x + w * 0.85, y + h * 0.95, body, ln, lw),
                ("oval", cx - w * 0.15, y + 2, cx + w * 0.15, y + h * 0.2, _AMBER if on else p["dark"], ln, lw)]
    elif kind == "g_heater":
        ops.append(("rect", x + 2, y + 2, x + w - 2, y + h - 2, p["bg"], ln, lw))
        zig, n = [], 8
        for i in range(n + 1):
            zig += [x + 6 + (w - 12) * i / n, cy + (h * 0.25 if i % 2 else -h * 0.25)]
        ops.append(("line", zig, _AMBER if on and not theme.startswith("ISA") else (p["on"] if on else ln), lw * 2))
    elif kind in ("g_gauge", "g_bar"):
        val = max(0.0, min(100.0, float(s["value"])))
        if kind == "g_gauge":
            r = min(w, h) * 0.45
            ops.append(("oval", cx - r, cy - r, cx + r, cy + r, p["bg"], ln, lw * 1.5))
            for i in range(11):
                a = 135 + 270 * i / 10
                ops.append(("line", [*_rot(cx, cy, r * 0.8, a), *_rot(cx, cy, r * 0.95, a)], ln, lw))
            ops.append(("line", [cx, cy, *_rot(cx, cy, r * 0.75, 135 + 270 * val / 100)], _RED, lw * 2))
            ops.append(("text", cx, cy + r * 0.6, f"{val:.0f}", p["text"], 9))
        else:
            ops.append(("rect", x + w * 0.2, y + 2, x + w * 0.8, y + h - 2, p["bg"], ln, lw))
            top = y + h - 2 - (h - 4) * val / 100
            if val > 0:
                ops.append(("rect", x + w * 0.2 + lw, top, x + w * 0.8 - lw, y + h - 2 - lw, p["fluid"], "", 0))
    elif kind == "g_pushbutton":
        r = min(w, h) * 0.42
        ops += [("oval", cx - r, cy - r, cx + r, cy + r, p["dark"], ln, lw),
                ("oval", cx - r * 0.7, cy - r * 0.7, cx + r * 0.7, cy + r * 0.7, (_GREEN if on else p["body"]), ln, lw)]
    elif kind == "g_selector":
        r = min(w, h) * 0.42
        ops += [("oval", cx - r, cy - r, cx + r, cy + r, p["body"], ln, lw),
                ("line", [*_rot(cx, cy, r * 0.8, 225 if not on else 315), *_rot(cx, cy, r * 0.8, 45 if not on else 135)],
                 p["dark"], lw * 4)]
    return ops


def svg_from_shapes(ops: list[tuple], fmt) -> str:
    """SVG markup for ``symbol_shapes`` ops. ``fmt`` formats numbers (drawings._num)."""
    from html import escape

    out = []
    for op in ops:
        kind = op[0]
        if kind in ("rect", "oval"):
            _k, x0, y0, x1, y1, fill, outline, width = op
            stroke = f'stroke="{outline}" stroke-width="{fmt(width)}"' if outline else 'stroke="none"'
            if kind == "rect":
                out.append(f'<rect x="{fmt(min(x0, x1))}" y="{fmt(min(y0, y1))}" width="{fmt(abs(x1 - x0))}" '
                           f'height="{fmt(abs(y1 - y0))}" fill="{fill or "none"}" {stroke}/>')
            else:
                out.append(f'<circle cx="{fmt((x0 + x1) / 2)}" cy="{fmt((y0 + y1) / 2)}" '
                           f'r="{fmt(min(abs(x1 - x0), abs(y1 - y0)) / 2)}" fill="{fill or "none"}" {stroke}/>')
        elif kind == "line":
            _k, pts, color, width = op
            text = " ".join(f"{fmt(pts[i])},{fmt(pts[i + 1])}" for i in range(0, len(pts) - 1, 2))
            out.append(f'<polyline points="{text}" fill="none" stroke="{color}" stroke-width="{fmt(width)}"/>')
        elif kind == "poly":
            _k, pts, fill, outline, width = op
            text = " ".join(f"{fmt(pts[i])},{fmt(pts[i + 1])}" for i in range(0, len(pts) - 1, 2))
            out.append(f'<polygon points="{text}" fill="{fill}" stroke="{outline or "none"}" stroke-width="{fmt(width)}"/>')
        elif kind == "text":
            _k, x, y_, text, color, size = op
            out.append(f'<text x="{fmt(x)}" y="{fmt(y_)}" font-family="Segoe UI, Liberation Sans, sans-serif" '
                       f'font-size="{fmt(size)}" fill="{color}" text-anchor="middle">{escape(text)}</text>')
    return "".join(out)


def tk_draw_shapes(canvas, ops: list[tuple], tag: str = "") -> list[int]:
    """Draw ``symbol_shapes`` ops on a Tk canvas; returns the item ids."""
    ids = []
    tags = (tag,) if tag else ()
    for op in ops:
        kind = op[0]
        if kind == "rect":
            _k, x0, y0, x1, y1, fill, outline, width = op
            ids.append(canvas.create_rectangle(x0, y0, x1, y1, fill=fill, outline=outline, width=width, tags=tags))
        elif kind == "oval":
            _k, x0, y0, x1, y1, fill, outline, width = op
            ids.append(canvas.create_oval(x0, y0, x1, y1, fill=fill, outline=outline, width=width, tags=tags))
        elif kind == "line":
            _k, pts, color, width = op
            if len(pts) >= 4:
                ids.append(canvas.create_line(*pts, fill=color, width=width, tags=tags))
        elif kind == "poly":
            _k, pts, fill, outline, width = op
            ids.append(canvas.create_polygon(*pts, fill=fill, outline=outline, width=width, tags=tags))
        elif kind == "text":
            _k, x, y, text, color, size = op
            ids.append(canvas.create_text(x, y, text=text, fill=color, font=("Segoe UI", int(size)), tags=tags))
    return ids
