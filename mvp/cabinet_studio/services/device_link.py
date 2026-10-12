"""Live Ethernet link to a running PLC for testing: connect, read info, upload the tag list, watch and
(carefully) write non-safety, non-physical tags.

Drivers sit behind one small interface:
* Allen-Bradley Logix / Micro800: pycomm3 (LogixDriver), imported only when used.
* Siemens S7-1200/1500/300: python-snap7 (PUT/GET must be allowed on the CPU), imported only when used.
* Omron CJ/CP/NX/NJ: minimal FINS over UDP (port 9600) reading / writing DM, WR, HR words and bits. BETA.
* Simulated PLC: no network, for practice and tests.

Program download / upload over the wire is NOT done here. Use the files from services.plc_export and
the maker's software. Writes are refused for safety tags, physical I/O and without an explicit
"I am at the machine and it is safe" confirmation. The software is never the safety function
(NFPA 79 / ISO 13849).
"""

from __future__ import annotations

import re
import socket
import struct
from dataclasses import dataclass, field
from typing import Any

from cabinet_studio.services.sim_plant import is_safety_tag

DEFAULT_TIMEOUT = 4.0
DRIVER_CHOICES = ("Allen-Bradley Logix (CompactLogix / ControlLogix)", "Allen-Bradley Micro800",
                  "Siemens S7-1200 / S7-1500", "Siemens S7-300 / S7-400", "Omron FINS (BETA)",
                  "Simulated PLC (no network)")
FAMILY_TO_CHOICE = {"logix": 0, "micro800": 1, "s7-1200": 2, "s7-1500": 2, "s7-300": 3, "omron-cp": 4,
                    "omron-cj": 4, "omron-nx": 4}
PHYSICAL_ADDRESS = re.compile(r"^(Local:|_IO_|%?[IQE]\d|%?[IQ][BWD]\d|%?(PI|PQ)|CIO\b|\d+\.\d{2}$)", re.I)


class DeviceError(Exception):
    """A plain-words problem talking to the device."""


@dataclass
class TagInfo:
    name: str
    data_type: str = ""


@dataclass
class TagCompare:
    missing: list[str] = field(default_factory=list)  # in the project, not in the PLC
    extra: list[str] = field(default_factory=list)  # in the PLC, not in the project
    mismatch: list[tuple[str, str, str]] = field(default_factory=list)  # (tag, project type, PLC type)
    note: str = ""

    def text(self) -> str:
        lines = [self.note] if self.note else []
        lines.append(f"Missing in PLC ({len(self.missing)}): " + (", ".join(self.missing[:40]) or "none"))
        lines.append(f"Only in PLC ({len(self.extra)}): " + (", ".join(self.extra[:40]) or "none")
                     + (" ..." if len(self.extra) > 40 else ""))
        lines.append(f"Type mismatch ({len(self.mismatch)}): "
                     + (", ".join(f"{t} (project {a}, PLC {b})" for t, a, b in self.mismatch[:20]) or "none"))
        return "\n".join(lines)


def plain_error(exc: BaseException, ip: str = "") -> str:
    where = f" at {ip}" if ip else ""
    if isinstance(exc, DeviceError):
        return str(exc)
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return (f"No answer from the PLC{where} in time. Check the Ethernet cable, the IP address, that the PLC "
                "is powered, and that this PC is on the same network.")
    if isinstance(exc, ConnectionRefusedError):
        return f"The device{where} refused the connection. Is it really this make of PLC, and is the port open?"
    if isinstance(exc, OSError):
        return f"Network problem{where}: {exc.strerror or exc}. Check the cable and IP address."
    return f"The PLC{where} reported a problem: {exc}"


def _category(dtype: str) -> str:
    t = (dtype or "").upper()
    if t in ("BOOL", "BIT"):
        return "bool"
    if "TIMER" in t or t in ("TON", "TOF", "RTO"):
        return "timer"
    if "COUNTER" in t or t in ("CTU", "CTD"):
        return "counter"
    if t in ("SINT", "INT", "DINT", "LINT", "REAL", "LREAL", "NUMERIC", "WORD", "DWORD", "BYTE", "UINT",
             "UDINT", "USINT", "CHANNEL"):
        return "number"
    return t.lower()


