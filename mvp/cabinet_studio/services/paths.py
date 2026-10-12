"""Where Cabinet Studio lives on disk.

Warren's tree is separate from SpartenRobotics:

    C:\\Users\\Warren.Williams\\OneDrive - ERMCO\\Desktop\\CabinetStudio\\
        project\\   this source
        builds\\    packaged exe later
        saves\\     user cabinet JSON

When this checkout is the ``project`` folder inside a ``CabinetStudio``
directory, saves and builds use the sibling folders. Otherwise they sit
next to the source so they can be copied into that tree.

A packaged onedir under ``CabinetStudio\\builds\\CabinetStudio`` also
contains a folder named CabinetStudio. Prefer the outermost match so
Open/Save land in the shared outer ``saves`` folder, not one next to
the exe.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

WINDOWS_HOME = Path(r"C:\Users\Warren.Williams\OneDrive - ERMCO\Desktop\CabinetStudio")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def cabinet_home(origin: Path | None = None) -> Path | None:
    """Return the outermost CabinetStudio folder, or None when this is a plain checkout."""
    configured = os.environ.get("CABINET_STUDIO_HOME")
    if configured:
        return Path(configured)
    start = (origin or repo_root()).resolve()
    found: Path | None = None
    for candidate in (start, *start.parents):
        if candidate.name.lower() == "cabinetstudio":
            found = candidate
    if found is not None:
        return found
    if WINDOWS_HOME.is_dir():
        return WINDOWS_HOME
    return None


def user_documents_home() -> Path:
    """Per-user fallback: ``%USERPROFILE%\\Documents\\Cabinet Studio``."""
    return Path(os.environ.get("USERPROFILE") or Path.home()) / "Documents" / "Cabinet Studio"


def _shared_install(home: Path | None) -> bool:
    """A frozen exe outside ``<home>\\builds`` is a tester install, not Warren's tree."""
    if not getattr(sys, "frozen", False) or os.environ.get("CABINET_STUDIO_HOME"):
        return False
    if home is None:
        return True
    exe = Path(sys.executable).resolve()
    builds = (home / "builds").resolve()
    return builds != exe and builds not in exe.parents


def _writable(path: Path) -> bool:
    if "program files" in str(path).lower():
        return False
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".cs_write_probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _slot(name: str, origin: Path | None = None) -> Path:
    start = (origin or repo_root()).resolve()
    home = cabinet_home(start if origin is not None else None)
    if origin is None and _shared_install(home):
        path = user_documents_home() / name
    elif home is not None:
        path = home / name
    elif origin is not None:
        path = start / name
    else:
        path = repo_root() / name
    if not _writable(path):
        path = user_documents_home() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def saves_directory(origin: Path | None = None) -> Path:
    """Folder for ``*.cabinet.json`` user projects."""
    return _slot("saves", origin)


def builds_directory(origin: Path | None = None) -> Path:
    """Folder reserved for a later packaged executable."""
    return _slot("builds", origin)


def standards_profile_path(origin: Path | None = None) -> Path:
    """Shop memory of accepted parts, colors, and wire numbers."""
    return saves_directory(origin) / "standards_profile.json"
