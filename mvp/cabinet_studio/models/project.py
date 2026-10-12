"""A cabinet project: placed devices plus the answers captured so far."""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_CABINET_WIDTH = 780.0
DEFAULT_CABINET_HEIGHT = 860.0
NAMEPLATE_CLEARANCE = 48.0
# Physical enclosure / backing plate (inches). Design-aid defaults until a
# verified enclosure catalog is filled in from research.
DEFAULT_ENCLOSURE_WIDTH_IN = 36.0
DEFAULT_ENCLOSURE_HEIGHT_IN = 48.0
DEFAULT_BACKPLATE_WIDTH_IN = 30.0
DEFAULT_BACKPLATE_HEIGHT_IN = 42.0


@dataclass
class PlacedItem:
    id: str
    library_id: str | None
    type_id: str
    x: float
    y: float
    fields: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.x = float(self.x)
        self.y = float(self.y)
        self.library_id = None if self.library_id in (None, "") else str(self.library_id)
        self.type_id = str(self.type_id)
        self.fields = {
            str(key): "" if value is None else str(value)
            for key, value in self.fields.items()
        }

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "library_id": self.library_id,
            "type_id": self.type_id,
            "x": self.x,
            "y": self.y,
            "fields": dict(self.fields),
        }


@dataclass
class Project:
    name: str
    template_id: str | None
    cabinet_width: float
    cabinet_height: float
    cabinet_label: str
    subtitle: str = ""
    notes: str = ""
    interview: dict[str, str] = field(default_factory=dict)
    program: dict = field(default_factory=dict)
    wiring_context: dict = field(default_factory=dict)
    items: list[PlacedItem] = field(default_factory=list)
    # Physical sizes in inches (backing plate drawn on layout sheets).
    enclosure_width_in: float = DEFAULT_ENCLOSURE_WIDTH_IN
    enclosure_height_in: float = DEFAULT_ENCLOSURE_HEIGHT_IN
    backplate_width_in: float = DEFAULT_BACKPLATE_WIDTH_IN
    backplate_height_in: float = DEFAULT_BACKPLATE_HEIGHT_IN
    enclosure_maker: str = ""
    enclosure_catalog: str = ""

    def __post_init__(self) -> None:
        self.name = str(self.name)
        self.template_id = None if self.template_id in (None, "") else str(self.template_id)
        self.cabinet_width = float(self.cabinet_width)
        self.cabinet_height = float(self.cabinet_height)
        self.cabinet_label = str(self.cabinet_label)
        self.enclosure_width_in = float(self.enclosure_width_in or DEFAULT_ENCLOSURE_WIDTH_IN)
        self.enclosure_height_in = float(self.enclosure_height_in or DEFAULT_ENCLOSURE_HEIGHT_IN)
        self.backplate_width_in = float(self.backplate_width_in or DEFAULT_BACKPLATE_WIDTH_IN)
        self.backplate_height_in = float(self.backplate_height_in or DEFAULT_BACKPLATE_HEIGHT_IN)
        self.enclosure_maker = str(self.enclosure_maker or "")
        self.enclosure_catalog = str(self.enclosure_catalog or "")
        self.subtitle = str(self.subtitle or "")
        self.notes = str(self.notes or "")
        self.interview = {
            str(key): "" if value is None else str(value)
            for key, value in (self.interview or {}).items()
        }
        from cabinet_studio.services.programming import program_from_dict
        from cabinet_studio.services.wiring_assist import empty_wiring_context

        self.program = program_from_dict(self.program or {})
        raw_ctx = self.wiring_context if isinstance(self.wiring_context, dict) else {}
        merged = empty_wiring_context()
        for key, value in raw_ctx.items():
            merged[str(key)] = value
        self.wiring_context = merged
        self.items = list(self.items)

    def find(self, item_id: str) -> PlacedItem | None:
        for item in self.items:
            if item.id == item_id:
                return item
        return None

    def to_dict(self) -> dict:
        from cabinet_studio.services.programming import program_to_dict

        return {
            "format": "cabinet-studio-project",
            "version": 1,
            "name": self.name,
            "template_id": self.template_id,
            "subtitle": self.subtitle,
            "notes": self.notes,
            "interview": dict(self.interview),
            "program": program_to_dict(self.program),
            "wiring_context": dict(self.wiring_context or {}),
            "cabinet": {
                "label": self.cabinet_label,
                "width": self.cabinet_width,
                "height": self.cabinet_height,
                "enclosure_width_in": self.enclosure_width_in,
                "enclosure_height_in": self.enclosure_height_in,
                "backplate_width_in": self.backplate_width_in,
                "backplate_height_in": self.backplate_height_in,
                "enclosure_maker": self.enclosure_maker,
                "enclosure_catalog": self.enclosure_catalog,
            },
            "items": [item.to_dict() for item in self.items],
        }
