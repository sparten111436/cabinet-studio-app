from pathlib import Path
from cabinet_studio.services.project_store import load_project
from cabinet_studio.services.library_loader import load_library
from cabinet_studio.services.drawings import write_drawings, build_sheets, _rung_is_stub, _disconnect_load_wires

cab = Path(r"C:\Users\spart\OneDrive\Desktop\CabinetStudio\saves\weld-place-cell.cabinet.json")
out = Path(r"C:\Users\spart\OneDrive\Desktop\CabinetStudio\saves\drawings\weld-place-cell")
out.mkdir(parents=True, exist_ok=True)
proj = load_project(cab)
lib = load_library()
print("DISC", _disconnect_load_wires(proj))
sheets = build_sheets(proj, lib)
for s in sheets:
    if s.number in (8, 9) and s.kind == "control":
        stubs = [b.tag for b in s.boxes if _rung_is_stub(b, proj)]
        print(f"SH{s.number} stubs={stubs} boxes={[b.tag for b in s.boxes]}")
write_drawings(proj, lib, out)
print("wrote", len(list(out.glob("*.svg"))), "svgs to", out)
# R2 check
r2 = proj.program["rungs"][1]
print("R2 series", r2["series"])
assert not any(c["tag"]=="Pause_Active" for c in r2["series"])
print("R2 OK")