# ----------------------------------------------------------------------------- drivers

class BaseDriver:
    name = "PLC"
    can_list_tags = True

    def __init__(self, ip: str, slot: int = 0, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.ip = (ip or "").strip()
        self.slot = int(slot or 0)
        self.timeout = float(timeout)

    def connect(self) -> None: ...
    def close(self) -> None: ...
    def info(self) -> dict[str, str]: return {}
    def list_tags(self) -> list[TagInfo]: return []
    def read(self, tags: list[str]) -> dict[str, Any]: return {}
    def write(self, tag: str, value: Any) -> None: ...


class FakeDriver(BaseDriver):
    """Simulated PLC: an in-memory tag table. No network."""
    name = "Simulated PLC"

    def __init__(self, ip: str = "sim", slot: int = 0, timeout: float = DEFAULT_TIMEOUT,
                 tags: dict[str, tuple[str, Any]] | None = None, fail_connect: bool = False) -> None:
        super().__init__(ip, slot, timeout)
        self.tags: dict[str, tuple[str, Any]] = dict(tags or {})
        self.connected = False
        self.fail_connect = fail_connect
        self.writes: list[tuple[str, Any]] = []

    def connect(self) -> None:
        if self.fail_connect:
            raise socket.timeout("simulated timeout")
        self.connected = True

    def close(self) -> None:
        self.connected = False

    def _need(self) -> None:
        if not self.connected:
            raise DeviceError("Not connected. Click Connect first.")

    def info(self) -> dict[str, str]:
        self._need()
        return {"Product": "Simulated PLC", "Revision": "1.0", "Mode": "RUN (simulated)", "IP": self.ip}

    def list_tags(self) -> list[TagInfo]:
        self._need()
        return [TagInfo(n, t) for n, (t, _v) in sorted(self.tags.items())]

    def read(self, tags: list[str]) -> dict[str, Any]:
        self._need()
        return {t: (self.tags[t][1] if t in self.tags else "(no such tag)") for t in tags}

    def write(self, tag: str, value: Any) -> None:
        self._need()
        if tag not in self.tags:
            raise DeviceError(f"The PLC has no tag named {tag}.")
        self.tags[tag] = (self.tags[tag][0], value)
        self.writes.append((tag, value))


class LogixLink(BaseDriver):
    name = "Allen-Bradley Logix (pycomm3)"
    micro800 = False

    def connect(self) -> None:
        try:
            from pycomm3 import LogixDriver
        except ImportError as exc:
            raise DeviceError("The pycomm3 package is missing, so the Allen-Bradley link is not available.") from exc
        path = self.ip if self.micro800 else f"{self.ip}/{self.slot}"
        self.drv = LogixDriver(path, init_program_tags=False)
        try:
            self.drv.socket_timeout = self.timeout
        except Exception:
            pass
        try:
            self.drv.open()
        except Exception as exc:
            raise DeviceError(plain_error(exc.__cause__ or exc, self.ip)) from exc

    def close(self) -> None:
        try:
            self.drv.close()
        except Exception:
            pass

    def info(self) -> dict[str, str]:
        raw = dict(getattr(self.drv, "info", {}) or {})
        keep = ("product_name", "revision", "serial", "name", "keyswitch", "status", "vendor")
        return {k.replace("_", " ").title(): str(raw[k]) for k in keep if k in raw}

    def list_tags(self) -> list[TagInfo]:
        tags = getattr(self.drv, "tags", {}) or {}
        return [TagInfo(n, str(d.get("data_type_name") or d.get("data_type") or "")) for n, d in sorted(tags.items())]

    def read(self, tags: list[str]) -> dict[str, Any]:
        if not tags:
            return {}
        res = self.drv.read(*tags)
        res = res if isinstance(res, list) else [res]
        return {r.tag: (r.value if not r.error else f"(error: {r.error})") for r in res}

    def write(self, tag: str, value: Any) -> None:
        res = self.drv.write((tag, value))
        if getattr(res, "error", None):
            raise DeviceError(f"The PLC refused the write to {tag}: {res.error}")


class Micro800Link(LogixLink):
    name = "Allen-Bradley Micro800 (pycomm3)"
    micro800 = True


_S7 = re.compile(r"^%?(?:(?P<area>[IQM])(?P<size>[BWD])?(?P<byte>\d+)(?:\.(?P<bit>[0-7]))?|"
                 r"DB(?P<db>\d+)\.DB(?P<dsize>[XBWD])(?P<dbyte>\d+)(?:\.(?P<dbit>[0-7]))?)$", re.I)


def parse_s7(address: str) -> dict[str, Any]:
    m = _S7.match((address or "").strip().replace(" ", ""))
    if not m:
        raise DeviceError(f"'{address}' is not a Siemens address Cabinet Studio can read "
                          "(examples: %I0.0, %Q0.1, %M10.0, %MW20, %IW64, DB1.DBX0.0, DB1.DBW2).")
    if m.group("db"):
        size = m.group("dsize").upper()
        return {"area": "DB", "db": int(m.group("db")), "byte": int(m.group("dbyte")),
                "bit": int(m.group("dbit")) if size == "X" and m.group("dbit") else None, "size": size}
    size = (m.group("size") or "X").upper()
    if size == "X" and m.group("bit") is None:
        raise DeviceError(f"'{address}' needs a bit number, e.g. %I0.0.")
    return {"area": m.group("area").upper(), "db": 0, "byte": int(m.group("byte")),
            "bit": int(m.group("bit")) if m.group("bit") is not None else None, "size": size}


def _s7_decode(data: bytes | bytearray, spec: dict[str, Any]) -> Any:
    if spec["bit"] is not None:
        return bool(data[0] >> spec["bit"] & 1)
    return {"B": lambda d: d[0], "W": lambda d: struct.unpack(">h", bytes(d[:2]))[0],
            "D": lambda d: struct.unpack(">i", bytes(d[:4]))[0]}[spec["size"]](data)


class S7Link(BaseDriver):
    name = "Siemens S7 (python-snap7)"
    can_list_tags = False
    rack, default_slot = 0, 1

    def __init__(self, ip: str, slot: int = 0, timeout: float = DEFAULT_TIMEOUT, tag_map: dict[str, str] | None = None):
        super().__init__(ip, slot or self.default_slot, timeout)
        self.tag_map = dict(tag_map or {})

    def connect(self) -> None:
        try:
            import snap7
        except ImportError as exc:
            raise DeviceError("The python-snap7 package is missing, so the Siemens link is not available.") from exc
        self.cli = snap7.client.Client()
        old = socket.getdefaulttimeout()
        socket.setdefaulttimeout(self.timeout)
        try:
            self.cli.connect(self.ip, self.rack, self.slot)
        except Exception as exc:
            raise DeviceError(plain_error(exc, self.ip) + " For S7-1200/1500 also allow PUT/GET access in the CPU "
                              "protection settings.") from exc
        finally:
            socket.setdefaulttimeout(old)

    def close(self) -> None:
        try:
            self.cli.disconnect()
        except Exception:
            pass

    def info(self) -> dict[str, str]:
        out: dict[str, str] = {}
        try:
            ci = self.cli.get_cpu_info()
            for k in ("ModuleTypeName", "SerialNumber", "ASName", "ModuleName"):
                v = getattr(ci, k, b"")
                out[k] = v.decode(errors="ignore").strip("\x00 ") if isinstance(v, bytes) else str(v)
        except Exception as exc:
            out["Info"] = f"CPU info not available: {exc}"
        try:
            out["Mode"] = str(self.cli.get_cpu_state())
        except Exception:
            pass
        return out

    def _read_one(self, addr: str) -> Any:
        spec = parse_s7(addr)
        n = {"X": 1, "B": 1, "W": 2, "D": 4}[spec["size"]]
        if spec["area"] == "DB":
            data = self.cli.db_read(spec["db"], spec["byte"], n)
        else:
            fn = {"I": self.cli.eb_read, "Q": self.cli.ab_read, "M": self.cli.mb_read}[spec["area"]]
            data = fn(spec["byte"], n)
        return _s7_decode(data, spec)

    def read(self, tags: list[str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for t in tags:
            try:
                out[t] = self._read_one(self.tag_map.get(t, t))
            except DeviceError as exc:
                out[t] = f"(error: {exc})"
        return out

    def write(self, tag: str, value: Any) -> None:
        spec = parse_s7(self.tag_map.get(tag, tag))
        if spec["area"] in ("I", "Q"):
            raise DeviceError("Physical I/O (%I / %Q) is never written from Cabinet Studio.")
        n = {"X": 1, "B": 1, "W": 2, "D": 4}[spec["size"]]
        if spec["bit"] is not None:
            cur = bytearray(self.cli.db_read(spec["db"], spec["byte"], 1) if spec["area"] == "DB"
                            else self.cli.mb_read(spec["byte"], 1))
            cur[0] = (cur[0] | (1 << spec["bit"])) if _truthy(value) else (cur[0] & ~(1 << spec["bit"]) & 0xFF)
            data = cur
        else:
            fmt = {"B": ">B", "W": ">h", "D": ">i"}[spec["size"]]
            data = bytearray(struct.pack(fmt, int(value)))
        if spec["area"] == "DB":
            self.cli.db_write(spec["db"], spec["byte"], data)
        else:
            self.cli.mb_write(spec["byte"], n, data)


class S7ClassicLink(S7Link):
    name = "Siemens S7-300/400 (python-snap7)"
    default_slot = 2


_FINS_AREAS = {"CIO": (0x30, 0xB0), "W": (0x31, 0xB1), "H": (0x32, 0xB2), "D": (0x02, 0x82), "DM": (0x02, 0x82)}
_FINS = re.compile(r"^(?P<area>CIO|DM|D|W|H)?\s*(?P<word>\d+)(?:\.(?P<bit>\d{1,2}))?$", re.I)


def parse_fins(address: str) -> tuple[str, int, int | None]:
    m = _FINS.match((address or "").strip().upper())
    if not m:
        raise DeviceError(f"'{address}' is not an Omron address the FINS link can read "
                          "(examples: 0.00, CIO 100, D100, W0.01, H10).")
    area = (m.group("area") or "CIO").upper()
    area = "D" if area == "DM" else area
    bit = int(m.group("bit")) if m.group("bit") is not None else None
    if bit is not None and bit > 15:
        raise DeviceError(f"'{address}': Omron bit numbers run 00 to 15.")
    return area, int(m.group("word")), bit


class FinsLink(BaseDriver):
    """Minimal FINS/UDP client (BETA): memory area read 0101 / write 0102 / controller data 0501."""
    name = "Omron FINS/UDP (BETA)"
    can_list_tags = False

    def __init__(self, ip: str, slot: int = 0, timeout: float = DEFAULT_TIMEOUT, tag_map: dict[str, str] | None = None,
                 port: int = 9600):
        super().__init__(ip, slot, timeout)
        self.port = port
        self.tag_map = dict(tag_map or {})
        self.sid = 0

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(self.timeout)
        node = int(self.ip.rsplit(".", 1)[-1]) if re.match(r"^\d+\.\d+\.\d+\.\d+$", self.ip) else 0
        self.da1 = node & 0xFF
        try:
            self._cmd(0x05, 0x01, b"")
        except DeviceError:
            raise
        except Exception as exc:
            self.close()
            raise DeviceError(plain_error(exc, self.ip) + " (FINS/UDP port 9600 must be enabled on the PLC.)") from exc

    def close(self) -> None:
        try:
            self.sock.close()
        except Exception:
            pass

    def _cmd(self, mrc: int, src: int, body: bytes) -> bytes:
        self.sid = (self.sid + 1) & 0xFF
        header = bytes([0x80, 0x00, 0x02, 0x00, self.da1, 0x00, 0x00, 0x01, 0x00, self.sid])
        self.sock.sendto(header + bytes([mrc, src]) + body, (self.ip, self.port))
        data, _ = self.sock.recvfrom(2048)
        if len(data) < 14:
            raise DeviceError("The PLC sent a short FINS reply.")
        end = data[12] << 8 | data[13]
        if end & 0x7F3F:
            raise DeviceError(f"The PLC answered with FINS end code {end:04X} (address out of range or protected).")
        return data[14:]

    def info(self) -> dict[str, str]:
        raw = self._cmd(0x05, 0x01, b"")
        return {"Model": raw[:20].decode("ascii", "ignore").strip(), "Version": raw[20:40].decode("ascii", "ignore").strip(),
                "Link": "FINS/UDP (BETA)"}

    def _read_one(self, addr: str) -> Any:
        area, word, bit = parse_fins(addr)
        bit_code, word_code = _FINS_AREAS[area]
        code = bit_code if bit is not None else word_code
        body = bytes([code]) + struct.pack(">H", word) + bytes([bit or 0]) + struct.pack(">H", 1)
        raw = self._cmd(0x01, 0x01, body)
        return bool(raw[0]) if bit is not None else struct.unpack(">H", raw[:2])[0]

    def read(self, tags: list[str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for t in tags:
            try:
                out[t] = self._read_one(self.tag_map.get(t, t))
            except DeviceError as exc:
                out[t] = f"(error: {exc})"
        return out

    def write(self, tag: str, value: Any) -> None:
        area, word, bit = parse_fins(self.tag_map.get(tag, tag))
        if area == "CIO":
            raise DeviceError("CIO (physical I/O area) is never written from Cabinet Studio. Use D, W or H.")
        bit_code, word_code = _FINS_AREAS[area]
        if bit is not None:
            body = bytes([bit_code]) + struct.pack(">H", word) + bytes([bit]) + struct.pack(">H", 1) + \
                bytes([1 if _truthy(value) else 0])
        else:
            body = bytes([word_code]) + struct.pack(">H", word) + b"\x00" + struct.pack(">H", 1) + \
                struct.pack(">H", int(value) & 0xFFFF)
        self._cmd(0x01, 0x02, body)


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "on", "yes")
    return bool(value)


def make_driver(choice: int | str, ip: str, slot: int = 0, *, timeout: float = DEFAULT_TIMEOUT,
                tag_map: dict[str, str] | None = None) -> BaseDriver:
    idx = DRIVER_CHOICES.index(choice) if isinstance(choice, str) else int(choice)
    if idx != 5 and not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", (ip or "").strip()):
        raise DeviceError("Enter the PLC's IP address, for example 192.168.1.10.")
    cls = (LogixLink, Micro800Link, S7Link, S7ClassicLink, FinsLink, FakeDriver)[idx]
    if cls in (S7Link, S7ClassicLink, FinsLink):
        return cls(ip, slot, timeout, tag_map=tag_map)
    return cls(ip, slot, timeout)


HMI_PORTS = {80: "web server", 443: "secure web server", 5900: "VNC remote screen", 44818: "EtherNet/IP",
             102: "Siemens S7 / WinCC", 9600: "Omron FINS"}


def hmi_probe(ip: str, ports: tuple[int, ...] = tuple(HMI_PORTS), timeout: float = 1.5) -> list[int]:
    """TCP ports that answer on an HMI (reachability only; screens are downloaded by the HMI software)."""
    if not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", (ip or "").strip()):
        raise DeviceError("Enter the HMI's IP address, for example 192.168.1.20.")
    found: list[int] = []
    for port in ports:
        try:
            with socket.create_connection((ip.strip(), port), timeout=timeout):
                found.append(port)
        except OSError:
            continue
    return found


def probe_text(ip: str, ports: list[int]) -> str:
    if not ports:
        return (f"No answer from {ip} on the usual HMI ports. Check the cable, IP address and that the panel is "
                "powered. Screens are downloaded with the HMI maker's software.")
    return (f"{ip} answers on: " + ", ".join(f"{p} ({HMI_PORTS.get(p, 'open')})" for p in ports)
            + ". The panel is reachable. Download screens with the HMI maker's software.")


# ----------------------------------------------------------------------------- session

class DeviceLink:
    """One connection plus the project's tag knowledge and the write-safety rules."""

    def __init__(self, driver: BaseDriver, project=None, plc_id: str | None = None) -> None:
        self.driver = driver
        self.project = project
        self.connected = False
        self.io: dict[str, str] = {}
        self.project_types: dict[str, str] = {}
        if project is not None:
            self._load_project(plc_id)
        if isinstance(driver, FakeDriver) and not driver.tags:
            driver.tags = {t: (ty, 0) for t, ty in self.project_types.items()}

    def _load_project(self, plc_id: str | None) -> None:
        from cabinet_studio.services.io_assign import assign_io
        from cabinet_studio.services.ladder_tools import tag_table
        from cabinet_studio.services.programming import cabinet_device_tags

        report = assign_io(self.project, plc_id, write=False)
        self.io = {r.tag: r.address for r in report.rows}
        self.io_kind = {r.tag: r.kind for r in report.rows}
        try:
            for row in tag_table(self.project.program or {}, cabinet_device_tags(self.project)):
                if row.get("type") != "ALIAS":
                    self.project_types[row["name"]] = row.get("type") or "BOOL"
        except Exception:
            pass
        for tag, kind in self.io_kind.items():
            self.project_types.setdefault(tag, "BOOL" if kind in ("DI", "DO") else "INT")

    def connect(self) -> dict[str, str]:
        self.driver.connect()
        self.connected = True
        return self.driver.info()

    def close(self) -> None:
        self.driver.close()
        self.connected = False

    def info(self) -> dict[str, str]:
        return self.driver.info()

    def project_tags(self) -> list[str]:
        return sorted(self.project_types)

    def compare_tags(self) -> TagCompare:
        if not self.driver.can_list_tags:
            return TagCompare(note=f"{self.driver.name} does not share its tag names over the network. "
                                   "Watch tags by address instead (the I/O list shows each address).")
        plc = {t.name: t.data_type for t in self.driver.list_tags()}
        proj = self.project_types
        out = TagCompare()
        out.missing = sorted(t for t in proj if t not in plc)
        out.extra = sorted(t for t in plc if t not in proj and not t.startswith(("Local:", "__", "_IO_")))
        for t in sorted(set(proj) & set(plc)):
            if _category(proj[t]) != _category(plc[t]) and _category(proj[t]) not in ("alias", ""):
                out.mismatch.append((t, proj[t], plc[t]))
        return out

    def read(self, tags: list[str]) -> dict[str, Any]:
        return self.driver.read(list(tags))

    def write_refusal(self, tag: str) -> str:
        """Why a write to this tag is refused, or '' when it may be written."""
        t = (tag or "").strip()
        if not t:
            return "Pick a tag to write."
        if is_safety_tag(t):
            return (f"{t} looks like a safety tag (E-stop, guard, light curtain, safety relay). Cabinet Studio never "
                    "writes safety tags. The software is never the safety function (NFPA 79 / ISO 13849).")
        if t in self.io or PHYSICAL_ADDRESS.match(t):
            return (f"{t} is physical I/O wired to a real device. Its value comes from the field wiring or the "
                    "program, so Cabinet Studio never writes it. Write HMI_ bits or setpoints instead.")
        return ""

    def write(self, tag: str, value: Any, *, confirmed: bool) -> None:
        if not confirmed:
            raise DeviceError("Tick 'I am at the machine and it is safe' before writing to a real PLC.")
        reason = self.write_refusal(tag)
        if reason:
            raise DeviceError(reason)
        if not self.connected:
            raise DeviceError("Not connected. Click Connect first.")
        self.driver.write(tag.strip(), value)
