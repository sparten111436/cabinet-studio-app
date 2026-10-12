"""Siemens S7 driver stub. Port 102 is documented only."""

from __future__ import annotations

from cabinet_studio.services.drivers.base import DriverStub


class S7Driver(DriverStub):
    protocol = "S7"
    default_port = 102
    allow_live = False
