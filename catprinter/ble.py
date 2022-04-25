import asyncio
from bleak import BleakClient, BleakError, BleakScanner
from bleak.backends.scanner import AdvertisementData
from bleak.backends.device import BLEDevice
from catprinter import logger

# For some reason, bleak reports the 0xaf30 service on my macOS, while it reports
# 0xae30 (which I believe is correct) on my Raspberry Pi. This hacky workaround
# should cover both cases.

POSSIBLE_SERVICE_UUIDS = [
    '0000ae30-0000-1000-8000-00805f9b34fb',
    '0000af30-0000-1000-8000-00805f9b34fb',
]

TX_CHARACTERISTIC_UUID = '0000ae01-0000-1000-8000-00805f9b34fb'

SCAN_TIMEOUT_S = 10

# This is a hacky solution so we don't terminate the BLE connection to the printer
# while it's still printing. A better solution is to subscribe to the RX characteristic
# and listen for printer events, so we know exactly when the printing is finished.
WAIT_AFTER_DATA_SENT_S = 30


async def scan(name, timeout, autodiscover):
    if autodiscover:
        logger.info(f'⏳ Trying to auto-discover a printer...')
    else:
        logger.info(f'⏳ Looking for a BLE device named {name}...')

    def filter_fn(device: BLEDevice, adv_data: AdvertisementData):
        if autodiscover:
            return any(uuid in adv_data.service_uuids
                       for uuid in POSSIBLE_SERVICE_UUIDS)
        else:
            return device.name == name

    device = await BleakScanner.find_device_by_filter(
        filter_fn, timeout=timeout,
    )
    if device is None:
        raise RuntimeError('Unable to find printer, make sure it is turned on and in range')
    logger.info(f'✅ Got it. Address: {device}')
    return device


def chunkify(data, chunk_size):
    return (
        data[i: i + chunk_size] for i in range(0, len(data), chunk_size)
    )


async def run_ble(data, devicename, autodiscover):
    try:
        address = await scan(devicename, SCAN_TIMEOUT_S, autodiscover)
    except RuntimeError as e:
        logger.error(f'🛑 {e}')
        return
    logger.info(f'⏳ Connecting to {address}...')
    async with BleakClient(address) as client:
        logger.info(
            f'✅ Connected: {client.is_connected}; MTU: {client.mtu_size}')
        chunk_size = client.mtu_size - 3
        logger.info(
            f'⏳ Sending {len(data)} bytes of data in chunks of {chunk_size} bytes...')
        for i, chunk in enumerate(chunkify(data, chunk_size)):
            await client.write_gatt_char(TX_CHARACTERISTIC_UUID, chunk)
        logger.info(f'✅ Done.')
        await asyncio.sleep(WAIT_AFTER_DATA_SENT_S)
