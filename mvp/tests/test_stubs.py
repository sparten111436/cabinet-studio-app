"""Future integrations stay inert: no live I/O, no microphone, no catalog download."""

from pathlib import Path

import pytest

from cabinet_studio.programs.modbus_tcp import holding_register_poll
from cabinet_studio.services.catalog_feed import CatalogFeed
from cabinet_studio.services.compatibility_watch import CompatibilityWatchlist
from cabinet_studio.services.drivers import ALLOW_LIVE, EthernetIpDriver, ModbusTcpDriver, S7Driver
from cabinet_studio.services.drivers.base import LiveDriverDisabled
from cabinet_studio.services.voice_capture import VoiceCapture

PROGRAMS = Path(__file__).resolve().parent.parent / "cabinet_studio" / "programs"


def test_live_drivers_are_off():
    assert ALLOW_LIVE is False
    for driver in (EthernetIpDriver(), S7Driver(), ModbusTcpDriver()):
        assert driver.allow_live is False
        with pytest.raises(LiveDriverDisabled):
            driver.connect("10.0.0.5")
        with pytest.raises(LiveDriverDisabled):
            driver.read("I0.0")
        with pytest.raises(LiveDriverDisabled):
            driver.write("Q0.0", True)


def test_voice_catalog_and_watchlist_are_stubs():
    assert VoiceCapture.enabled is False
    with pytest.raises(NotImplementedError):
        VoiceCapture().capture()
    assert CatalogFeed.enabled is False
    with pytest.raises(NotImplementedError):
        CatalogFeed().fetch_updates()
    assert CompatibilityWatchlist().evaluate([{"tag": "PLC1"}]) == []


def test_program_stubs_are_cut_and_paste_only():
    stub = holding_register_poll.build_read_holding_request(1, 0, 3)
    assert stub["function"] == 3
    assert stub["note"].startswith("Template only")
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in PROGRAMS.rglob("*")
        if path.is_file() and path.suffix.lower() in {".py", ".st", ".scl", ".md"}
    )
    assert "import socket" not in text
    assert "pymodbus" not in text
    assert (PROGRAMS / "allen_bradley" / "motor_run_permissive.st").is_file()
    assert (PROGRAMS / "siemens" / "motor_run_permissive.scl").is_file()
