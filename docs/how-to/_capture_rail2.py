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
canvas = app.rail.body._parent_canvas
# small scroll steps until Programming button would be in view: scroll by pixels
for units in range(0, 20):
    canvas.yview_scroll(1, "units")
    app.update(); time.sleep(0.05)
# capture rail
rail = app.rail
rail.update(); time.sleep(0.4)
x,y = rail.winfo_rootx(), rail.winfo_rooty()
w,h = rail.winfo_width(), rail.winfo_height()
img = ImageGrab.grab(bbox=(x, y, x+w, y+h), all_screens=True)
img.save(OUT/"05e-rail-scrolled-output.png")
print("saved 05e", img.size, (OUT/"05e-rail-scrolled-output.png").stat().st_size)
# also full window at this scroll
app.lift(); app.update(); time.sleep(0.2)
x,y = app.winfo_rootx(), app.winfo_rooty()
w,h = app.winfo_width(), app.winfo_height()
img2 = ImageGrab.grab(bbox=(max(0,x-8), max(0,y-32), x+w+8, y+h+8), all_screens=True)
img2.save(OUT/"06-left-rail-output.png")
print("saved 06", img2.size)
app.after(200, app.destroy); app.mainloop()
