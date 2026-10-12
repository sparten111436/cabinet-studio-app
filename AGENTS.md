---
description: Cabinet Studio standing rules (Warren Williams)
alwaysApply: true
---
# Cabinet Studio rules

## Cost (Warren's standing rule)
- Always use the cheapest way to get the job done. Warren pays for every token.
- Read only the lines you need (grep first), run only the relevant tests, skip screenshots unless asked, keep updates short.
- Don't start subagents, big rewrites or long exploration without asking first. If a job needs more power or another approach, ask.

## Layout
- Live app source: `mvp\` (v0.3.18 installed). The live exe is `builds\CabinetStudio\CabinetStudio.exe`, launched from the Desktop shortcut `Cabinet Studio.lnk`, with icon `assets\cabinet_studio.ico`.
- Unfinished v0.3.19 source: `cursor-handoff\mvp-0.3.19-wip\`. Finish it there first, then merge into `mvp\`.
- Project saves: `CabinetStudio\saves\`, the outermost folder.

## Never break
- PROTECTED files: never overwrite or rewrite these wholesale. Make only small, surgical edits, after a backup.
  - `cabinet_studio/ui/main_window.py`
  - `cabinet_studio/ui/library_rail.py` (sticky OUTPUT: Drawings / View drawings / Programming)
  - `cabinet_studio/services/paths.py` (resolves the outer `saves\`)
  - `ui/ai_build.py`, `services/ai_build.py`, `desktop_shortcut.py`
- Before any change, make a timestamped backup to `backups\`. Never delete old builds; rename them aside.
- Every printed output carries this exact footer, once per sheet: `NOT A CERTIFIED UL 508A DRAWING. Design aid only.`
- Ladder outputs keep the safety note: E-stop and safety functions must be hardwired or use rated safety relays (NFPA 79 / ISO 13849). The software is never the safety function.

## Drawings (enforced in drawings.py engine-wide, never patched per sample)
- True shop-print schematics: continuous rails, rail to protection to device to return, separate PE bar, and +24V/0V control ladders whose I/O matches the cabinet JSON.
- Every conductor has a wire #, FROM–TO, color and gauge. Those labels live in the hover popup; only coil descriptions sit on the sheet. No false junctions.
- Panel layout: real device outline footprints on a scaled UL 508A backing plate. Hoffman is the enclosure default, with Saginaw and Hammond as options. 11x17 sheets. Text stays inside the sheet, wrapping long labels.
- Order: Panel layout, then Power schematic, then Control schematic, then Wire Schedule. Ladder logic is a SEPARATE document.

## Ladder import safety (lessons from v0.3.13–0.3.18)
- The wiring in the file is the source of truth. Doc notes and hints never supply logic; they only label.
- Use an allow-list of modelled LD elements and attributes. Refuse the WHOLE file on anything unknown, any unresolved reference, or a missing or ambiguous rail. Never guess, never silently skip.
- Verify-and-refuse: compare the imported logic's truth table to the source and refuse on mismatch.

## Release gate (required before installing on the PC)
1. `pytest` passes, except the known failures: `test_library_load` relay questions, plus Windows-only `test_watch_pause_labels_csv` (fix it: blank lines in `ladder_tools.export_csv`, use newline=''), the research-note test, and the gaid2 print test.
2. `tests/test_programming_ui_gate.py` must click EVERY new button or UI action headlessly. Launch-only smoke tests are not enough.
3. IR to PLCopen XML to IR round-trip is exact, XSD-valid, and covered by fresh-seed fuzz, including deleted-object and attribute-mutation fuzz (0 unsafe imports reported as verified).
4. Bump `__version__`, back up, then freeze with PyInstaller onedir using `builds\CabinetStudio-0.3.18.spec` as the template (icon=cabinet_studio.ico, ico in datas, hiddenimports for the ladder, sim, PLCopen, tools, history, templates, programming and viewer modules). Repoint the shortcut.
