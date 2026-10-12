"""Save and build folders follow Warren's CabinetStudio tree."""

from pathlib import Path

from cabinet_studio.services.paths import WINDOWS_HOME, builds_directory, cabinet_home, saves_directory


def test_plain_checkout_keeps_saves_next_to_the_source(tmp_path):
    checkout = tmp_path / "cabinet-studio"
    checkout.mkdir()
    assert cabinet_home(checkout) is None
    assert saves_directory(checkout) == checkout / "saves"
    assert builds_directory(checkout) == checkout / "builds"
    assert (checkout / "saves").is_dir()


def test_project_folder_uses_sibling_saves_and_builds(tmp_path):
    home = tmp_path / "CabinetStudio"
    project = home / "project"
    project.mkdir(parents=True)
    assert cabinet_home(project) == home
    assert saves_directory(project) == home / "saves"
    assert builds_directory(project) == home / "builds"


def test_home_override_wins(tmp_path, monkeypatch):
    home = tmp_path / "CabinetStudio"
    monkeypatch.setenv("CABINET_STUDIO_HOME", str(home))
    other = tmp_path / "somewhere-else"
    other.mkdir()
    assert cabinet_home(other) == home
    assert saves_directory(other) == home / "saves"


def test_windows_path_is_the_documented_desktop_folder():
    assert WINDOWS_HOME == Path(r"C:\Users\Warren.Williams\OneDrive - ERMCO\Desktop\CabinetStudio")
