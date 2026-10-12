"""I/O enumeration: give every 'dumb' field device a PLC point in the selected PLC's own format.

Inputs: pushbuttons, selectors, sensors, light-curtain OSSD feedback, E-stop monitoring contacts,
safety-relay monitoring, overload and aux contacts. Outputs: pilot / stack lights, contactor and
relay coils, solenoids, valves, hard-wired VFD run / direction. Transmitters and sensors with a
4-20 mA / 0-10 V signal take an analog input.

Addresses follow the maker and family of the PLC item (catalog number) and the I/O modules whose
``parent_tag`` is that PLC. Points spill to the next module of the same kind; anything left over is
reported as a shortage ("need 1 more 16-pt DI module"). Re-running keeps every address that is still
valid, so wiring that was already built does not move.

Safety inputs are monitored only. The software is never the safety function (NFPA 79 / ISO 13849):
E-stop and guarding stay hard-wired or on rated safety relays.
"""

from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from cabinet_studio.models.project import PlacedItem, Project

SAFETY_NOTE = ("E-stop and safety functions must be hardwired or use rated safety relays "
               "(NFPA 79 / ISO 13849). The software is never the safety function.")
KINDS = ("DI", "DO", "AI", "AO")
KIND_WORD = {"DI": "input", "DO": "output", "AI": "analog input", "AO": "analog output"}
MODULE_SIZE = {"DI": 16, "DO": 16, "AI": 4, "AO": 4}
CSV_COLUMNS = ("Tag", "Device", "Type", "Kind", "Address", "Module", "Terminal", "Wire #", "Description")

INPUT_TYPES = {"pushbutton", "estop", "light_curtain", "motor_protector", "sensor", "safety_relay", "selector"}
OUTPUT_TYPES = {"light", "contactor", "relay", "solenoid", "valve"}
NEVER_TYPES = {"motor", "plc", "hmi", "io_module", "enclosure", "backplate", "ethernet_switch", "transformer",
               "terminal_block", "fuse_holder"}
ANALOG_SIGNALS = ("4-20", "0-10", "hart", "analog")
SKIP_WIRE_TOKENS = {"PE", "0V", "24V", "+24V", "L1", "L2", "L3", "N", "GND", "COM", "+24"}


@dataclass
class PlcProfile:
    maker: str  # Allen-Bradley / Siemens / Omron / Generic
    family: str  # logix, micro800, s7-1200, s7-1500, s7-300, omron-cp, omron-cj, omron-nx
    label: str
    embedded: dict[str, int] = field(default_factory=dict)
    catalog: str = ""
    tag: str = ""


@dataclass
class Channel:
    kind: str
    address: str
    module: str
    slot: int
    index: int


@dataclass
class IoPoint:
    item_id: str
    tag: str
    device: str
    type_id: str
    kind: str
    suffix: str = ""
    description: str = ""


@dataclass
class IoRow:
    tag: str
    device: str
    type_id: str
    kind: str
    address: str
    module: str
    terminal: str
    wire: str
    description: str
    kept: bool = False

    def as_list(self) -> list[str]:
        return [self.tag, self.device, self.type_id, self.kind, self.address, self.module, self.terminal,
                self.wire, self.description]


@dataclass
class IoReport:
    profile: PlcProfile | None
    rows: list[IoRow] = field(default_factory=list)
    shortages: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.profile is not None and not self.shortages


# ----------------------------------------------------------------------------- PLC profile

def plc_items(project: Project) -> list[PlacedItem]:
    return [item for item in project.items if item.type_id == "plc"]


def selected_plc(project: Project, plc_id: str | None = None) -> PlacedItem | None:
    plcs = plc_items(project)
    if plc_id:
        for item in plcs:
            if item.id == plc_id or (item.fields.get("tag") or "").strip() == plc_id:
                return item
    return plcs[0] if plcs else None


def _pts(catalog: str, pattern: str) -> int:
    m = re.search(pattern, catalog)
    return int(m.group(1)) if m else 0


