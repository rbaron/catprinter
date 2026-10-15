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
from catprinter.cmds import CMD_GET_BATTERY, CMD_GET_DEV_STATE
from catprinter.status import CMD_DEV_STATE, PrinterStatus, parse_notification

# For some reason, bleak reports the 0xaf30 service on my macOS, while it reports
# 0xae30 (which I believe is correct) on my Raspberry Pi. This hacky workaround
# should cover both cases.

POSSIBLE_SERVICE_UUIDS = [
    "0000ae30-0000-1000-8000-00805f9b34fb",
    "0000af30-0000-1000-8000-00805f9b34fb",
]

TX_CHARACTERISTIC_UUID = "0000ae01-0000-1000-8000-00805f9b34fb"
RX_CHARACTERISTIC_UUID = "0000ae02-0000-1000-8000-00805f9b34fb"

# Flow control: the printer asks us to pause when its buffer is full.
PRINTER_READY_NOTIFICATION = b"\x51\x78\xae\x01\x01\x00\x00\x00\xff"
PRINTER_BUSY_NOTIFICATION = b"\x51\x78\xae\x01\x01\x00\x10\x70\xff"

SCAN_TIMEOUT_S = 10

CONNECT_ATTEMPTS = 3

# Largest packet the official app sends (its "imgMTU" for these printers).
# Larger writes can overflow the printer's buffer and result in blank prints.
MAX_PACKET_SIZE = 180

# Wait time after sending each chunk of data through BLE.
WAIT_AFTER_EACH_CHUNK_S = 0.02

# Time to wait for the answers to a status query.
STATUS_WAIT_S = 1.5

# Wait for printer done event timeout.
WAIT_FOR_PRINTER_DONE_TIMEOUT = 30


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


async def find_printer(timeout: int = SCAN_TIMEOUT_S) -> Optional[BLEDevice]:
    '''Auto-discovers a printer, returning None if none is found.'''

    def filter_fn(device: BLEDevice, adv_data: AdvertisementData):
        return any(uuid in adv_data.service_uuids for uuid in POSSIBLE_SERVICE_UUIDS)

    return await BleakScanner.find_device_by_filter(filter_fn, timeout=timeout)


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


async def prefer_le_bearer(address):
    '''Asks BlueZ to connect to the printer over Bluetooth Low Energy.

    Dual-mode printers (e.g. SC03h) also advertise classic Bluetooth (SPP), and
    BlueZ then tries a BR/EDR connection, which fails with
    "br-connection-profile-unavailable". The PreferredBearer property needs
    BlueZ >= 5.80 with "Experimental = true" in /etc/bluetooth/main.conf; it is
    silently skipped otherwise.
    '''
    if BleakClientBlueZDBus is None or address is None:
        return
    from dbus_next import BusType, Message, MessageType, Variant
    from dbus_next.aio import MessageBus

    if isinstance(address, BLEDevice):
        path = address.details["path"]
    else:
        path = "/org/bluez/hci0/dev_" + address.upper().replace(":", "_")
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    try:
        reply = await bus.call(
            Message(
                destination="org.bluez",
                path=path,
                interface="org.freedesktop.DBus.Properties",
                member="Set",
                signature="ssv",
                body=["org.bluez.Device1", "PreferredBearer", Variant("s", "le")],
            )
        )
        if reply.message_type == MessageType.ERROR:
            logger.debug(f"Could not set PreferredBearer: {reply.error_name}")
        else:
            logger.debug("Set PreferredBearer=le")
    finally:
        bus.disconnect()


async def connect(address, disconnected_callback=None):
    '''Connects to the printer, retrying if BlueZ picks the classic (BR/EDR)
    bearer of a dual-mode printer anyway.'''
    for attempt in range(CONNECT_ATTEMPTS):
        await prefer_le_bearer(address)
        logger.info(f"⏳ Connecting to {address}...")
        client = BleakClient(address, disconnected_callback=disconnected_callback)
        try:
            await client.connect()
            return client
        except Exception as e:
            if "br-connection-profile-unavailable" not in str(e) or attempt == CONNECT_ATTEMPTS - 1:
                raise
            logger.info("⚠️ BlueZ tried classic Bluetooth, retrying over LE...")
            await asyncio.sleep(1)


