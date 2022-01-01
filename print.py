import argparse
import asyncio
import logging
import sys
import os

from catprinter.cmds import PRINT_WIDTH, cmds_print_img
from catprinter.ble import run_ble
from catprinter.img import read_img


def parse_args():
    args = argparse.ArgumentParser(
        description='prints an image on your cat thermal printer')
    args.add_argument('filename', type=str)
    args.add_argument('--log-level', type=str,
                      choices=['debug', 'info', 'warn', 'error'], default='info')
    args.add_argument('--img-binarization-algo', type=str,
                      choices=['mean-threshold', 'floyd-steinberg', 'halftone'],
                      default='floyd-steinberg',
                      help='Which image binarization algorithm to use.')
    args.add_argument('--show-preview', action='store_true',
                      help='If set, displays the final image and asks the user for confirmation before printing.')
    args.add_argument('--devicename', type=str, default='GT01',
                      help='Specify the Bluetooth device name to search for. Default value is GT01.')
    args.add_argument('--darker', action='store_true',
                      help="Print the image in text mode. This leads to more contrast, but slower speed")
    return args.parse_args()


def make_logger(log_level):
    logger = logging.getLogger('catprinter')
    logger.setLevel(log_level)
    h = logging.StreamHandler(sys.stdout)
    h.setLevel(log_level)
    logger.addHandler(h)
    return logger


def main():
    args = parse_args()

    log_level = getattr(logging, args.log_level.upper())
    logger = make_logger(log_level)

    filename = args.filename
    if not os.path.exists(filename):
        logger.info('🛑 File not found. Exiting.')
        return

    bin_img = read_img(args.filename, PRINT_WIDTH,
                       logger, args.img_binarization_algo, args.show_preview)
    if bin_img is None:
        logger.info(f'🛑 No image generated. Exiting.')
        return

    logger.info(f'✅ Read image: {bin_img.shape} (h, w) pixels')
    data = cmds_print_img(bin_img, dark_mode=args.darker)
    logger.info(f'✅ Generated BLE commands: {len(data)} bytes')

    loop = asyncio.get_event_loop()
    loop.run_until_complete(run_ble(data, args.devicename, logger))


if __name__ == '__main__':
    main()