def detect_profile(plc: PlacedItem) -> PlcProfile:
    """Maker + family + embedded I/O from the PLC item's vendor and catalog number."""
    vendor = (plc.fields.get("vendor") or "").strip().lower()
    cat = (plc.fields.get("catalog") or "").strip().upper()
    tag = (plc.fields.get("tag") or "PLC").strip()
    if cat.startswith("2080"):
        n = _pts(cat, r"-L[CE]?\d{2}-(\d{2})")
        di, do = {10: (6, 4), 16: (10, 6), 20: (12, 8), 24: (14, 10), 48: (28, 20)}.get(n, (14, 10))
        return PlcProfile("Allen-Bradley", "micro800", "Micro800 (CCW)", {"DI": di, "DO": do}, cat, tag)
    if cat.startswith("1756"):
        return PlcProfile("Allen-Bradley", "logix", "ControlLogix (Studio 5000)", {}, cat, tag)
    if cat.startswith(("1769", "5069", "5380", "5480")) or (vendor.startswith("allen") and not cat):
        return PlcProfile("Allen-Bradley", "logix", "CompactLogix (Studio 5000)", {}, cat, tag)
    if cat.startswith("6ES7") or vendor == "siemens":
        code = cat[4:7] if cat.startswith("6ES7") else ""
        if code.startswith("21") or (not code and vendor == "siemens"):
            emb = {"211": (6, 4, 2, 0), "212": (8, 6, 2, 0), "214": (14, 10, 2, 0),
                   "215": (14, 10, 2, 2), "217": (14, 10, 2, 2)}.get(code, (14, 10, 2, 0))
            return PlcProfile("Siemens", "s7-1200", "S7-1200 (TIA Portal)",
                              dict(zip(KINDS, emb)), cat, tag)
        if code.startswith("31"):
            return PlcProfile("Siemens", "s7-300", "S7-300 (TIA Portal / STEP 7)", {}, cat, tag)
        return PlcProfile("Siemens", "s7-1500", "S7-1500 (TIA Portal)", {}, cat, tag)
    if cat.startswith(("NX1P", "NX102", "NX502", "NX701", "NJ")) or (vendor == "omron" and cat.startswith("N")):
        n = _pts(cat, r"NX1P2-\d{2}(\d{2})")
        emb = {"DI": 14, "DO": 10} if n == 24 else ({"DI": 24, "DO": 16} if n == 40 else {})
        return PlcProfile("Omron", "omron-nx", "NX/NJ (Sysmac Studio)", emb, cat, tag)
    if cat.startswith(("CP1", "CP2")):
        n = _pts(cat, r"-[A-Z]?(\d{2})")
        di, do = {14: (8, 6), 20: (12, 8), 30: (18, 12), 40: (24, 16), 60: (36, 24)}.get(n, (18, 12))
        return PlcProfile("Omron", "omron-cp", "CP1/CP2 (CX-Programmer)", {"DI": di, "DO": do}, cat, tag)
    if cat.startswith(("CJ", "CS")) or vendor == "omron":
        return PlcProfile("Omron", "omron-cj", "CJ/CS (CX-Programmer)", {}, cat, tag)
    return PlcProfile("Allen-Bradley", "logix", "Generic (Logix-style addresses)", {}, cat, tag)


# ----------------------------------------------------------------------------- modules

@dataclass
class _Module:
    slot: int
    label: str
    counts: dict[str, int]


def _module_kind(item: PlacedItem) -> str:
    kind = (item.fields.get("io_kind") or "").strip().upper()
    if kind in KINDS or kind == "MIXED":
        return kind
    cat = (item.fields.get("catalog") or "").upper()
    for pat, k in ((r"6ES7221|-IB|-IV|-IQ|NX-ID|ID2|ID5", "DI"), (r"6ES7222|-OB|-OW|-OV|NX-OD|NX-OC|OD2|OC2", "DO"),
                   (r"6ES7223|-IQ16|MD2", "MIXED"), (r"6ES7231|-IF|NX-AD|AD0", "AI"),
                   (r"6ES7232|-OF|NX-DA|DA0", "AO")):
        if re.search(pat, cat):
            return k
    return "DI"