class PrinterConnection:
    '''A connection to the printer that can stay open between prints.'''

    def __init__(self, address, on_disconnect=None):
        self.address = address
        self.on_disconnect = on_disconnect
        self.client = None
        self.status = PrinterStatus()
        self.can_send = asyncio.Event()
        self.can_send.set()
        # Set when the printer answers a state query, which it does once it has
        # processed everything sent before it.
        self.state_received = asyncio.Event()
        # Prints and status queries must not interleave.
        self.lock = asyncio.Lock()

    @property
    def is_connected(self):
        return self.client is not None and self.client.is_connected

    async def open(self):
        def disconnected(_client):
            logger.info("🔌 Printer disconnected")
            self.client = None
            if self.on_disconnect:
                self.on_disconnect()

        client = await connect(self.address, disconnected)
        try:
            # XXX: BlueZ incorrectly reports a fixed MTU of 23; force MTU negotiation manually.
            # https://bleak.readthedocs.io/en/latest/api/client.html#bleak.BleakClient.mtu_size
            # Only use this library on Linux, not MacOS
            if BleakClientBlueZDBus and isinstance(client, BleakClientBlueZDBus):
                await client._acquire_mtu()
            await client.start_notify(RX_CHARACTERISTIC_UUID, self._on_notification)
        except Exception:
            await client.disconnect()
            raise
        self.client = client
        logger.info(f"✅ Connected: {client.is_connected}; MTU: {client.mtu_size}")

    async def close(self):
        client, self.client = self.client, None
        if client is not None:
            # Closing on purpose: don't report it as a lost connection.
            client.set_disconnected_callback(None)
            await client.disconnect()

    def _on_notification(self, _sender, data):
        logger.debug(f"📡 Received notification: {bytes(data).hex(' ')}")
        parse_notification(data, self.status)
        if data == PRINTER_READY_NOTIFICATION:
            self.can_send.set()
        elif data == PRINTER_BUSY_NOTIFICATION:
            self.can_send.clear()
        elif len(data) > 2 and data[2] == CMD_DEV_STATE:
            self.state_received.set()

    async def query_status(self) -> PrinterStatus:
        '''Asks the printer for its state and battery level.'''
        async with self.lock:
            for cmd in (CMD_GET_DEV_STATE, CMD_GET_BATTERY):
                await self.client.write_gatt_char(TX_CHARACTERISTIC_UUID, cmd)
            await asyncio.sleep(STATUS_WAIT_S)
        logger.info(f"🔋 Printer status: {self.status}")
        return self.status

    async def send(self, data, progress=None) -> PrinterStatus:
        '''Sends data generated by cmds_print_img() and waits until the printer
        has processed it. progress, if given, is called with the fraction of
        data sent so far.'''
        async with self.lock:
            chunk_size = min(self.client.mtu_size, MAX_PACKET_SIZE) - 3
            chunks = list(chunkify(data, chunk_size))
            self.can_send.set()
            logger.info(
                f"⏳ Sending {len(data)} bytes of data in chunks of {chunk_size} bytes..."
            )
            for i, chunk in enumerate(chunks):
                if i == len(chunks) - 1:
                    # The data ends with a state query; its answer means "done".
                    self.state_received.clear()
                await asyncio.wait_for(
                    self.can_send.wait(), timeout=WAIT_FOR_PRINTER_DONE_TIMEOUT)
                await self.client.write_gatt_char(TX_CHARACTERISTIC_UUID, chunk)
                await asyncio.sleep(WAIT_AFTER_EACH_CHUNK_S)
                if progress:
                    progress((i + 1) / len(chunks))

            logger.info("⏳ Done sending. Waiting for the printer to finish...")
            try:
                await asyncio.wait_for(
                    self.state_received.wait(), timeout=WAIT_FOR_PRINTER_DONE_TIMEOUT)
                logger.info("✅ Printer is done.")
            except asyncio.TimeoutError:
                logger.error("🛑 Timed out while waiting for printer done event.")
        return self.status


async def query_status(address) -> PrinterStatus:
    '''Connects briefly to ask the printer for its state and battery level.'''
    connection = PrinterConnection(address)
    await connection.open()
    try:
        return await connection.query_status()
    finally:
        await connection.close()


async def send_data(address, data, progress=None) -> PrinterStatus:
    '''Connects, sends data to the printer and disconnects.'''
    connection = PrinterConnection(address)
    await connection.open()
    try:
        return await connection.send(data, progress)
    finally:
        await connection.close()


async def run_ble(data, device: Optional[str]):
    try:
        address = await get_device_address(device)
    except RuntimeError as e:
        logger.error(f"🛑 {e}")
        return
    await send_data(address, data)
