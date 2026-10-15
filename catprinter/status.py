from dataclasses import dataclass
from typing import Optional

# Notifications that carry the printer's state.
CMD_DEV_STATE = 0xa3
CMD_BATTERY = 0xba


@dataclass
class PrinterStatus:
    battery: Optional[int] = None
    no_paper: bool = False
    cover_open: bool = False
    overheat: bool = False
    low_battery: bool = False
    charging: bool = False


def parse_notification(data, status):
    '''Updates status from a printer notification. Notifications look like
    51 78 <cmd> 01 <len lo> <len hi> <payload...> <crc> ff.

    The state flags match the ones the official iPrint app checks. The state
    answer of an SC03h looks like 51 78 a3 01 03 00 <flags> <battery %> <temp> <crc> ff.
    '''
    if len(data) < 8 or data[0:2] != b"\x51\x78":
        return
    cmd = data[2]
    length = data[4] | data[5] << 8
    payload = data[6:6 + length]
    if not payload:
        return
    if cmd == CMD_DEV_STATE:
        flags = payload[0]
        status.no_paper = bool(flags & 0x01)
        status.cover_open = bool(flags & 0x02)
        status.overheat = bool(flags & 0x04)
        status.low_battery = bool(flags & 0x08)
        status.charging = bool(flags & 0x10)
        if len(payload) >= 2 and payload[1] <= 100:
            status.battery = payload[1]
    elif cmd == CMD_BATTERY and payload[0] <= 100:
        status.battery = payload[0]
