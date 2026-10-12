# Cabinet Studio

Cabinet Studio is a dark industrial desktop app for laying out a control cabinet and defining every device a PLC will supervise. It is built for Warren Williams at ERMCO.

## Where this lives on Warren's PC

Keep Cabinet Studio in its own folder. Do not mix it with SpartenRobotics.

```
C:\Users\Warren.Williams\OneDrive - ERMCO\Desktop\CabinetStudio\
    project\    source, docs, library, and program templates (this repository)
    builds\     packaged exe later
    saves\      user cabinet JSON (*.cabinet.json)
```

Copy this repository into `project\`. Copy the `builds` placeholder with it, or create that empty folder beside `project`. Leave `saves` for cabinets the app writes.

Open and Save use `saves` automatically when the app is launched from `CabinetStudio\project`. If that tree is not present, they use a `saves` folder next to the source. Copy those JSON files into `CabinetStudio\saves` when you want them on the Desktop. Set `CABINET_STUDIO_HOME` to the `CabinetStudio` folder if you need to point at it explicitly.

Pick a layout, drop in PLCs, HMIs, drives, motors, sensors, valves, lights, safety devices, and network gear, and answer the questions for that device class. A tile stays flagged until the required fields are filled: tag, description, landings, wire numbers, and a PLC I/O placeholder, plus the ratings that belong to that class.

Live PLC writes, EPLAN or AutoCAD drawings, and microphone capture are out of scope. Program stubs for Allen-Bradley, Siemens, and Modbus TCP are cut-and-paste text only.

## Run

Python 3.11 or newer. On Linux, install Tk if it is not already there:

```bash
sudo apt install python3-tk
```

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m cabinet_studio
```

`python app.py` from this folder starts the same window.

The splash is a child window of the main app. Set `CABINET_STUDIO_NO_SPLASH=1` to skip it.

Cabinets save as `.cabinet.json` in the `saves` folder described above. The file dialog opens there.

## What you can do

- Start from a blank panel, a compact machine station, a small motor cabinet, or a process skid.
- Add a starter part from Allen-Bradley, Siemens, or a generic Modbus-capable device.
- Define any device the PLC supervises, not only motors. The wizard changes questions by class: sensor (type, signal, range, wiring), valve (size, solenoid voltage, ports), light (color, voltage), PLC (catalog, IP, slots), and the same treatment for HMIs, drives, contactors, e-stops, switches, power supplies, solenoids, safety relays, transmitters, I/O modules, and pushbuttons. Tag, description, landings, wire numbers, and a PLC I/O placeholder are always asked.
- Drag tiles on the elevation. Double-click a tile, or use the inspector, to keep answering.
- Save and reopen the cabinet, including positions and every answer.
- Open **Program stubs** and copy a Logix, SCL, or Modbus TCP starting point.

## Guide build

**Guide build** on the left rail interviews the job first: duty, supply and control voltage, environment, enclosure, grounding, SCCR, disconnect, branch protection, power versus control separation, and field-wiring terminals. It then suggests a layout and shop-stock parts. **AI suggest** does the same for the selected device, or for the next class that is not on the panel yet.

Suggestions cover the catalog part, terminal landings, wire number, and wire color. They show up as suggestions. Every field stays editable. **Accept suggestion** restores the suggested values. **Mark as special (nonstandard)** keeps the device out of the shop memory.

Accepted choices are written to `saves/standards_profile.json` (wire colors, the next wire number, and the preferred catalog id for that class). The next suggestion prefers that memory. A special device does not change it.

## UL 508A review

**UL 508A review** opens an advisory checklist for the current cabinet. The standard is UL 508A, industrial control panels. Findings use check ids such as `UL508A-DISC-01` and a status of pass, warn, or missing. The rules are heuristics: disconnect and branch-circuit notes, power and control separation, wire-color consistency, grounding, enclosure and environment, an SCCR documentation field, motor overload data, and field-wiring terminal identification.

This is a design aid. It is not a certified UL listing and it is not a substitute for a qualified engineer or a formal UL evaluation. The same sentence is on the interview, the wizard, and the review window.

## Tests

```bash
pytest
```

Library loading and project save/load do not need a display. The window smoke test runs when `DISPLAY` is set.

## Layout of the code

See [cabinet_studio/docs/ARCHITECTURE.md](cabinet_studio/docs/ARCHITECTURE.md). The starter parts live in [cabinet_studio/library](cabinet_studio/library/README.md).
