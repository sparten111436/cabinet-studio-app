"""Starter library of operator touch panels (HMIs).

One JSON file (library/hmi_catalog.json) feeds the HMI interview, the HMI
editor canvas and the HMI drawing sheets. Sizes are typical published values;
every entry says to verify the cutout with the maker before cutting a door.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parent.parent / "library" / "hmi_catalog.json"
MAKERS = ("Allen-Bradley", "Siemens", "Omron")
MM_PER_IN = 25.4
REQUIRED_FIELDS = (
    "id", "maker", "family", "model", "catalog_number", "screen_in", "resolution_px", "aspect",
    "touch", "function_keys", "bezel_w_mm", "bezel_h_mm", "depth_mm", "cutout_w_mm", "cutout_h_mm",
    "mounting", "power", "power_w", "comms", "plc_families", "software", "max_screens", "max_objects",
    "ip_rating", "price_tier", "summary", "source_url", "verify",
)
_TIER_RANK = {"budget": 1, "mid": 0, "high": 3}
_cache: dict[str, list[dict]] = {}

# Words in a PLC's library id / vendor / catalog that name its family.
_PLC_FAMILY_WORDS = (
    ("CompactLogix", ("compactlogix", "5069-", "1769-", "5380", "5370")),
    ("ControlLogix", ("controllogix", "1756-")),
    ("Micro800", ("micro8", "2080-")),
    ("MicroLogix", ("micrologix", "1766-", "1763-")),
    ("S7-1200", ("s7-1200", "1214c", "1215c", "1212c", "6es7 21", "6es721")),
    ("S7-1500", ("s7-1500", "1511", "1513", "1515", "6es7 51", "6es751")),
    ("NX1P", ("nx1p",)),
    ("NX", ("nx102", "nx502", "nx701", "omron nx")),
    ("NJ", ("nj101", "nj301", "nj501", "omron nj")),
    ("CP1", ("cp1e", "cp1h", "cp1l", "cp2e")),
)


def load_hmi_catalog(path: Path | str | None = None) -> list[dict]:
    """Every HMI entry, fully filled in (defaults, then family, then the entry)."""
    key = str(path or CATALOG_PATH)
    if key not in _cache:
        data = json.loads(Path(key).read_text(encoding="utf-8"))
        defaults = data.get("defaults") or {}
        families = data.get("families") or {}
        entries = []
        for raw in data.get("items") or []:
            entry = {**defaults, **families.get(raw.get("family_key", ""), {}), **raw}
            entry.pop("family_key", None)
            w, h = (int(v) for v in entry["resolution_px"])
            g = math.gcd(w, h) or 1
            entry.setdefault("aspect", f"{w // g}:{h // g}")
            entry.setdefault(
                "summary",
                f"{entry['screen_in']:g} in {entry['family']} touch panel, {w}x{h}, "
                f"{', '.join(entry['comms'][:2])}; programmed in {entry['software']}.",
            )
            entries.append(entry)
        _cache[key] = entries
    return [dict(entry, comms=list(entry["comms"]), plc_families=list(entry["plc_families"]))
            for entry in _cache[key]]


def hmi_by_id(model_id: str) -> dict | None:
    for entry in load_hmi_catalog():
        if entry["id"] == model_id:
            return entry
    return None


def hmi_label(entry: dict) -> str:
    return f"{entry['maker']} {entry['model']} ({entry['catalog_number']})"


def hmi_id_from_label(text: str) -> str | None:
    """Accept a model id or the label shown in pick lists."""
    text = (text or "").strip()
    for entry in load_hmi_catalog():
        if text in (entry["id"], hmi_label(entry), entry["catalog_number"]):
            return entry["id"]
    return None


def normalize_maker(text: str) -> str:
    low = (text or "").lower()
    if "allen" in low or "rockwell" in low or low.strip() in {"ab", "a-b"}:
        return "Allen-Bradley"
    if "siemens" in low:
        return "Siemens"
    if "omron" in low:
        return "Omron"
    return ""


def hmi_choices(maker: str | None = None, min_in: float | None = None, max_in: float | None = None,
                plc_family: str | None = None) -> list[dict]:
    """Library entries filtered by maker, screen size range and PLC family, smallest first."""
    want = normalize_maker(maker or "")
    out = []
    for entry in load_hmi_catalog():
        if want and entry["maker"] != want:
            continue
        if min_in is not None and entry["screen_in"] < min_in:
            continue
        if max_in is not None and entry["screen_in"] > max_in:
            continue
        if plc_family and plc_family not in entry["plc_families"]:
            continue
        out.append(entry)
    out.sort(key=lambda e: (MAKERS.index(e["maker"]) if e["maker"] in MAKERS else 9, e["screen_in"],
                            _TIER_RANK.get(e["price_tier"], 2), e["id"]))
    return out


def hmi_sizes(maker: str | None = None) -> list[float]:
    return sorted({entry["screen_in"] for entry in hmi_choices(maker)})


def screen_area_in(entry: dict) -> tuple[float, float]:
    """Visible screen width / height in inches from the diagonal and pixel shape."""
    w, h = entry["resolution_px"]
    diag = math.hypot(w, h)
    return entry["screen_in"] * w / diag, entry["screen_in"] * h / diag


def hmi_door_outline(model_id: str) -> tuple[float, float]:
    """Bezel width / height in inches, for drawing the HMI to scale on a door layout."""
    entry = hmi_by_id(model_id)
    if entry is None:
        raise KeyError(f"Unknown HMI model {model_id!r}.")
    return entry["bezel_w_mm"] / MM_PER_IN, entry["bezel_h_mm"] / MM_PER_IN


def project_plc_families(project) -> list[str]:
    """PLC families named by the PLCs already on the cabinet (never guessed from anything else)."""
    found: list[str] = []
    for item in getattr(project, "items", []) or []:
        if item.type_id != "plc":
            continue
        hay = " ".join([item.library_id or "", *item.fields.values()]).lower()
        for family, words in _PLC_FAMILY_WORDS:
            if any(word in hay for word in words) and family not in found:
                found.append(family)
    return found


def project_maker_preference(project) -> str:
    """Maker from the interview answer, else from a PLC's vendor field."""
    interview = getattr(project, "interview", {}) or {}
    maker = normalize_maker(interview.get("hmi_maker", "")) or normalize_maker(interview.get("manufacturer", ""))
    if maker:
        return maker
    for item in getattr(project, "items", []) or []:
        if item.type_id == "plc":
            maker = normalize_maker(item.fields.get("vendor", "") or item.library_id or "")
            if maker:
                return maker
    for family in project_plc_families(project):
        for entry in load_hmi_catalog():
            if family in entry["plc_families"]:
                return entry["maker"]
    return ""