def _module_counts(item: PlacedItem) -> dict[str, int]:
    kind = _module_kind(item)
    raw = (item.fields.get("point_count") or "").upper()
    pairs = re.findall(r"(\d+)\s*(DI|DO|AI|AO)", raw)
    if pairs:
        return {k: int(n) for n, k in pairs}
    m = re.search(r"\d+", raw)
    if kind == "MIXED":
        total = int(m.group(0)) if m else 32
        return {"DI": total // 2, "DO": total - total // 2}
    return {kind: int(m.group(0)) if m else MODULE_SIZE[kind]}


def _modules(project: Project, plc: PlacedItem, profile: PlcProfile) -> list[_Module]:
    tag = (plc.fields.get("tag") or "").strip()
    single = len(plc_items(project)) <= 1
    mods: list[_Module] = []
    if any(profile.embedded.values()):
        mods.append(_Module(0, f"{tag or 'PLC'} embedded I/O", {k: v for k, v in profile.embedded.items() if v}))
    first = 2 if profile.family == "s7-1200" else (4 if profile.family == "s7-300" else 1)
    loose: list[tuple[int, PlacedItem]] = []
    for order, item in enumerate(project.items):
        if item.type_id != "io_module":
            continue
        parent = (item.fields.get("parent_tag") or "").strip()
        if parent and parent != tag:
            continue
        if not parent and not single:
            continue
        loose.append((order, item))
    used: set[int] = set()
    pending: list[PlacedItem] = []
    for _order, item in loose:
        m = re.search(r"\d+", item.fields.get("slot") or "")
        if m and int(m.group(0)) not in used and int(m.group(0)) >= 1:
            slot = int(m.group(0))
            used.add(slot)
            mods.append(_Module(slot, _module_label(item, slot), _module_counts(item)))
        else:
            pending.append(item)
    nxt = first
    for item in pending:
        while nxt in used:
            nxt += 1
        used.add(nxt)
        mods.append(_Module(nxt, _module_label(item, nxt), _module_counts(item)))
    mods.sort(key=lambda m: m.slot)
    return mods


def _module_label(item: PlacedItem, slot: int) -> str:
    bits = [f"Slot {slot}"]
    for key in ("tag", "catalog"):
        val = (item.fields.get(key) or "").strip()
        if val and val not in bits:
            bits.append(val)
    return " ".join(bits)


# ----------------------------------------------------------------------------- address formats

def _bit_addr(prefix: str, n: int, byte0: int = 0) -> str:
    return f"%{prefix}{byte0 + n // 8}.{n % 8}"


def build_channels(profile: PlcProfile, modules: list[_Module]) -> list[Channel]:
    """Every point on every module in the PLC's native address format, in slot order."""
    out: list[Channel] = []
    fam = profile.family
    seq = {"I": 0, "Q": 0}  # S7-1500 sequential byte pointers
    word = {"in": 0, "out": 0, "cj": 0, "cp_in": 0, "cp_out": 100}
    for mod in modules:
        s = mod.slot
        for kind in KINDS:
            n_pts = mod.counts.get(kind, 0)
            if not n_pts:
                continue
            io = "I" if kind in ("DI", "AI") else "O"
            q = "I" if io == "I" else "Q"
            for n in range(n_pts):
                if fam == "logix":
                    addr = (f"Local:{s}:{io}.Data.{n}" if kind in ("DI", "DO") else f"Local:{s}:{io}.Ch{n}Data")
                elif fam == "micro800":
                    where = "EM" if s == 0 else f"X{s}"
                    addr = f"_IO_{where}_{kind}_{n:02d}"
                elif fam == "s7-1200":
                    if kind in ("DI", "DO"):
                        addr = _bit_addr(q, n, 0 if s == 0 else 8 + 4 * (s - 2))
                    else:
                        addr = f"%{q}W{(64 if s == 0 else 96 + 16 * (s - 2)) + 2 * n}"
                elif fam == "s7-300":
                    if kind in ("DI", "DO"):
                        addr = _bit_addr(q, n, 4 * (s - 4))
                    else:
                        addr = f"%{q}W{256 + 16 * (s - 4) + 2 * n}"
                elif fam == "s7-1500":
                    if kind in ("DI", "DO"):
                        addr = _bit_addr(q, n, seq[q])
                    else:
                        addr = f"%{q}W{seq[q] + 2 * n}"
                elif fam == "omron-cp":
                    if s == 0 and kind == "DI":
                        addr = f"{n // 12}.{n % 12:02d}"
                    elif s == 0 and kind == "DO":
                        addr = f"{100 + n // 8}.{n % 8:02d}"
                    elif kind in ("DI", "DO"):
                        base = word["cp_in"] if io == "I" else word["cp_out"]
                        addr = f"{base + n // 16}.{n % 16:02d}"
                    else:
                        base = word["cp_in"] if io == "I" else word["cp_out"]
                        addr = f"CIO {base + n}"
                elif fam == "omron-cj":
                    if kind in ("DI", "DO"):
                        addr = f"{word['cj'] + n // 16}.{n % 16:02d}"
                    else:
                        addr = f"CIO {2000 + 10 * s + (1 if io == 'I' else 5) + n}"
                else:  # omron-nx: variables mapped to I/O ports in Sysmac I/O Map
                    unit = "BuiltIn" if s == 0 else f"N{s}"
                    if kind in ("DI", "DO"):
                        addr = f"{unit}_{'Input' if io == 'I' else 'Output'}_Bit_{n:02d}"
                    else:
                        addr = f"{unit}_Ch{n + 1}_Analog_{'Input' if io == 'I' else 'Output'}_Value"
                out.append(Channel(kind, addr, mod.label, s, n))
            # advance sequential pointers after the module's kind block
            if fam == "s7-1500":
                seq[q] += math.ceil(n_pts / 8) if kind in ("DI", "DO") else 2 * n_pts
            elif fam == "omron-cj" and kind in ("DI", "DO"):
                word["cj"] += math.ceil(n_pts / 16)
            elif fam == "omron-cp":
                key = "cp_in" if io == "I" else "cp_out"
                if s == 0:
                    word[key] = (math.ceil(n_pts / 12) if io == "I" else 100 + math.ceil(n_pts / 8))
                else:
                    word[key] += math.ceil(n_pts / 16) if kind in ("DI", "DO") else n_pts
    return out


# ----------------------------------------------------------------------------- demand

def _hay(item: PlacedItem) -> str:
    f = item.fields
    return " ".join((f.get("tag", ""), f.get("description", ""), f.get("function", ""))).lower()


def device_points(item: PlacedItem) -> list[IoPoint]:
    """The PLC points one cabinet device needs (empty for power / network / structural parts)."""
    tag = (item.fields.get("tag") or "").strip()
    if not tag:
        return []
    t = item.type_id
    direction = (item.fields.get("io_direction") or "").strip().lower()
    desc = (item.fields.get("description") or item.fields.get("function") or "").strip()
    signal = (item.fields.get("signal") or "").lower()
    dev = t.replace("_", " ").title()
    if direction.startswith("network"):
        return []
    if t == "vfd":
        if not direction:
            return []
        return [IoPoint(item.id, f"{tag}_RUN", dev, t, "DO", "RUN", f"{desc or tag} run command".strip()),
                IoPoint(item.id, f"{tag}_DIR", dev, t, "DO", "DIR", f"{desc or tag} direction (reverse)".strip())]
    analog = any(s in signal for s in ANALOG_SIGNALS)
    if t == "transmitter" or (t == "sensor" and analog):
        return [IoPoint(item.id, tag, dev, t, "AI", "", desc)]
    if t in ("contactor", "relay") and (direction.startswith("input and") or " aux" in f" {_hay(item)}"):
        return [IoPoint(item.id, tag, dev, t, "DO", "", desc),
                IoPoint(item.id, f"{tag}_AUX", dev, t, "DI", "AUX", f"{desc or tag} aux contact".strip())]
    if t == "safety_relay":
        return [IoPoint(item.id, tag, dev, t, "DI", "", desc or "Safety relay monitoring contact")]
    if t in NEVER_TYPES:
        return []
    if direction == "input" or (direction != "output" and t in INPUT_TYPES):
        return [IoPoint(item.id, tag, dev, t, "DI", "", desc)]
    if direction == "output" or t in OUTPUT_TYPES:
        return [IoPoint(item.id, tag, dev, t, "DO", "", desc)]
    return []


# ----------------------------------------------------------------------------- wire # / terminal

def _wire_list(item: PlacedItem) -> list[str]:
    from cabinet_studio.services.drawings import wire_tokens

    return [w for w in wire_tokens(item.fields.get("wire_numbers") or "") if w not in SKIP_WIRE_TOKENS]


def _max_w(project: Project) -> int:
    best = 0
    for item in project.items:
        raw = " ".join((item.fields.get("wire_numbers") or "", item.fields.get("io_wire") or ""))
        for m in re.finditer(r"\bW(\d+)\b", raw.upper()):
            best = max(best, int(m.group(1)))
    return best


def _strip_tag(project: Project) -> str:
    for item in project.items:
        if item.type_id == "terminal_block" and (item.fields.get("tag") or "").strip():
            return item.fields["tag"].strip()
    return "TB-IO"


def _max_terminal(project: Project, strip: str) -> int:
    best = 0
    pat = re.compile(rf"\b{re.escape(strip.upper())}-(\d+)\b")
    for item in project.items:
        raw = " ".join((item.fields.get("terminal_landings") or "", item.fields.get("io_terminal") or "")).upper()
        for m in pat.finditer(raw):
            best = max(best, int(m.group(1)))
    return best


def _split_multi(raw: str) -> list[str]:
    return [p.strip() for p in re.split(r"[;,]", raw or "") if p.strip()]


def _existing(item: PlacedItem, point: IoPoint) -> str:
    if not point.suffix:
        return (item.fields.get("io_address") or "").strip()
    for part in _split_multi(item.fields.get("io_points") or ""):
        key, _, val = part.partition("=")
        if key.strip() == point.tag:
            return val.strip()
    return ""


def _existing_multi(item: PlacedItem, field_key: str, index: int) -> str:
    vals = _split_multi(item.fields.get(field_key) or "")
    return vals[index] if index < len(vals) else ""


# ----------------------------------------------------------------------------- main entry

def assign_io(project: Project, plc_id: str | None = None, *, write: bool = True) -> IoReport:
    """Assign (or confirm) every device point. Deterministic; keeps still-valid addresses."""
    plc = selected_plc(project, plc_id)
    if plc is None:
        return IoReport(None, notes=["Add a PLC to the cabinet first. I/O addresses follow the PLC maker and family."])
    profile = detect_profile(plc)
    channels = build_channels(profile, _modules(project, plc, profile))
    free: dict[str, Channel] = {ch.address: ch for ch in channels}
    tag = (plc.fields.get("tag") or "").strip()
    single = len(plc_items(project)) <= 1
    demand: list[tuple[PlacedItem, IoPoint]] = []
    for item in project.items:
        parent = (item.fields.get("parent_tag") or "").strip()
        if not single and parent and parent != tag:
            continue
        for point in device_points(item):
            demand.append((item, point))
    placed: dict[int, Channel] = {}
    kept: set[int] = set()
    for i, (item, point) in enumerate(demand):
        old = _existing(item, point)
        ch = free.get(old)
        if ch is not None and ch.kind == point.kind:
            placed[i] = free.pop(old)
            kept.add(i)
    pools: dict[str, list[Channel]] = {k: [c for c in channels if c.kind == k and c.address in free] for k in KINDS}
    short: dict[str, int] = {k: 0 for k in KINDS}
    for i, (_item, point) in enumerate(demand):
        if i in placed:
            continue
        pool = pools[point.kind]
        if pool:
            ch = pool.pop(0)
            free.pop(ch.address, None)
            placed[i] = ch
        else:
            short[point.kind] += 1
    report = IoReport(profile)
    next_w = _max_w(project)
    strip = _strip_tag(project)
    next_t = _max_terminal(project, strip)
    per_item: dict[str, list[int]] = {}
    for i, (item, _p) in enumerate(demand):
        per_item.setdefault(item.id, []).append(i)
    for item_id, idxs in per_item.items():
        item = project.find(item_id)
        wires = _wire_list(item)
        multi_addr: list[str] = []
        io_wires: list[str] = []
        io_terms: list[str] = []
        for pos, i in enumerate(idxs):
            point = demand[i][1]
            ch = placed.get(i)
            wire = _existing_multi(item, "io_wire", pos) or (wires[pos] if pos < len(wires) else "")
            if not wire:
                next_w += 1
                wire = f"W{next_w}"
            term = _existing_multi(item, "io_terminal", pos)
            if not term:
                m = re.search(r"\b(X?TB[\w]*-\d+)\b", (item.fields.get("terminal_landings") or "").upper())
                if m and pos == 0:
                    term = m.group(1)
                else:
                    next_t += 1
                    term = f"{strip}-{next_t}"
            io_wires.append(wire)
            io_terms.append(term)
            address = ch.address if ch else ""
            if ch and i not in kept:
                report.changed.append(f"{point.tag}: {_existing(item, point) or '(none)'} -> {address}")
            report.rows.append(IoRow(point.tag, point.device, point.type_id, point.kind,
                                     address or "UNASSIGNED", ch.module if ch else "(no free point)", term, wire,
                                     point.description, i in kept))
            if point.suffix and address:
                multi_addr.append(f"{point.tag}={address}")
            if write and ch and pos == 0 and not point.suffix:
                item.fields["io_address"] = address
                if not (item.fields.get("io_direction") or "").strip():
                    item.fields["io_direction"] = "Input" if point.kind in ("DI", "AI") else "Output"
        if write:
            first = demand[idxs[0]][1]
            if multi_addr:
                item.fields["io_points"] = "; ".join(multi_addr)
                if first.suffix:
                    item.fields["io_address"] = multi_addr[0].split("=", 1)[1]
            if any(placed.get(i) for i in idxs):
                item.fields["io_wire"] = ", ".join(io_wires)
                item.fields["io_terminal"] = ", ".join(io_terms)
                item.fields["io_module"] = ", ".join(dict.fromkeys(placed[i].module for i in idxs if i in placed))
    for kind in KINDS:
        n = short[kind]
        if n:
            mods = math.ceil(n / MODULE_SIZE[kind])
            unit = "pt" if kind in ("DI", "DO") else "ch"
            report.shortages.append(
                f"Need {mods} more {MODULE_SIZE[kind]}-{unit} {kind} module{'s' if mods > 1 else ''} "
                f"({n} {KIND_WORD[kind]} point{'s' if n > 1 else ''} without an address).")
    if profile.family == "omron-nx":
        report.notes.append("NX/NJ: create each tag as a global variable, then map it to the port shown in the "
                            "Address column in Sysmac Studio's I/O Map.")
    if profile.family in ("s7-1200", "s7-1500", "s7-300", "omron-cj", "omron-cp"):
        report.notes.append("Addresses are the software's default start addresses. Confirm them in the device "
                            "configuration of the maker software before wiring.")
    report.notes.append(SAFETY_NOTE)
    return report


def tag_addresses(project: Project, plc_id: str | None = None) -> dict[str, str]:
    """Device / point tag -> address, plus ladder aliases that resolve to one of them."""
    out: dict[str, str] = {}
    for row in assign_io(project, plc_id, write=False).rows:
        if row.address and row.address != "UNASSIGNED":
            out[row.tag] = row.address
    aliases = (project.program or {}).get("tag_aliases") or {}
    if isinstance(aliases, dict):
        for alias, base in aliases.items():
            seen = {alias}
            while base in aliases and base not in seen:
                seen.add(base)
                base = aliases[base]
            if base in out:
                out[str(alias)] = out[base]
    return out


def write_io_csv(report: IoReport, path: Path | str) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_COLUMNS)
        for row in report.rows:
            writer.writerow(row.as_list())
    return target


def summary_text(report: IoReport) -> str:
    if report.profile is None:
        return "\n".join(report.notes)
    p = report.profile
    lines = [f"PLC {p.tag}: {p.maker} {p.label}" + (f" ({p.catalog})" if p.catalog else ""),
             f"{len(report.rows)} I/O point(s); {sum(1 for r in report.rows if r.kept)} kept from before."]
    lines += report.shortages or ["Every point has an address."]
    if report.changed:
        lines.append("New or moved: " + "; ".join(report.changed[:12]) + (" ..." if len(report.changed) > 12 else ""))
    lines += report.notes
    return "\n".join(lines)
