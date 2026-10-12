"""The wizard asks class-specific questions for every supervised device."""

from cabinet_studio.services.library_loader import load_library
from cabinet_studio.services.wizard_plan import fields_by_group


def test_every_class_has_its_own_specification_step():
    library = load_library()
    specs: dict[str, tuple[str, ...]] = {}
    for type_id, equipment in library.types.items():
        steps = fields_by_group(library.groups, equipment.fields)
        by_id = {group.id: fields for group, fields in steps}
        assert "specifications" in by_id
        assert by_id["specifications"]
        wiring = {field.key for field in by_id["wiring"]}
        plc_io = {field.key for field in by_id["plc_io"]}
        identity = {field.key for field in by_id["identity"]}
        assert {"tag", "description", "vendor"} <= identity
        assert {"terminal_landings", "wire_numbers"} <= wiring
        assert {"io_direction", "io_address"} <= plc_io
        specs[type_id] = tuple(field.key for field in by_id["specifications"])

    assert "horsepower" in specs["motor"]
    assert "pinout" not in specs["motor"]
    assert "sensor_kind" in specs["sensor"]
    assert "horsepower" not in specs["sensor"]
    assert "size" in specs["valve"]
    assert "color" in specs["light"]
    assert "ip_address" in specs["plc"]
    assert "screen_size" in specs["hmi"]
    assert specs["motor"] != specs["sensor"]
    assert specs["valve"] != specs["light"]
    assert specs["plc"] != specs["pushbutton"]
    assert specs["estop"] != specs["safety_relay"]
    assert specs["transmitter"] != specs["io_module"]
