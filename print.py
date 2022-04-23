#!/usr/bin/env python
import argparse
import asyncio
import io
import logging
import os
import sys

from catprinter import ble, cmds, img, logger, txt


def parse_args():
    args = argparse.ArgumentParser(
        description='prints an image on your cat thermal printer')
    args.add_argument('--filename', type=str, default="", help="Path to image file to print.")
    args.add_argument('--text', type=str, help="Prints provided text messages. Linebreaks can be added with a newline character \\n Either --filename or --text should be provided, but not both.")
    args.add_argument('-l', '--log-level', type=str,
                      choices=['debug', 'info', 'warn', 'error'], default='info')
    args.add_argument('-b', '--img-binarization-algo', type=str,
                      choices=['mean-threshold',
                               'floyd-steinberg', 'halftone', 'none'],
                      default='floyd-steinberg',
                      help=f'Which image binarization algorithm to use. If \'none\' is used, no binarization will be used. In this case the image has to have a width of {cmds.PRINT_WIDTH} px.')
    args.add_argument('--show-preview', action='store_true',
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
    args.add_argument('-t', '--darker', action='store_true',
                      help="Print the image in text mode. This leads to more contrast, \
                          but slower speed.")
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
    text = args.text

    if not filename and not text:
        logger.info('🛑 Both a filename and text are missing. Please provide one of these parameters. Exiting')
        return

    if filename and text:
        logger.info('🛑 Both a filename and text were provided, only one of these parameters is allowed at a time. Exiting')
        return

    if not text and not os.path.exists(filename):
        logger.info('🛑 File not found. Exiting.')
        return

    try:
        bin_img = None
        if filename:
            with open(filename, "rb") as f:
                img_arr = bytearray(f.read())
                bin_img = img.read_img(img_arr, cmds.PRINT_WIDTH,
                            logger, args.img_binarization_algo,)
        elif text:
            txt_arr = bytearray(txt.text_to_image(text))
            bin_img = img.read_img(txt_arr, cmds.PRINT_WIDTH,
                        logger, args.img_binarization_algo,)

        if bin_img is None:
            logger.info(f'🛑 No image generated. Exiting.')
            return

        if args.show_preview:
            img.show_preview(bin_img)
    except RuntimeError as e:
        logger.error(f'🛑 {e}')
        return

    logger.info(f'✅ Read image: {bin_img.shape} (h, w) pixels')
    data = cmds.cmds_print_img(bin_img, dark_mode=args.darker)
    logger.info(f'✅ Generated BLE commands: {len(data)} bytes')

    # Try to autodiscover a printer if --device is not specified.
    asyncio.run(ble.run_ble(data, device=args.device))


if __name__ == '__main__':
    main()
