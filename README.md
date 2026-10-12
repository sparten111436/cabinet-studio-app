# Cabinet Studio

Desktop design aid for industrial control cabinets: panel layout, power and control schematics, wire schedules, and ladder logic (PLCopen XML). By Warren Williams.

## Run from source (Windows, Python 3.11+)

```powershell
cd mvp
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m cabinet_studio
```

`python app.py` from `mvp\` starts the same window. See `mvp\README.md` for details.

## Notices

- NOT A CERTIFIED UL 508A DRAWING. Design aid only.
- E-stop and safety functions must be hardwired or use rated safety relays (NFPA 79 / ISO 13849). The software is never the safety function.
