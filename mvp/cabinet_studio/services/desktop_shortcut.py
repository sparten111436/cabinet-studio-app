"""Create a Windows desktop shortcut that launches Cabinet Studio."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SHORTCUT_NAME = "Cabinet Studio.lnk"

def resolve_shortcut_icon(target: Path | None = None) -> str:
    """Return IconLocation for the Desktop shortcut (assets ico preferred)."""
    candidates: list[Path] = []
    # Repo root assets (Desktop/CabinetStudio/assets) — prefer over exe
    try:
        from cabinet_studio.services.paths import cabinet_home

        home = cabinet_home()
        if home is not None:
            candidates.append(home / "assets" / "cabinet_studio.ico")
            # cabinet_home may be the project root already
            if home.name.lower() != "cabinetstudio":
                candidates.append(home.parent / "assets" / "cabinet_studio.ico")
    except Exception:
        pass
    # Relative to this file: mvp/cabinet_studio/services → repo root parents[3]
    here = Path(__file__).resolve()
    if len(here.parents) >= 3:
        candidates.append(here.parents[2] / "assets" / "cabinet_studio.ico")  # mvp parent = root
    if len(here.parents) >= 4:
        candidates.append(here.parents[3] / "assets" / "cabinet_studio.ico")
    desktop = resolve_user_desktop()
    candidates.append(desktop / "CabinetStudio" / "assets" / "cabinet_studio.ico")
    if target is not None:
        t = Path(target)
        candidates.append(t.parent.parent.parent / "assets" / "cabinet_studio.ico")
        candidates.append(t)  # fall back to exe
    for path in candidates:
        if path.is_file() and path.suffix.lower() == ".ico":
            return f"{path},0"
    if target is not None:
        return f"{Path(target)},0"
    return ""



def desktop_shortcut_path(desktop: Path) -> Path:
    """Return the full path of the Cabinet Studio shortcut on ``desktop``."""
    return Path(desktop) / SHORTCUT_NAME


def resolve_user_desktop() -> Path:
    """Locate the user's real Desktop, preferring OneDrive Desktop when present."""
    from cabinet_studio.services.paths import cabinet_home

    home = cabinet_home()
    if home is not None and home.parent.name.lower() == "desktop" and home.parent.is_dir():
        return home.parent

    candidates: list[Path] = []
    one_drive = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
    if one_drive:
        candidates.append(Path(one_drive) / "Desktop")
    user = Path.home()
    candidates.append(user / "OneDrive" / "Desktop")
    candidates.append(user / "Desktop")
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return user / "Desktop"


def launch_target(
    *,
    frozen: bool | None = None,
    executable: Path | None = None,
    python_exe: Path | None = None,
    app_py: Path | None = None,
) -> tuple[Path, str, Path]:
    """Return ``(target, arguments, working_directory)`` for the running program.

    When frozen (PyInstaller), target ``sys.executable`` with an empty argument
    list and the exe folder as the working directory. Otherwise target the venv
    Python with ``app.py`` and use that script's folder as the working directory.
    """
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    executable = Path(executable or sys.executable)
    if frozen:
        return executable, "", executable.parent

    root = Path(__file__).resolve().parents[2]
    python_exe = Path(python_exe or sys.executable)
    app_py = Path(app_py or (root / "app.py"))
    return python_exe, str(app_py), app_py.parent


def create_desktop_shortcut(
    *,
    desktop: Path | None = None,
    target: Path | None = None,
    arguments: str | None = None,
    working_directory: Path | None = None,
    write: bool = True,
) -> Path:
    """Create ``Cabinet Studio.lnk`` on ``desktop`` and return its path.

    Pass ``desktop`` / ``target`` (and optional arguments / working directory)
    to pin locations without touching COM ? useful for tests. When ``write`` is
    False the path is returned without creating the file.
    """
    desktop_dir = Path(desktop) if desktop is not None else resolve_user_desktop()
    link = desktop_shortcut_path(desktop_dir)
    if target is None:
        resolved_target, resolved_args, resolved_cwd = launch_target()
        target = resolved_target
        if arguments is None:
            arguments = resolved_args
        if working_directory is None:
            working_directory = resolved_cwd
    else:
        target = Path(target)
        if arguments is None:
            arguments = ""
        if working_directory is None:
            working_directory = target.parent

    if not write:
        return link

    desktop_dir.mkdir(parents=True, exist_ok=True)
    _write_shortcut(
        link,
        target=Path(target),
        arguments=arguments or "",
        working_directory=Path(working_directory),
    )
    return link


def _write_shortcut(link: Path, *, target: Path, arguments: str, working_directory: Path) -> None:
    if _try_win32com(link, target=target, arguments=arguments, working_directory=working_directory):
        return
    _write_via_powershell(link, target=target, arguments=arguments, working_directory=working_directory)


def _try_win32com(link: Path, *, target: Path, arguments: str, working_directory: Path) -> bool:
    try:
        import win32com.client  # type: ignore
    except ImportError:
        return False
    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortcut(str(link))
    shortcut.TargetPath = str(target)
    shortcut.Arguments = arguments
    shortcut.WorkingDirectory = str(working_directory)
    shortcut.IconLocation = resolve_shortcut_icon(target)
    shortcut.Save()
    return True


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _write_via_powershell(
    link: Path, *, target: Path, arguments: str, working_directory: Path
) -> None:
    script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut({_ps_quote(str(link))}); "
        f"$s.TargetPath = {_ps_quote(str(target))}; "
        f"$s.Arguments = {_ps_quote(arguments)}; "
        f"$s.WorkingDirectory = {_ps_quote(str(working_directory))}; "
        f"$s.IconLocation = {_ps_quote(resolve_shortcut_icon(target))}; "
        "$s.Save()"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0 or not link.is_file():
        detail = (completed.stderr or completed.stdout or "unknown error").strip()
        raise OSError(detail or f"PowerShell exited {completed.returncode}")
