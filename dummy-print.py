import asyncio
import contextlib
from typing import Optional
import uuid
from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from catprinter import logger

POSSIBLE_SERVICE_UUIDS = [
    "0000ae30-0000-1000-8000-00805f9b34fb",
    "0000af30-0000-1000-8000-00805f9b34fb",
]

TX_CHARACTERISTIC_UUID = "0000ae01-0000-1000-8000-00805f9b34fb"
RX_CHARACTERISTIC_UUID = "0000ae02-0000-1000-8000-00805f9b34fb"

PRINTER_READY_NOTIFICATION = b"\x51\x78\xae\x01\x01\x00\x00\x00\xff"

SCAN_TIMEOUT_S = 10
WAIT_AFTER_EACH_CHUNK_S = 0.2
WAIT_FOR_PRINTER_DONE_TIMEOUT = 60

# Scan and connect to the printer
async def scan(name: Optional[str], timeout: int):
    autodiscover = not name
    if autodiscover:
        logger.info("⏳ Trying to auto-discover a printer...")
    else:
        logger.info(f"⏳ Looking for a BLE device named {name}...")
    # Filter function for devices
    def filter_fn(device: BLEDevice, adv_data):
        if autodiscover:
            return any(uuid in adv_data.service_uuids for uuid in POSSIBLE_SERVICE_UUIDS)
        else:
            return device.name == name

    device = await BleakScanner.find_device_by_filter(filter_fn, timeout=timeout)
    if device is None:
        raise RuntimeError("Unable to find printer, make sure it is turned on and in range")
    logger.info(f"✅ Found printer: {device}")
    return device

# Simulate a dummy print activity (ping)
async def run_dummy_print(device: Optional[str]):
    try:
        address = await scan(device, timeout=SCAN_TIMEOUT_S)
    except RuntimeError as e:
        logger.error(f"🛑 {e}")
        return
    logger.info(f"⏳ Connecting to {address}...")
    async with BleakClient(address) as client:
        logger.info(f"✅ Connected: {client.is_connected}; MTU: {client.mtu_size}")
        event = asyncio.Event()

        # Sending a dummy "ping" to the printer to keep it awake
        logger.info("⏳ Sending dummy signal to the printer...")
        await client.write_gatt_char(TX_CHARACTERISTIC_UUID, PRINTER_READY_NOTIFICATION)
        await asyncio.sleep(WAIT_AFTER_EACH_CHUNK_S)

        logger.info("✅ Printer activity simulated successfully. Exiting.")

# Run the dummy print to simulate the interaction with the printer
if __name__ == "__main__":
    asyncio.run(run_dummy_print(None)) 
