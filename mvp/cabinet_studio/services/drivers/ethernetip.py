"""EtherNet/IP (CIP) driver stub. Port 44818 is documented only."""

from __future__ import annotations

from cabinet_studio.services.drivers.base import DriverStub


class EthernetIpDriver(DriverStub):
    protocol = "EtherNet/IP"
    default_port = 44818
    allow_live = False
