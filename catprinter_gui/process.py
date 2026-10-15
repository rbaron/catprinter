"""Turns pages into rows of black and white dots for the printer.

Pure Python plus GdkPixbuf, so the app needs neither numpy nor OpenCV.
Grayscale images are bytearrays of width*height values from 0 to 255; dots
are bytearrays of 1 (black) and 0 (white).
"""
from dataclasses import dataclass

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf  # noqa: E402

from catprinter.cmds import PRINT_WIDTH  # noqa: E402

MODES = ("auto", "photo", "sharp", "atkinson")

# Pixels darker than this count as content when cropping margins.
CROP_THRESHOLD = 220
CROP_PADDING = 0.02
TRIM_PADDING_ROWS = 8

_THRESHOLD_TABLE = bytes(1 if v < 128 else 0 for v in range(256))
_CROP_TABLE = bytes(1 if v < CROP_THRESHOLD else 0 for v in range(256))
_PREVIEW_TABLE = bytes([255, 0]) + bytes(254)


@dataclass
class Options:
    mode: str = "auto"
    brightness: int = 0
    contrast: int = 0
    rotate: bool = False
    crop: bool = True
    bold: bool = True


def flatten_scale(pb, width, height, interp=GdkPixbuf.InterpType.HYPER):
    '''Scales pb to width x height over a white background, without alpha.'''
    dest = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, width, height)
    dest.fill(0xffffffff)
    pb.composite(dest, 0, 0, width, height, 0, 0,
                 width / pb.get_width(), height / pb.get_height(), interp, 255)
    return dest


def to_gray(pb):
    w, h, rs = pb.get_width(), pb.get_height(), pb.get_rowstride()
    data = pb.read_pixel_bytes().get_data()
    out = bytearray(w * h)
    for y in range(h):
        row = data[y * rs:y * rs + w * 3]
        out[y * w:(y + 1) * w] = bytes(
            (77 * r + 150 * g + 29 * b) >> 8
            for r, g, b in zip(row[0::3], row[1::3], row[2::3]))
    return out


def crop_to_content(pb):
    '''Crops white margins so the content uses the whole paper width.'''
    w, h = pb.get_width(), pb.get_height()
    sw = min(w, 600)
    sh = max(1, round(h * sw / w))
    gray = to_gray(flatten_scale(pb, sw, sh, GdkPixbuf.InterpType.BILINEAR))
    top = bottom = None
    left, right = sw, -1
    for y in range(sh):
        row = gray[y * sw:(y + 1) * sw].translate(_CROP_TABLE)
        first = row.find(1)
        if first < 0:
            continue
        if top is None:
            top = y
        bottom = y
        left = min(left, first)
        right = max(right, row.rfind(1))
    if top is None:
        return pb

    sx, sy = w / sw, h / sh
    pad = round(max(w, h) * CROP_PADDING)
    x0 = max(0, int(left * sx) - pad)
    y0 = max(0, int(top * sy) - pad)
    x1 = min(w, int((right + 1) * sx) + pad)
    y1 = min(h, int((bottom + 1) * sy) + pad)
    return pb.new_subpixbuf(x0, y0, x1 - x0, y1 - y0)


def tone_table(brightness, contrast):
    c = contrast * 2.55
    factor = 259 * (c + 255) / (255 * (259 - c))
    return bytes(
        max(0, min(255, round(factor * (v - 128) + 128 + brightness * 2.55)))
        for v in range(256))


def floyd_steinberg(gray, w, h):
    px = list(gray)
    out = bytearray(w * h)
    for y in range(h):
        base = y * w
        has_next = y < h - 1
        for x in range(w):
            i = base + x
            old = px[i]
            if old < 128:
                out[i] = 1
                err = old
            else:
                err = old - 255
            if not err:
                continue
            if x + 1 < w:
                px[i + 1] += err * 7 >> 4
            if has_next:
                j = i + w
                if x > 0:
                    px[j - 1] += err * 3 >> 4
                px[j] += err * 5 >> 4
                if x + 1 < w:
                    px[j + 1] += err >> 4
    return out


def atkinson(gray, w, h):
    px = list(gray)
    out = bytearray(w * h)
    n = w * h
    for y in range(h):
        base = y * w
        for x in range(w):
            i = base + x
            old = px[i]
            if old < 128:
                out[i] = 1
                err = old
            else:
                err = old - 255
            err >>= 3
            if not err:
                continue
            if x + 1 < w:
                px[i + 1] += err
                if x + 2 < w:
                    px[i + 2] += err
            for j in (i + w - 1 if x > 0 else -1, i + w, i + w + 1 if x + 1 < w else -1, i + 2 * w):
                if 0 <= j < n:
                    px[j] += err
    return out


def embolden(bits, w, h):
    '''Thickens strokes by one dot to the right, so thin text prints darker.'''
    out = bytearray(len(bits))
    for y in range(h):
        row = int.from_bytes(bits[y * w:(y + 1) * w], "big")
        out[y * w:(y + 1) * w] = (row | (row >> 8)).to_bytes(w, "big")
    return out


def resolve_mode(mode, kind):
    if mode != "auto":
        return mode
    return "photo" if kind == "image" else "sharp"


def process_page(page, opts):
    '''Returns the rows of a page, as PRINT_WIDTH bytes of 0/1 each.'''
    pb = page.load()
    if page.kind != "text":
        if opts.rotate:
            pb = pb.rotate_simple(GdkPixbuf.PixbufRotation.CLOCKWISE)
        if opts.crop:
            pb = crop_to_content(pb)

    w = PRINT_WIDTH
    h = max(1, round(pb.get_height() * w / pb.get_width()))
    gray = to_gray(flatten_scale(pb, w, h))
    if opts.brightness or opts.contrast:
        gray = gray.translate(tone_table(opts.brightness, opts.contrast))

    mode = resolve_mode(opts.mode, page.kind)
    if mode == "photo":
        bits = floyd_steinberg(gray, w, h)
    elif mode == "atkinson":
        bits = atkinson(gray, w, h)
    else:
        bits = gray.translate(_THRESHOLD_TABLE)
    if opts.bold:
        bits = embolden(bits, w, h)

    rows = [bytes(bits[y * w:(y + 1) * w]) for y in range(h)]
    if opts.crop and page.kind != "text":
        rows = trim_blank_rows(rows)
    return rows


def trim_blank_rows(rows):
    marked = [i for i, r in enumerate(rows) if any(r)]
    if not marked:
        return rows
    start = max(0, marked[0] - TRIM_PADDING_ROWS)
    end = min(len(rows), marked[-1] + 1 + TRIM_PADDING_ROWS)
    return rows[start:end]


def preview_bytes(rows):
    '''Grayscale (G8) preview image: black = 0, white = 255.'''
    return b"".join(rows).translate(_PREVIEW_TABLE)


def parse_page_range(text, count):
    '''"1-3, 5" -> indices [0, 1, 2, 4]. Empty means all pages. Raises
    ValueError if the range is not valid.'''
    text = text.strip()
    if not text:
        return list(range(count))
    pages = []
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start = int(a) if a.strip() else 1
            end = int(b) if b.strip() else count
        else:
            start = end = int(part)
        if not (1 <= start <= end <= count):
            raise ValueError(part)
        pages.extend(range(start - 1, end))
    return pages
