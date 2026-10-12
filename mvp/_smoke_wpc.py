from pathlib import Path
import re, json
from cabinet_studio.services.project_store import load_project
from cabinet_studio.services.library_loader import load_library
from cabinet_studio.services.drawings import (
    build_sheets, render_svg, write_drawings, _rung_is_stub, box_hover_detail,
    CALLOUT_AFTER_SYMBOL, _ladder_trunk_x, LABEL_LINE_GAP,
)
from cabinet_studio.services.programming import simulation_rung_tags

cab = Path(r"C:\Users\spart\OneDrive\Desktop\CabinetStudio\saves\weld-place-cell.cabinet.json")
proj = load_project(cab)
lib = load_library()
sheets = build_sheets(proj, lib)
checks = []

# Program R2
r2 = proj.program["rungs"][1]
ok = not any(c["tag"]=="Pause_Active" for c in r2["series"])
checks.append(("R2 no Pause in seal-in", ok, r2["series"]))

sh8 = next(s for s in sheets if s.number==8 and s.kind=="control")
sh9 = next(s for s in sheets if s.number==9 and s.kind=="control")
sh7 = next(s for s in sheets if s.number==7 and s.kind=="control")
sh6 = next(s for s in sheets if s.number==6 and s.kind=="power")
checks.append(("SH8 no stubs", not any(_rung_is_stub(b, proj) for b in sh8.boxes), [b.tag for b in sh8.boxes]))
checks.append(("SH9 sensors on rails", not any(_rung_is_stub(b, proj) for b in sh9.boxes if b.tag in {"Arm_Deployed","Light_Curtain"}), None))

svg8 = render_svg(sh8, proj)
svg9 = render_svg(sh9, proj)
svg7 = render_svg(sh7, proj)
svg6 = render_svg(sh6, proj)
checks.append(("SH8 +24/0V rails", 'data-wire="+24V"' in svg8 and 'data-wire="0V"' in svg8, None))
checks.append(("W109 From-To", bool(re.search(r'wire-refs" data-tag="HS_STOP"', svg8)) and "W109" in svg8, None))
checks.append(("W114 From-To", bool(re.search(r'wire-refs" data-tag="Welder_Relay"', svg9)) and "W114" in svg9, None))
checks.append(("W107 From-To", bool(re.search(r'wire-refs" data-tag="SR1"', svg7)) and "W107" in svg7, None))
checks.append(("DO1 glyph DO", bool(re.search(r'data-tag="DO1".*?>DO</text>', svg7, re.S)), None))
checks.append(("W102->DISC", "W102" in svg6 and "DISC" in svg6 and "not identified" not in re.search(r'wire-refs" data-tag="PSU1">(.*?)</g>', svg6, re.S).group(1).split("PE")[0], None))

# Hover popup content
place = next(b for b in sh9.boxes if b.tag == "Place_Relay")
tip = box_hover_detail(place)
checks.append(("hover has type/tag", "Place_Relay" in tip and "Type:" in tip, tip[:80]))
checks.append(("hover has callout/io", "Callout:" in tip and "I/O:" in tip, None))
checks.append(("hover has from-to", "FROM" in tip and "W113" in tip, tip.splitlines()[-1] if tip else None))

# Callout left of trunk
for box in sh9.boxes:
    trunk = _ladder_trunk_x(box)
    callout_x = box.x + box.w + CALLOUT_AFTER_SYMBOL
    checks.append((f"callout clear of trunk {box.tag}", callout_x + 8 < trunk, (callout_x, trunk)))

# Sim pulse tags
active, pulse = simulation_rung_tags({"series":[{"tag":"HS_START","normally_closed":False}],"parallel":[],"coil_tag":"Welder_Relay"})
checks.append(("sim pulses Welder_Relay", "Welder_Relay" in pulse and "Welder_Relay" in active, sorted(pulse)))
active2, pulse2 = simulation_rung_tags({"series":[{"tag":"Arm_Deployed","normally_closed":False}],"parallel":[],"coil_tag":"Place_Relay"})
checks.append(("sim pulses Place_Relay", "Place_Relay" in pulse2, sorted(pulse2)))

# Viewer module imports
from cabinet_studio.ui.drawing_viewer import DrawingViewer, _SPARSE_SKIP
checks.append(("viewer sparse skips callout", "callout" in _SPARSE_SKIP and "wire-ref" in _SPARSE_SKIP, None))
from cabinet_studio.ui import programming_viewer as pv
checks.append(("sim methods present", hasattr(pv.ProgrammingViewer, "_sim_toggle_run") and hasattr(pv.ProgrammingViewer, "_sim_step"), None))

# Rewrite drawings to disk
disk = Path(r"C:\Users\spart\OneDrive\Desktop\CabinetStudio\saves\drawings\weld-place-cell")
written = write_drawings(proj, lib, disk)
checks.append(("wrote drawings", len(written) >= 6, len(written)))

for name, needle in [
    ("sheet-08-control.svg", 'data-wire="+24V"'),
    ("sheet-09-control.svg", "Arm_Deployed"),
    ("sheet-07-control.svg", ">DO</text>"),
    ("sheet-06-power.svg", "W102"),
]:
    p = disk / name
    if not p.exists():
        p = next(disk.glob(f"*{name}"), None)
    text = p.read_text(encoding="utf-8") if p else ""
    checks.append((f"disk {name}", needle in text, str(p)))

exe = Path(r"C:\Users\spart\OneDrive\Desktop\CabinetStudio\builds\CabinetStudio\CabinetStudio.exe")
zipf = Path(r"C:\Users\spart\OneDrive\Desktop\CabinetStudio\builds\CabinetStudio-windows.zip")
checks.append(("exe present", exe.exists() and exe.stat().st_size > 1_000_000, exe.stat().st_size if exe.exists() else 0))
checks.append(("zip present", zipf.exists() and zipf.stat().st_size > 1_000_000, zipf.stat().st_size if zipf.exists() else 0))

failed = 0
for name, ok, detail in checks:
    status = "PASS" if ok else "FAIL"
    if not ok: failed += 1
    print(f"{status}: {name} :: {detail}")
print("SMOKE", "OK" if failed==0 else f"FAILED {failed}")
raise SystemExit(failed)
