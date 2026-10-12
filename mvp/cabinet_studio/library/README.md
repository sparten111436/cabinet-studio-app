# Equipment library

Three JSON files. The app loads them at startup and refuses to open if they disagree.

| File | What it holds |
| --- | --- |
| `schema.json` | Field groups, fields shared by every supervised device, and one block per equipment class |
| `catalog.json` | Starter parts from Allen-Bradley, Siemens, and generic Modbus-capable devices |
| `layouts.json` | Cabinet templates. Each placement points at a catalog id |

To add a class, add a type in `schema.json` and at least one catalog item whose `type_id` matches. Set `supervised` to true when a PLC will control or watch the device. Those types always carry tag, description, vendor, catalog, mounting, terminal landings, wire numbers, PLC I/O direction, PLC I/O address, and notes. Put class-specific questions in `fields`. Use `field_overrides` to make a shared field required for that class (the PLC catalog number is required; a pushbutton catalog number is not).

`descriptor_keys` are the short specs drawn on the tile. They must be field keys.

Catalog `defaults` may only name fields that exist on that type. Choice values must be one of the field's options. Leave installation facts empty — wire numbers, landings, and I/O addresses — so a new device stays flagged until someone answers them.