def _parse_inches(text: str) -> float | None:
    try:
        return float(str(text).lower().replace("in", "").replace('"', "").strip())
    except ValueError:
        return None


def recommend_hmi(source, size_in: float | None = None) -> tuple[str, str]:
    """Best library model id plus a plain-words reason.

    ``source`` is a Project or a dict of answers (keys hmi_maker / manufacturer / hmi_size).
    """
    if isinstance(source, dict):
        answers, project = source, None
    else:
        project = source
        answers = dict(getattr(project, "interview", {}) or {})
    maker = normalize_maker(answers.get("hmi_maker", "")) or normalize_maker(answers.get("manufacturer", ""))
    if not maker and project is not None:
        maker = project_maker_preference(project)
    families = project_plc_families(project) if project is not None else []
    devices = 0
    if project is not None:
        devices = sum(1 for item in project.items if (item.fields.get("tag") or "").strip())
    target = size_in or _parse_inches(answers.get("hmi_size", ""))
    size_reason = "your size choice"
    if not target:
        target = 7.0 if devices <= 8 else 10.0 if devices <= 20 else 12.0
        size_reason = f"{devices} tagged devices on this cabinet"
    pool = hmi_choices(maker) or hmi_choices()

    def score(entry: dict) -> float:
        pairs = not families or any(f in entry["plc_families"] for f in families)
        return abs(entry["screen_in"] - target) * 10 + (0 if pairs else 15) + _TIER_RANK.get(entry["price_tier"], 2)

    best = min(pool, key=score)
    bits = [f"{hmi_label(best)}."]
    if maker:
        bits.append(f"It is a {best['maker']} panel to match your maker choice.")
    bits.append(f"About {best['screen_in']:g} in suits {size_reason}.")
    paired = [f for f in families if f in best["plc_families"]]
    if paired:
        bits.append(f"It talks to your {paired[0]} PLC over {best['comms'][0]}.")
    bits.append(f"Programmed in {best['software']}.")
    return best["id"], " ".join(bits)
