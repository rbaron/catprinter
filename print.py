import argparse
import asyncio
import logging
import sys
import os

from catprinter.cmds import PRINT_WIDTH, cmds_print_img
from catprinter.ble import run_ble
from catprinter.img import read_img

class prefixchoice(list):
    def __contains__(self, other):
        for i in self:
            if i.startswith(other):
                return True
        return False

def parse_args():
    args = argparse.ArgumentParser(
        description='prints an image on your cat thermal printer')
    args.add_argument('filename', type=str)
    args.add_argument('-l', '--log-level', type=str,
                      choices=['debug', 'info', 'warn', 'error'], default='info')
    args.add_argument('-b', '--img-binarization-algo', type=str,
                      choices=prefixchoice(['mean-threshold',
                               'floyd-steinberg', 'halftone', 'none']),
                      default='floyd-steinberg',
                      help=f'Which image binarization algorithm to use. If \'none\' is used, no binarization will be used. In this case the image has to have a width of {PRINT_WIDTH} px.')
    args.add_argument('-s', '--show-preview', action='store_true',
                      help='If set, displays the final image and asks the user for \
                          confirmation before printing.')
    args.add_argument('-d', '--devicename', type=str, default='',
                      help='Specify the Bluetooth Low Energy (BLE) device name to    \
                          search for. If not specified, the script will try to       \
                          auto discover the printer based on its advertised BLE      \
                          service UUIDs. Common names are similar to "GT01", "GB02", \
                          "GB03".')
    args.add_argument('-t', '--darker', action='store_true',
                      help="Print the image in text mode. This leads to more contrast, \
                          but slower speed.")
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

    # Try to autodiscover a printer if --devicename is not specified.
    autodiscover = not args.devicename
    asyncio.run(run_ble(data, args.devicename, autodiscover, logger))


if __name__ == '__main__':
    main()
