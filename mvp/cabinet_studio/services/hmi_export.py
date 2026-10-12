"""Import-ready HMI files per maker: tag list, alarm list, screen spec (JSON) and screen pictures (SVG).

Honest scope: the maker's software imports the tags and alarms; screens are rebuilt there from the spec and
pictures. Nothing is downloaded into the HMI. Column layouts below use each maker's familiar column names but
are NOT confirmed against the maker's import format, so every tag file is labelled
"generic - map columns on import".
"""

from __future__ import annotations

import copy
import csv
import json
from pathlib import Path

from cabinet_studio.services.hmi_design import (
    OBJECT_KINDS,
    SAFETY_NOTE,
    HmiDesign,
    alarm_rows,
    design_to_dict,
    hmi_tag_rows,
    save_design,
)
from cabinet_studio.services.hmi_library import hmi_by_id, hmi_label

GENERIC = "generic - map columns on import"
FOOTER = "NOT A CERTIFIED UL 508A DRAWING. Design aid only."

# maker -> (software, header row, row builder). Builders get a merged hmi_tag_rows row.
_FORMATS = {
    "Allen-Bradley": ("FactoryTalk View ME (Tag Import and Export Wizard)",
                      ["Tag Type", "Tag Name", "Tag Description", "Read Only", "Data Source", "Address"],
                      lambda r: ["Analog" if r["type"] == "REAL" else "Digital", r["tag"], r["description"],
                                 "False" if r["access"] == "Read/Write" else "True", "Device",
                                 f"{{::[PLC]{r['tag']}}}"]),
    "Siemens": ("TIA Portal WinCC (HMI tags)",
                ["Name", "Connection", "PLC tag", "DataType", "Access Method", "Acquisition cycle", "Comment"],
                lambda r: [r["tag"], "HMI_Connection_1", r["tag"], "Real" if r["type"] == "REAL" else "Bool",
                           "Symbolic access", "100 ms", r["description"]]),
    "Omron": ("Omron NB-Designer / Sysmac Studio (NA)",
              ["Name", "Data Type", "Variable / Address", "Read/Write", "Comment"],
              lambda r: [r["tag"], r["type"], r["address"] or r["tag"],
                         "RW" if r["access"] == "Read/Write" else "R", r["description"]]),
}
_GENERIC_FORMAT = ("any HMI software", ["Tag Name", "Data Type", "Access", "PLC Address", "Description"],
                   lambda r: [r["tag"], r["type"], r["access"], r["address"], r["description"]])


def _slug(text: str) -> str:
    out = "".join(ch.lower() if ch.isalnum() else "-" for ch in text)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-") or "hmi"


def export_for_maker(design: HmiDesign, project, folder: Path | str | None = None) -> dict:
    """Write the files; returns {maker, software, folder, files, format}."""
    from cabinet_studio.services.drawings import default_drawings_folder, render_svg
    from cabinet_studio.services.hmi_drawings import hmi_sheets

    entry = hmi_by_id(design.model_id)
    maker = entry["maker"] if entry else "Generic"
    software, header, build = _FORMATS.get(maker, _GENERIC_FORMAT)
    out = Path(folder) if folder else default_drawings_folder(project) / "hmi"
    out.mkdir(parents=True, exist_ok=True)
    base = f"{_slug(project.name)}_{_slug(maker)}"
    files: list[Path] = []

    tags_path = out / f"{base}_tags_generic.csv"
    with open(tags_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for row in hmi_tag_rows(design, project):
            writer.writerow(build(row))
    files.append(tags_path)

    alarms_path = out / f"{base}_alarms_generic.csv"
    with open(alarms_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Alarm ID", "Trigger Tag", "Trigger", "Message", "Priority", "Class"])
        for i, row in enumerate(alarm_rows(design, project), start=1):
            writer.writerow([i, row["tag"], f"{row['tag']} = 1", row["message"], row["priority"], row["class"]])
    files.append(alarms_path)

    spec = {
        "format": "cabinet-studio-hmi-screen-spec",
        "hmi": hmi_label(entry) if entry else design.model_id,
        "software": software,
        "how_to_use": "Rebuild each screen in the maker's software from this list and the SVG pictures. "
                      "Import the tag and alarm CSVs first (" + GENERIC + "). Nothing is downloaded into the HMI.",
        "safety_note": SAFETY_NOTE,
        "screens": [{"name": s.name, "objects": [
            {"kind": OBJECT_KINDS[o.kind]["name"], "label": o.label, "tags": o.tags, "grid": [o.x, o.y, o.w, o.h],
             "access": o.access or "-", "animation": o.anim or "none", "go_to": o.target}
            for o in s.objects]} for s in design.screens],
        "design": design_to_dict(design),
    }
    spec_path = out / f"{base}_screens.json"
    spec_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    files.append(spec_path)

    shadow = copy.copy(project)
    shadow.interview = dict(project.interview)
    save_design(shadow, design)
    for sheet in hmi_sheets(shadow):
        if sheet.kind == "hmi-layout":
            path = out / f"{base}_screen_{sheet.schedule_page:02d}_{_slug(sheet.title)[:40]}.svg"
            path.write_text(render_svg(sheet, shadow), encoding="utf-8")
            files.append(path)

    readme = out / f"{base}_README.txt"
    readme.write_text(
        f"HMI export for {maker} - {hmi_label(entry) if entry else design.model_id}\n"
        f"Software: {software}\n\n"
        f"1. Import {tags_path.name} as HMI tags. Column layout is {GENERIC}: the column names follow\n"
        f"   {maker} conventions but are not confirmed against its import format - check them in the import wizard.\n"
        f"2. Import {alarms_path.name} as alarms ({GENERIC}).\n"
        f"3. Rebuild each screen in the maker's software using {spec_path.name} and the SVG pictures.\n"
        "   Cabinet Studio does NOT download into the HMI and is not a live PLC connection.\n"
        "4. Tags starting HMI_ are HMI memory bits - add them to the PLC program.\n\n"
        f"{SAFETY_NOTE}\n{FOOTER}\n", encoding="utf-8")
    files.append(readme)
    return {"maker": maker, "software": software, "folder": out, "files": files, "format": GENERIC}
