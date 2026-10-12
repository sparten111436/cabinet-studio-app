# Program stubs

Cut-and-paste starting points for a controller program. Cabinet Studio
does not download them and does not open a connection.

Fill the addresses from the PLC I/O fields on each device before use.

| Folder | Platform |
| --- | --- |
| `allen_bradley/` | Logix structured text |
| `siemens/` | TIA Portal SCL |
| `modbus_tcp/` | Modbus TCP register map (no socket) |

Live EtherNet/IP, S7, and Modbus drivers live under
`cabinet_studio/services/drivers/` with `allow_live = False`.
