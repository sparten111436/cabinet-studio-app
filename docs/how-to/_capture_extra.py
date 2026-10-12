from __future__ import annotations
import os, sys, time
from pathlib import Path
os.environ["CABINET_STUDIO_NO_SPLASH"] = "1"
ROOT = Path(r"C:\Users\spart\OneDrive\Desktop\CabinetStudio\mvp")
sys.path.insert(0, str(ROOT))
OUT = Path(r"C:\Users\spart\OneDrive\Desktop\CabinetStudio\docs\how-to\images")
SAMPLE = Path(r"C:\Users\spart\OneDrive\Desktop\CabinetStudio\saves\sample-motor-cabinet.cabinet.json")
from PIL import ImageGrab

def grab(widget, name, settle=0.6):
    widget.update_idletasks(); widget.update(); time.sleep(settle)
    try: widget.lift(); widget.focus_force()
    except Exception: pass
    widget.update(); time.sleep(0.2)
    x,y = widget.winfo_rootx(), widget.winfo_rooty()
    w,h = max(widget.winfo_width(),100), max(widget.winfo_height(),100)
    img = ImageGrab.grab(bbox=(max(0,x-4), max(0,y-4), x+w+4, y+h+4), all_screens=True)
    path = OUT/name; img.save(path); print(f"saved {name} {img.size} {path.stat().st_size}")

from cabinet_studio.services.library_loader import load_library
from cabinet_studio.ui.main_window import CabinetStudioApp

app = CabinetStudioApp(load_library())
app.geometry("1400x860+60+40")
app.update(); time.sleep(0.7)
app.open_path(SAMPLE); app.update(); time.sleep(0.4)

# Crop left rail only at different scroll positions
rail = app.rail
try:
    canvas = rail.body._parent_canvas
    # Find scroll that shows Programming / Desktop shortcut / UL
    for frac, name in [(0.0,"05b-rail-project.png"), (0.12,"05c-rail-devices-output.png"), (0.22,"05d-rail-programming-shortcut.png")]:
        canvas.yview_moveto(frac)
        app.update(); time.sleep(0.35)
        # capture just the rail frame
        grab(rail, name, 0.4)
except Exception as e:
    print("scroll fail", e)

# Open a motor/contactor and walk to wiring step
target = None
for item in app.project.items:
    f = item.fields or {}
    if f.get("wire_numbers") or f.get("terminal_landings"):
        if item.type_id in ("contactor","motor","vfd","pushbutton","sensor") or "wire" in str(f).lower():
            target = item
            break
if target is None:
    target = next((i for i in app.project.items if (i.fields or {}).get("wire_numbers")), app.project.items[0])
app.select_item(target.id)
app.edit_item(target.id)
app.update(); time.sleep(0.8)
wiz = app._wizard_window
if wiz and wiz.winfo_exists():
    # Walk steps looking for wire / landing labels
    for i in range(8):
        try:
            # inspect current step title
            title = ""
            for child in wiz.winfo_children():
                pass
            step_text = getattr(wiz, "_step_label", None)
            # try reading heading from UI
            grab(wiz, f"08c-wizard-step-{i}.png", 0.35)
            # Check if wiring-related fields present in current step fields
            shown = ""
            if hasattr(wiz, "_entries"):
                shown = ",".join(getattr(wiz, "_entries", {}).keys())
            labels = []
            def walk(w):
                try:
                    t = w.cget("text")
                    if t: labels.append(str(t))
                except Exception:
                    pass
                for c in w.winfo_children():
                    walk(c)
            walk(wiz)
            joined = " | ".join(labels)
            print("step", i, "labels:", joined[:200])
            if any(k in joined.lower() for k in ("wire number", "terminal", "landing", "wire color")):
                grab(wiz, "08-wiring-landings.png", 0.5)
                break
            if hasattr(wiz, "_next"):
                wiz._next()
                app.update(); time.sleep(0.3)
            else:
                break
        except Exception as exc:
            print("step err", exc)
            break
    try: wiz.close()
    except Exception: pass

app.after(200, app.destroy)
app.mainloop()
print("extra done")
