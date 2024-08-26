import cv2
from math import ceil
import numpy as np

from catprinter import logger


def floyd_steinberg_dither(img):
    '''Applies the Floyd-Steinberg dithering to img, in place.
    img is expected to be a 8-bit grayscale image.

    Algorithm borrowed from wikipedia.org/wiki/Floyd%E2%80%93Steinberg_dithering.
    '''
    h, w = img.shape

    def adjust_pixel(y, x, delta):
        if y < 0 or y >= h or x < 0 or x >= w:
            return
        img[y][x] = min(255, max(0, img[y][x] + delta))

    for y in range(h):
        for x in range(w):
            new_val = 255 if img[y][x] > 127 else 0
            err = img[y][x] - new_val
            img[y][x] = new_val
            adjust_pixel(y, x + 1, err * 7/16)
            adjust_pixel(y + 1, x - 1, err * 3/16)
            adjust_pixel(y + 1, x, err * 5/16)
            adjust_pixel(y + 1, x + 1, err * 1/16)
    return img

def atkinson_dither(img):
    '''
    Applies the Atkinson dithering to img, in place.
    img is expected to be a 8-bit grayscale image.

    Algorithm from https://tannerhelland.com/2012/12/28/dithering-eleven-algorithms-source-code.html
    '''
    h, w = img.shape

    def adjust_pixel(y, x, delta):
        if y < 0 or y >= h or x < 0 or x >= w:
            return
        img[y][x] = min(255, max(0, img[y][x] + delta))

    for y in range(h):
        for x in range(w):
            new_val = 255 if img[y][x] > 127 else 0
            err = img[y][x] - new_val
            img[y][x] = new_val
            adjust_pixel(y, x + 1, err * 1/8)
            adjust_pixel(y, x + 2, err * 1/8)
            adjust_pixel(y + 1, x - 1, err * 1/8)
            adjust_pixel(y + 1, x, err * 1/8)
            adjust_pixel(y + 1, x + 1, err * 1/8)
            adjust_pixel(y + 2, x, err * 1/8)
    return img


def halftone_dither(img):
    '''Applies Halftone dithering using different sized circles

    Algorithm is borrowed from https://github.com/GravO8/halftone
    '''

    def square_avg_value(square):
        '''
        Calculates the average grayscale value of the pixels in a square of the
        original image
        Argument:
            square: List of N lists, each with N integers whose value is between 0
            and 255
        '''
        sum = 0
        n = 0
        for row in square:
            for pixel in row:
                sum += pixel
                n += 1
        return sum/n

    side = 4
    jump = 4  # Todo: make this configurable
    alpha = 3
    height, width = img.shape

    if not jump:
        jump = ceil(min(height, height)*0.007)
    assert jump > 0, "jump must be greater than 0"

    height_output, width_output = side*ceil(height/jump), side*ceil(width/jump)
    canvas = np.zeros((height_output, width_output), np.uint8)
    output_square = np.zeros((side, side), np.uint8)
    x_output, y_output = 0, 0
    for y in range(0, height, jump):
        for x in range(0, width, jump):
            output_square[:] = 255
            intensity = 1 - square_avg_value(img[y:y+jump, x:x+jump])/255
            radius = int(alpha*intensity*side/2)
            if radius > 0:
                # draw a circle
                cv2.circle(
                    output_square,
                    center=(side//2, side//2),
                    radius=radius,
                    color=(0, 0, 0),
                    thickness=-1,
                    lineType=cv2.FILLED
                )
            # place the square on the canvas
            canvas[y_output:y_output+side,
                   x_output:x_output+side] = output_square
            x_output += side
        y_output += side
        x_output = 0
    return canvas


def read_img(
    filename,
    print_width,
    img_binarization_algo,
):
    im = cv2.imread(filename, cv2.IMREAD_GRAYSCALE)
    height = im.shape[0]
    width = im.shape[1]
    factor = print_width / width
    resized = cv2.resize(
        im,
        (
            print_width,
            int(height * factor)
        ),
        interpolation=cv2.INTER_AREA)

    if img_binarization_algo == 'atkinson':
        logger.info('⏳ Applying Atkinson dithering to image...')
        resized = atkinson_dither(resized)
        logger.info('✅ Done.')
        resized = resized > 127
    elif img_binarization_algo == 'floyd-steinberg':
        logger.info('⏳ Applying Floyd-Steinberg dithering to image...')
        resized = floyd_steinberg_dither(resized)
        logger.info('✅ Done.')
        resized = resized > 127
    elif img_binarization_algo == 'halftone':
        logger.info('⏳ Applying halftone dithering to image...')
        resized = halftone_dither(resized)
        logger.info('✅ Done.')
        resized = resized > 127
    elif img_binarization_algo == 'mean-threshold':
        resized = resized > resized.mean()
    elif img_binarization_algo == 'none':
        if width == print_width:
            resized = im > 127
        else:
            raise RuntimeError(
                f'Wrong width of {width} px. '
                f'An image with a width of {print_width} px '
                f'is required for "none" binarization'
            )

    else:
        raise RuntimeError(
            f'unknown image binarization algorithm: '
            f'{img_binarization_algo}'
        )

    # Invert the image before returning it.
    return ~resized


def show_preview(bin_img):
    # Convert from our boolean representation to float and invert.
    preview_img = (~bin_img).astype(float)
    cv2.imshow('Preview', preview_img)
    logger.info('ℹ️  Displaying preview.')
    # Calling waitKey(1) tells OpenCV to process its GUI events and actually display our image.
    cv2.waitKey(1)
    if input('🤔 Go ahead with print? [Y/n]? ').lower() == 'n':
        raise RuntimeError('Aborted print.')
