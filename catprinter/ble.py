import asyncio
from bleak import BleakClient, BleakError, BleakScanner
from bleak.backends.scanner import AdvertisementData
from bleak.backends.device import BLEDevice

TX_SERVICE_UUID = '0000af30-0000-1000-8000-00805f9b34fb'
TX_CHARACTERISTIC_UUID = '0000ae01-0000-1000-8000-00805f9b34fb'

SCAN_TIMEOUT_S = 10

# This is a hacky solution so we don't terminate the BLE connection to the printer
# while it's still printing. A better solution is to subscribe to the RX characteristic
# and listen for printer events, so we know exactly when the printing is finished.
WAIT_AFTER_DATA_SENT_S = 30


async def scan(name, timeout, autodiscover, logger):
    if autodiscover:
        logger.info(f'⏳ Trying to auto-discover a printer...')
    else:
        logger.info(f'⏳ Looking for a BLE device named {name}...')

    def filter_fn(device: BLEDevice, adv_data: AdvertisementData):
        if autodiscover:
            return TX_SERVICE_UUID in adv_data.service_uuids
        else:
            return device.name == name

    device = await BleakScanner.find_device_by_filter(
        filter_fn, timeout=timeout,
    )
    if device is None:
        logger.error(f'🛑 Unable to find printerAdMake sure it is turned on')
        raise RuntimeError('unable to find printer')
    logger.info(f'✅ Got it. Address: {device}')
    return device


def chunkify(data, chunk_size):
    return (
        data[i: i + chunk_size] for i in range(0, len(data), chunk_size)
    )


async def run_ble(data, devicename, autodiscover, logger):
    address = await scan(devicename, SCAN_TIMEOUT_S, autodiscover, logger)
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
