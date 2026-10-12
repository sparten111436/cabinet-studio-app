"""Cabinet Studio — cut/paste Modbus TCP map.

This file does not open a socket and does not import a Modbus library.
Copy the map into your own tool. The live driver stub in
cabinet_studio/services/drivers/modbus_tcp.py keeps allow_live = False.

Holding registers (PDU address, zero-based):
    0  status word
    1  command word
    2  speed setpoint, 0.01 Hz per count
"""

from __future__ import annotations

REGISTER_MAP = (
    {"name": "status", "address": 0, "count": 1, "type": "uint16"},
    {"name": "command", "address": 1, "count": 1, "type": "uint16"},
    {"name": "speed_setpoint", "address": 2, "count": 1, "type": "uint16", "scale": 0.01},
)


def build_read_holding_request(unit_id: int, address: int, count: int) -> dict:
    """Describe a read-holding-registers request. Nothing is transmitted."""
    if unit_id < 0 or unit_id > 255:
        raise ValueError("unit_id must be 0..255")
    if address < 0:
        raise ValueError("address must be >= 0")
    if count < 1 or count > 125:
        raise ValueError("count must be 1..125")
    return {
        "function": 3,
        "unit_id": unit_id,
        "address": address,
        "count": count,
        "note": "Template only. Cabinet Studio will not transmit this.",
    }


if __name__ == "__main__":
    print("Cabinet Studio cut/paste stub. This file does not open a socket.")
    print(build_read_holding_request(1, 0, 3))
