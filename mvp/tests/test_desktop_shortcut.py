"""Desktop shortcut path logic without requiring COM."""

from pathlib import Path

from cabinet_studio.services.desktop_shortcut import (
    SHORTCUT_NAME,
    create_desktop_shortcut,
    desktop_shortcut_path,
    launch_target,
)


def test_desktop_shortcut_path_joins_name(tmp_path):
    desktop = tmp_path / "Desktop"
    assert desktop_shortcut_path(desktop) == desktop / "Cabinet Studio.lnk"
    assert desktop_shortcut_path(desktop).name == SHORTCUT_NAME


def test_create_desktop_shortcut_returns_expected_path_for_fake_desktop_and_exe(tmp_path):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    exe = tmp_path / "builds" / "CabinetStudio" / "CabinetStudio.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    path = create_desktop_shortcut(
        desktop=desktop,
        target=exe,
        arguments="",
        working_directory=exe.parent,
        write=False,
    )
    assert path == desktop / "Cabinet Studio.lnk"
    assert path == desktop_shortcut_path(desktop)
    assert not path.exists()


def test_launch_target_frozen_uses_exe_folder(tmp_path):
    exe = tmp_path / "CabinetStudio" / "CabinetStudio.exe"
    exe.parent.mkdir(parents=True)
    target, arguments, cwd = launch_target(frozen=True, executable=exe)
    assert target == exe
    assert arguments == ""
    assert cwd == exe.parent


def test_launch_target_source_uses_python_and_app(tmp_path):
    python = tmp_path / ".venv" / "Scripts" / "python.exe"
    app = tmp_path / "app.py"
    python.parent.mkdir(parents=True)
    app.write_text("pass\n", encoding="utf-8")
    target, arguments, cwd = launch_target(
        frozen=False,
        executable=python,
        python_exe=python,
        app_py=app,
    )
    assert target == python
    assert arguments == str(app)
    assert cwd == app.parent
