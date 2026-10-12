"""Modbus TCP driver stub. Port 502 is documented only."""

from __future__ import annotations

from cabinet_studio.services.drivers.base import DriverStub


class ModbusTcpDriver(DriverStub):
    protocol = "Modbus TCP"
    default_port = 502
    allow_live = False
