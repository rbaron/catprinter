import argparse
import asyncio
import logging
import sys

from catprinter.cmds import PRINT_WIDTH, cmds_print_img
from catprinter.ble import run_ble
from catprinter.img import read_img


def parse_args():
    args = argparse.ArgumentParser(
        description='prints an image on your cat thermal printer')
    args.add_argument('filename', type=str)
    args.add_argument('--log-level', type=str,
                      choices=['debug', 'info', 'warn', 'error'], default='info')
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

    bin_img = read_img(args.filename, PRINT_WIDTH)
    logger.info(f'✅ Read image: {bin_img.shape} (h, w) pixels')
    data = cmds_print_img(bin_img)
    logger.info(f'✅ Generated BLE commands: {len(data)} bytes')

    loop = asyncio.get_event_loop()
    loop.run_until_complete(run_ble(data, logger))


if __name__ == '__main__':
    main()
