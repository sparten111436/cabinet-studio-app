from pathlib import Path
from cabinet_studio.services.project_store import load_project
from cabinet_studio.services.library_loader import load_library
from cabinet_studio.services.drawings import write_drawings, build_sheets, render_svg, box_hover_detail

lib = load_library()
root = Path(r"C:\Users\spart\OneDrive\Desktop\CabinetStudio\saves")
jobs = [
    ("weld-place-cell", root / "weld-place-cell.cabinet.json", root / "drawings" / "weld-place-cell"),
]
found = list(Path(r"C:\Users\spart\OneDrive\Desktop\CabinetStudio").rglob("sample-motor-cabinet.cabinet.json"))
print("sample candidates", found[:5])
if found:
    jobs.append(("sample-motor-cabinet", found[0], root / "drawings" / "sample-motor-cabinet"))

for name, cab, out in jobs:
    out.mkdir(parents=True, exist_ok=True)
    proj = load_project(cab)
    paths = write_drawings(proj, lib, out)
    sheets = build_sheets(proj, lib)
    control = [s for s in sheets if s.kind in {"power", "control"}]
    bad = 0
    coils = 0
    for s in control:
        svg = render_svg(s, proj)
        for cls in ("callout", "wire-ref", "wire-ref-header", "connector-label", "selected-connections"):
            if f'class="{cls}"' in svg:
                bad += 1
                print("BAD", name, s.number, cls)
        if "coil-desc" in svg:
            coils += 1
        for b in s.boxes[:1]:
            tip = box_hover_detail(b)
            assert b.tag in tip
    print(name, "wrote", len(paths), "svgs; control sheets", len(control), "coil sheets", coils, "bad", bad)
