"""The starter library loads, and every supervised class has a real schema."""

from cabinet_studio.services.descriptors import tile_text
from cabinet_studio.services.layouts import instantiate_layout
from cabinet_studio.services.library_loader import load_library
from cabinet_studio.services.placement import rects_overlap

MINIMUM_FIELDS = (
    "tag",
    "description",
    "vendor",
    "catalog",
    "mounting",
    "terminal_landings",
    "wire_numbers",
    "io_direction",
    "io_address",
    "notes",
)

ALWAYS_REQUIRED = (
    "tag",
    "description",
    "vendor",
    "terminal_landings",
    "wire_numbers",
    "io_direction",
    "io_address",
)

EXTRA_REQUIRED = {
    "motor": ("horsepower", "rpm", "torque", "voltage", "fla", "pinout"),
    "vfd": ("horsepower", "voltage", "fla", "control_mode", "comms"),
    "plc": ("catalog", "ip_address", "slot_count", "protocol"),
    "hmi": ("catalog", "screen_size", "ip_address", "protocol"),
    "contactor": ("coil_voltage", "poles", "amp_rating"),
    "estop": ("contact_config", "voltage", "reset_style"),
    "ethernet_switch": ("port_count", "managed", "ip_address"),
    "power_supply": ("input_voltage", "output_voltage", "output_current", "phases"),
    "sensor": ("sensor_kind", "signal", "range_span", "wiring_style"),
    "valve": ("size", "solenoid_voltage", "ports", "fail_position"),
    "solenoid": ("voltage", "duty"),
    "light": ("color", "voltage", "function"),
    "safety_relay": ("safety_function", "channels", "reset_type"),
    "transmitter": ("measured_variable", "range_span", "signal", "loop_power"),
    "io_module": ("catalog", "io_kind", "point_count", "parent_tag", "slot"),
    "pushbutton": ("color", "function", "contact", "voltage"),
}


def test_library_loads_vendors_and_classes():
    library = load_library()
    assert library.version == 1
    assert set(EXTRA_REQUIRED) <= set(library.types)
    vendors = {item.vendor for item in library.catalog}
    assert {"Allen-Bradley", "Siemens", "Generic / Modbus"}.issubset(vendors)
    assert {"Hoffman", "Saginaw", "Hammond"}.issubset(vendors)
    ids = {item.id for item in library.catalog}
    assert {"generic-modbus-plc", "generic-modbus-hmi", "generic-modbus-vfd", "generic-modbus-io"} <= ids
    assert len(library.layouts) == 3


def test_every_supervised_type_has_the_minimum_questions():
    library = load_library()
    group_ids = {group.id for group in library.groups}
    for type_id, equipment in library.types.items():
        if equipment.id in {"enclosure", "backplate"}:
            assert equipment.supervised is False
            continue
        assert equipment.supervised is True
        keys = [field.key for field in equipment.fields]
        assert list(MINIMUM_FIELDS) == [key for key in keys if key in MINIMUM_FIELDS]
        required = {field.key for field in equipment.fields if field.required}
        assert set(ALWAYS_REQUIRED) <= required
        assert set(EXTRA_REQUIRED[type_id]) <= required
        for field in equipment.fields:
            assert field.group in group_ids
            assert field.help.strip()
        for key in equipment.descriptor_keys:
            assert key in keys


def test_catalog_defaults_and_layouts_fit_the_cabinet():
    library = load_library()
    assert library.catalog
    for layout in library.layouts:
        tags = [placement.tag for placement in layout.placements]
        assert len(tags) == len(set(tags))
        rects = []
        for placement in layout.placements:
            catalog = library.catalog_by_id[placement.library_id]
            equipment = library.types[catalog.type_id]
            rect = (placement.x, placement.y, equipment.tile_w, equipment.tile_h)
            assert placement.y >= 48
            assert placement.x + equipment.tile_w <= layout.cabinet_width - 12
            assert placement.y + equipment.tile_h <= layout.cabinet_height - 12
            for other in rects:
                assert not rects_overlap(rect, other, pad=12)
            rects.append(rect)


def test_template_devices_start_flagged_on_installation_fields():
    library = load_library()
    for layout in library.layouts:
        project = instantiate_layout(layout, library, "Check")
        assert project.items
        assert project.template_id == layout.id
        for item in project.items:
            equipment = library.types[item.type_id]
            assert item.fields["tag"]
            assert item.fields["description"]
            assert item.fields["vendor"] in {"Allen-Bradley", "Siemens", "Generic / Modbus", "Hoffman", "Saginaw", "Hammond"}
            for key in ("terminal_landings", "wire_numbers", "io_direction", "io_address"):
                assert not item.fields[key].strip()
            required = {field.key for field in equipment.fields if field.required}
            assert "terminal_landings" in required


def test_tile_descriptor_uses_answered_specs():
    library = load_library()
    project = instantiate_layout(library.layout_by_id["small-motor-cabinet"], library)
    motor = next(item for item in project.items if item.type_id == "motor")
    tag, kind, detail = tile_text(motor, library.types["motor"])
    assert tag == "MTR1"
    assert kind == "Motor"
    assert "5 HP" in detail
    assert "460 VAC" in detail
    motor.fields["tag"] = ""
    assert tile_text(motor, library.types["motor"])[0] == "UNTAGGED"
