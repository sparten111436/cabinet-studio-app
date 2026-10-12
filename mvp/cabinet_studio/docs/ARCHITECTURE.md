# Cabinet Studio architecture

Cabinet Studio is a desktop app for laying out a cabinet and defining every device a PLC will supervise. It is a CustomTkinter HMI for Warren Williams at ERMCO. It does not download to a controller, draw an EPLAN project, or open a fieldbus session.

## Folder on Warren's PC

Cabinet Studio does not live inside SpartenRobotics.

```
C:\Users\Warren.Williams\OneDrive - ERMCO\Desktop\CabinetStudio\
    project\    this source, docs, library, and program templates
    builds\     packaged exe later
    saves\      user *.cabinet.json files
```

`services/paths.py` picks `saves` and `builds`. If this checkout is `CabinetStudio\project`, those are the sibling folders. A plain checkout uses `saves` and `builds` next to the source so they can be copied into the tree above. `CABINET_STUDIO_HOME` overrides the CabinetStudio root. Shop memory lives at `saves/standards_profile.json`.

## How the window is built

One `CTk` window owns every other window. The splash, the wizard, the type picker, and the program-stub viewer are `CTkToplevel` children. There is never a second root.

The main window packs in this order:

1. Header, top
2. Orange rule, top
3. Status bar, bottom
4. Body, top, expand
5. Inside the body: left rail, then the right inspector, then the center canvas with `expand=True`

The inspector is packed before the expanding center on purpose. On a scaled display, CustomTkinter drops a side panel that is packed after an `expand=True` sibling. Both rails use a scrollable frame. Add-device actions stay pinned at the bottom of the left rail so they remain reachable while the device list scrolls.

Colors are fixed: background `#0d0d0f`, panels `#16161a`, orange `#ff8a1f`, cyan `#2ee6d6`, primary buttons `#2f6bff`.

## Package map

```
cabinet_studio/
  app.py                 entry point used by python -m cabinet_studio
  ui/                    CustomTkinter windows
  models/                schema dataclasses and the project model
  services/              load, save, completeness, placement
  services/drivers/      EtherNet/IP, S7, and Modbus TCP stubs
  library/               schema.json, catalog.json, layouts.json
  programs/              cut-and-paste AB, Siemens, and Modbus TCP stubs
  docs/ARCHITECTURE.md
```

`python app.py` from the repo root calls the same `main()`.

## Equipment schema

`services/library_loader.py` reads the JSON, merges common fields with each type, and rejects overlap, unknown defaults, and placements that sit on the nameplate or on each other.

Every supervised type gets these fields:

| Key | Required | Why it is here |
| --- | --- | --- |
| tag | yes | Same name on the schematic, HMI, and PLC |
| description | yes | What the device does |
| vendor | yes | Allen-Bradley, Siemens, or Generic / Modbus |
| catalog | only when the class says so | Known part number |
| mounting | no | In cabinet, on the door, or a field device |
| terminal_landings | yes | Where the conductors land |
| wire_numbers | yes | Numbers to print |
| io_direction | yes | Input, output, both, or network |
| io_address | yes | Address placeholder |
| notes | no | Anything else that must not be forgotten |
| wire_color | no | Shop color suggestion. Editable. |

Class fields sit in the same groups. A motor asks for HP/kW, RPM, torque, voltage, FLA, and pinout. A sensor asks for type, signal, range, and wiring. A valve asks for size, solenoid voltage, ports, and fail position. A light asks for color, voltage, and function. A PLC asks for catalog, IP, slots, and protocol. The wizard walks Identity, Specifications, Wiring, PLC I/O, Notes, then Review.

A device is complete only when every required field for its type is non-blank. Templates prefill the tag, the description, and catalog facts such as a known coil voltage. They do not prefill landings, wire numbers, or I/O addresses, so those tiles start flagged.

`descriptor_keys` become the third line on the tile. An orange corner means the definition is still open.

## Project file

`services/project_store.py` writes JSON:

```json
{
  "format": "cabinet-studio-project",
  "version": 1,
  "name": "Line 2 MCC",
  "template_id": "small-motor-cabinet",
  "cabinet": {"label": "MCC1", "width": 780, "height": 860},
  "items": [
    {
      "id": "…",
      "library_id": "motor-nema-5hp",
      "type_id": "motor",
      "x": 24,
      "y": 320,
      "fields": {"tag": "MTR1"}
    }
  ]
}
```

Positions are layout units on a 780 by 860 elevation, not screen pixels. Unknown top-level keys are ignored so a later metadata field does not make an older build refuse the file. A different `version` is refused.

## Guide build and UL 508A review

`services/suggestions.py` is deterministic. Given the same interview, shop profile, and project, it returns the same catalog part, landings, wire number, and wire color. Stock Allen-Bradley parts in the starter library win until the shop profile records an accepted catalog id for that class. A device saved with `nonstandard` set to Yes does not update the profile.

`services/ul508a.py` reviews the open project against UL 508A design-review checks. Ids look like `UL508A-DISC-01`. Status is `pass`, `warn`, or `missing`. Advisory checks read the application interview. The window title is "UL 508A design review (advisory)". Nothing in this module claims a listing or a certification.

## What is deliberately not live

| Module | Behavior in this build |
| --- | --- |
| `services/voice_capture.py` | Raises. No microphone library is imported. |
| `services/catalog_feed.py` | Raises. Edit the JSON locally. No download. |
| `services/compatibility_watch.py` | Returns no findings. |
| `services/drivers/ethernetip.py` | `allow_live = False`. `connect` raises `LiveDriverDisabled`. |
| `services/drivers/s7.py` | Same, port 102 documented only. |
| `services/drivers/modbus_tcp.py` | Same, port 502 documented only. |
| `programs/` | Text stubs for Logix ST, TIA SCL, and a Modbus register map. Nothing opens a socket. |

`DriverStub.connect` checks `allow_live` and then raises `NotImplementedError` even if a caller flips the flag. There is no session code behind the gate.

## Tests

`tests/test_library_load.py` loads the library and checks every supervised class, the three vendors, and the templates.

`tests/test_project_serialize.py` saves and loads a project and checks that a motor stays flagged until its required fields are filled.

`tests/test_stubs.py` checks that the drivers refuse a connection and that the program stubs do not import a socket.

`tests/test_smoke_ui.py` opens the window on a display, checks that the splash is a `CTkToplevel` of the main window, and places a device through the wizard.

`tests/test_suggestions.py` locks the suggestion engine to a fixed standards profile.

`tests/test_ul508a.py` checks that an incomplete project produces UL 508A findings and that the checker does not claim a listing.
