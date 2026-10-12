from __future__ import annotations
import os, sys, time
from pathlib import Path
os.environ["CABINET_STUDIO_NO_SPLASH"] = "1"
ROOT = Path(r"C:\Users\spart\OneDrive\Desktop\CabinetStudio\mvp")
sys.path.insert(0, str(ROOT))
OUT = Path(r"C:\Users\spart\OneDrive\Desktop\CabinetStudio\docs\how-to\images")
SAMPLE = Path(r"C:\Users\spart\OneDrive\Desktop\CabinetStudio\saves\sample-motor-cabinet.cabinet.json")
from PIL import ImageGrab
from cabinet_studio.services.library_loader import load_library
from cabinet_studio.ui.main_window import CabinetStudioApp

app = CabinetStudioApp(load_library())
app.geometry("1400x860+60+40"); app.update(); time.sleep(0.5)
app.open_path(SAMPLE); app.update(); time.sleep(0.3)

def find_labels(widget, needle, found):
    try:
        t = widget.cget("text")
        if t and needle.lower() in str(t).lower():
            found.append((str(t), widget.winfo_rootx(), widget.winfo_rooty(), widget.winfo_width(), widget.winfo_height(), widget.winfo_viewable()))
    except Exception:
        pass
    for c in widget.winfo_children():
        find_labels(c, needle, found)

found = []
find_labels(app.rail, "Programming", found)
find_labels(app.rail, "Desktop shortcut", found)
find_labels(app.rail, "UL 508A", found)
print("FOUND:", found)

# Scroll until Programming is viewable in body
canvas = app.rail.body._parent_canvas
for frac in [i/100 for i in range(0, 60, 2)]:
    canvas.yview_moveto(frac)
    app.update()
    found = []
    find_labels(app.rail, "Programming", found)
    if found and found[0][5]:
        # check if within rail visible area
        ry = app.rail.winfo_rooty(); rh = app.rail.winfo_height()
        py = found[0][2]
        if ry <= py <= ry+rh-40:
            print("visible at frac", frac, found[0])
            time.sleep(0.3)
            x,y = app.rail.winfo_rootx(), app.rail.winfo_rooty()
            w,h = app.rail.winfo_width(), app.rail.winfo_height()
            img = ImageGrab.grab(bbox=(x,y,x+w,y+h), all_screens=True)
            img.save(OUT/"05-rail-with-programming.png")
            print("saved", img.size, (OUT/"05-rail-with-programming.png").stat().st_size)
            break
else:
    print("never found viewable programming in rail bounds")
    # force capture at frac 0.08 anyway
    canvas.yview_moveto(0.08); app.update(); time.sleep(0.3)
    x,y = app.rail.winfo_rootx(), app.rail.winfo_rooty()
    w,h = app.rail.winfo_width(), app.rail.winfo_height()
    ImageGrab.grab(bbox=(x,y,x+w,y+h), all_screens=True).save(OUT/"05-rail-with-programming.png")

app.after(200, app.destroy); app.mainloop()
