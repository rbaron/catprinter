import asyncio
import numpy as np
from bleak import BleakClient, BleakError, BleakScanner

TX_CHARACTERISTIC_UUID = '4B646063-6264-F3A7-8941-E65356EA82FE'

SCAN_TIMEOUT_S = 10

WAIT_AFTER_DATA_SENT_S = 5

CMD_CLEAR_IMG_BUF = 0x00
CMD_PUSH_IMG_BUF_TO_EPD = 0x01
CMD_SET_IMG_BUF_POSITION = 0x02
CMD_WRITE_IMG_BUF = 0x03


async def scan(name, timeout, logger):
    logger.info(f'⏳ Looking for a BLE device named {name}...')
    device = await BleakScanner.find_device_by_filter(
        lambda d, ad: d.name and d.name == name,
        timeout=timeout,
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


async def run_ble(data, devicename, logger):
    address = await scan(devicename, SCAN_TIMEOUT_S, logger)
    logger.info(f'⏳ Connecting to {address}...')
    async with BleakClient(address) as client:
        logger.info(
            f'✅ Connected: {client.is_connected}; MTU: {client.mtu_size}')
        # Clear the image buffer.
        await client.write_gatt_char(
            TX_CHARACTERISTIC_UUID, bytearray([CMD_CLEAR_IMG_BUF, 0xff]))
        # Reset the buffer pointer, so we start writing at position 0.
        await client.write_gatt_char(
            TX_CHARACTERISTIC_UUID, bytearray([CMD_SET_IMG_BUF_POSITION, 0x00, 0x00]))
        chunk_size = client.mtu_size - 3 - 1
        logger.info(
            f'⏳ Sending {len(data)} bytes of data in chunks of {chunk_size} bytes...')
        for i, chunk in enumerate(chunkify(data, chunk_size)):
            await client.write_gatt_char(
                TX_CHARACTERISTIC_UUID,
                np.concatenate([np.array([CMD_WRITE_IMG_BUF], dtype=np.uint8), chunk]))
        # Trigger a refresh.
        await client.write_gatt_char(TX_CHARACTERISTIC_UUID, bytearray([CMD_PUSH_IMG_BUF_TO_EPD]))
        logger.info(f'✅ Done.')
        await asyncio.sleep(WAIT_AFTER_DATA_SENT_S)
