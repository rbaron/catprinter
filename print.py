#!/usr/bin/env python
import argparse
import asyncio
import logging
import sys
import os

from catprinter import logger
from catprinter.cmds import PRINT_WIDTH, cmds_print_img
from catprinter.ble import run_ble
from catprinter.img import read_img, show_preview


def parse_args():
    args = argparse.ArgumentParser(
        description='prints an image on your cat thermal printer')
    args.add_argument('filename', type=str)
    args.add_argument('-l', '--log-level', type=str,
                      choices=['debug', 'info', 'warn', 'error'], default='info')
    args.add_argument('-b', '--img-binarization-algo', type=str,
                      choices=['mean-threshold',
                               'floyd-steinberg', 'atkinson', 'halftone', 'none'],
                      default='floyd-steinberg',
                      help=f'Which image binarization algorithm to use. If \'none\'  \
                             is used, no binarization will be used. In this case the \
                             image has to have a width of {PRINT_WIDTH} px.')
    args.add_argument('-s', '--show-preview', action='store_true',
                      help='If set, displays the final image and asks the user for \
                          confirmation before printing.')
    args.add_argument('-d', '--device', type=str, default='',
                      help=(
                          'The printer\'s Bluetooth Low Energy (BLE) address '
                          '(MAC address on Linux; UUID on macOS) '
                          'or advertisement name (e.g.: "GT01", "GB02", "GB03"). '
                          'If omitted, the the script will try to auto discover '
                          'the printer based on its advertised BLE services.'
                      ))
    args.add_argument('-e', '--energy', type=lambda h: int(h.removeprefix("0x"), 16),
                      help="Thermal energy. Between 0x0000 (light) and 0xffff (darker, default).",
                      default="0xffff")
    return args.parse_args()


def configure_logger(log_level):
    logger.setLevel(log_level)
    h = logging.StreamHandler(sys.stdout)
    h.setLevel(log_level)
    logger.addHandler(h)


def main():
    args = parse_args()

    log_level = getattr(logging, args.log_level.upper())
    configure_logger(log_level)

    filename = args.filename
    if not os.path.exists(filename):
        logger.info('🛑 File not found. Exiting.')
        return

    try:
        bin_img = read_img(
            args.filename,
            PRINT_WIDTH,
            args.img_binarization_algo,
        )
        if args.show_preview:
            show_preview(bin_img)
    except RuntimeError as e:
        logger.error(f'🛑 {e}')
        return

    logger.info(f'✅ Read image: {bin_img.shape} (h, w) pixels')
    data = cmds_print_img(bin_img, energy=args.energy)
    logger.info(f'✅ Generated BLE commands: {len(data)} bytes')

    # Try to autodiscover a printer if --device is not specified.
    asyncio.run(run_ble(data, device=args.device))


if __name__ == '__main__':
    main()
