"""Controller drivers. Live sessions stay off in this build.

EtherNet/IP, S7, and Modbus TCP are named here so a later release can
add a session behind the same classes. ``allow_live`` is False, and
there is no socket implementation to turn on by accident.
"""

from cabinet_studio.services.drivers.base import DriverStub, LiveDriverDisabled
from cabinet_studio.services.drivers.ethernetip import EthernetIpDriver
from cabinet_studio.services.drivers.modbus_tcp import ModbusTcpDriver
from cabinet_studio.services.drivers.s7 import S7Driver

ALLOW_LIVE = False

__all__ = [
    "ALLOW_LIVE",
    "DriverStub",
    "EthernetIpDriver",
    "LiveDriverDisabled",
    "ModbusTcpDriver",
    "S7Driver",
]
