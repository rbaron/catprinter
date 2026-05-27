import asyncio
import contextlib
import uuid
from typing import Optional

from bleak import BleakClient, BleakScanner
from bleak.backends.scanner import AdvertisementData
from bleak.backends.device import BLEDevice
# In MacOS capture exception trying Linux library import and set a flag
try:
    from bleak.backends.bluezdbus.client import BleakClientBlueZDBus
except ImportError:
    BleakClientBlueZDBus = None
from catprinter import logger

# For some reason, bleak reports the 0xaf30 service on my macOS, while it reports
# 0xae30 (which I believe is correct) on my Raspberry Pi. This hacky workaround
# should cover both cases.

POSSIBLE_SERVICE_UUIDS = [
    "0000ae30-0000-1000-8000-00805f9b34fb",
    "0000af30-0000-1000-8000-00805f9b34fb",
]

TX_CHARACTERISTIC_UUID = "0000ae01-0000-1000-8000-00805f9b34fb"
RX_CHARACTERISTIC_UUID = "0000ae02-0000-1000-8000-00805f9b34fb"

PRINTER_READY_NOTIFICATION = b"\x51\x78\xae\x01\x01\x00\x00\x00\xff"

SCAN_TIMEOUT_S = 10

# Wait time after sending each chunk of data through BLE.
WAIT_AFTER_EACH_CHUNK_S = 0.2

# Wait for printer done event timeout.
WAIT_FOR_PRINTER_DONE_TIMEOUT = 60


async def scan(name: Optional[str], timeout: int):
    autodiscover = not name
    if autodiscover:
        logger.info("⏳ Trying to auto-discover a printer...")
    else:
        logger.info(f"⏳ Looking for a BLE device named {name}...")

    def filter_fn(device: BLEDevice, adv_data: AdvertisementData):
        if autodiscover:
            return any(
                uuid in adv_data.service_uuids for uuid in POSSIBLE_SERVICE_UUIDS
            )
        else:
            return device.name == name

    device = await BleakScanner.find_device_by_filter(
        filter_fn,
        timeout=timeout,
    )
    if device is None:
        raise RuntimeError(
            "Unable to find printer, make sure it is turned on and in range"
        )
    logger.info(f"✅ Got it. Address: {device}")
    return device


def chunkify(data, chunk_size):
    return (data[i : i + chunk_size] for i in range(0, len(data), chunk_size))


async def get_device_address(device: Optional[str]):
    # See if we were passed a string that smells like an UUID or MAC address.
    if device:
        with contextlib.suppress(ValueError):
            return str(uuid.UUID(device))
        if device.count(":") == 5 and device.replace(":", "").isalnum():
            return device

    return await scan(device, timeout=SCAN_TIMEOUT_S)


def notification_receiver_factory(event):
    def notification_receiver(sender, data):
        logger.debug(f"📡 Received notification: {data}")
        if data == PRINTER_READY_NOTIFICATION:
            event.set()

    return notification_receiver


async def wait_for_printer_ready(event):
    logger.info("⏳ Done printing. Waiting for printer to be ready...")
    await event.wait()
    logger.info("✅ Printer is ready, disconnecting...")


async def run_ble(data, device: Optional[str]):
    try:
        address = await get_device_address(device)
    except RuntimeError as e:
        logger.error(f"🛑 {e}")
        return
    logger.info(f"⏳ Connecting to {address}...")
    async with BleakClient(address) as client:
        # XXX: BlueZ incorrectly reports a fixed MTU of 23; force MTU negotiation manually.
        # https://bleak.readthedocs.io/en/latest/api/client.html#bleak.BleakClient.mtu_size
        # Only use this library on Linux, not MacOS
        if BleakClientBlueZDBus and isinstance(client, BleakClientBlueZDBus):
            await client._acquire_mtu()

        logger.info(f"✅ Connected: {client.is_connected}; MTU: {client.mtu_size}")
        chunk_size = client.mtu_size - 3
        event = asyncio.Event()

        receive_notification = notification_receiver_factory(event)

        await client.start_notify(RX_CHARACTERISTIC_UUID, receive_notification)

        logger.info(
            f"⏳ Sending {len(data)} bytes of data in chunks of {chunk_size} bytes..."
        )
        for i, chunk in enumerate(chunkify(data, chunk_size)):
            await client.write_gatt_char(TX_CHARACTERISTIC_UUID, chunk)
            await asyncio.sleep(WAIT_AFTER_EACH_CHUNK_S)

        try:
            await asyncio.wait_for(
                wait_for_printer_ready(event), timeout=WAIT_FOR_PRINTER_DONE_TIMEOUT
            )
        except asyncio.TimeoutError:
            logger.error("🛑 Timed out while waiting for printer done event. Exiting.")
