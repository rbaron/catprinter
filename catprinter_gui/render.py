"""Turns files of many types into pages (GdkPixbuf) ready to be processed."""
import io
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Callable

import cairo
import gi

gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import GdkPixbuf, Gio, Pango, PangoCairo  # noqa: E402

from catprinter.cmds import PRINT_WIDTH  # noqa: E402

# Blank rows of dots between pages or files.
PAGE_GAP = 24
TEXT_MARGIN = 4
TEXT_LINES_PER_CHUNK = 120

OFFICE_TYPES = (
    "application/vnd.oasis.opendocument.text",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.oasis.opendocument.presentation",
    "application/vnd.oasis.opendocument.graphics",
    "application/msword",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/rtf",
    "text/rtf",
    "text/html",
)

# Types offered in "Open With" and in the context menu of Files.
MIME_TYPES = (
    "image/png", "image/jpeg", "image/gif", "image/bmp", "image/webp",
    "image/tiff", "image/svg+xml", "image/x-icon", "image/heif", "image/avif",
    "application/pdf", "text/plain", "text/markdown", "text/csv",
) + OFFICE_TYPES


class RenderError(Exception):
    pass


@dataclass
class Page:
    load: Callable[[], GdkPixbuf.Pixbuf]
    # "image", "document" or "text": decides the automatic mode and whether
    # the page can be cropped or rotated.
    kind: str
    source: str
    # Blank rows left after this page.
    gap: int = PAGE_GAP


def content_type(path):
    info = Gio.File.new_for_path(path).query_info(
        "standard::content-type", Gio.FileQueryInfoFlags.NONE, None)
    return info.get_content_type()


def is_a(ct, types):
    return any(Gio.content_type_is_a(ct, t) for t in types)


def render_file(path, workdir, text_size=22):
    '''Returns the pages of a file. workdir is a temporary directory for
    intermediate files.'''
    if not os.path.isfile(path):
        raise RenderError(f"No existe el archivo {path}")
    name = os.path.basename(path)
    ct = content_type(path)

    if is_a(ct, ("application/pdf",)):
        return render_pdf(path, workdir, name)
    if ct.startswith("image/"):
        return [Page(lambda: load_image(path), "image", name)]
    if is_a(ct, OFFICE_TYPES):
        return render_office(path, workdir, name)
    if is_a(ct, ("text/plain",)):
        mono = not Gio.content_type_equals(ct, "text/plain")
        return render_text(read_text(path), text_size, mono, name)
    # Last resort: LibreOffice opens lots of formats.
    if shutil.which("soffice"):
        return render_office(path, workdir, name)
    raise RenderError(f"No sé imprimir archivos de tipo {Gio.content_type_get_description(ct)}")


def load_image(path):
    try:
        if Gio.content_type_is_a(content_type(path), "image/svg+xml"):
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, PRINT_WIDTH * 3, -1, True)
        else:
            pb = GdkPixbuf.Pixbuf.new_from_file(path)
    except Exception as e:
        raise RenderError(f"No se pudo abrir la imagen {os.path.basename(path)}: {e}")
    return pb.apply_embedded_orientation() or pb


def render_pdf(path, workdir, name):
    if not shutil.which("pdftoppm"):
        raise RenderError("Para imprimir PDF instala poppler-utils: sudo apt install poppler-utils")
    outdir = tempfile.mkdtemp(dir=workdir)
    # 1400 px on the long side is enough to crop margins or rotate the page.
    result = subprocess.run(
        ["pdftoppm", "-png", "-scale-to", "1400", path, os.path.join(outdir, "p")],
        capture_output=True, text=True)
    files = sorted(
        (f for f in os.listdir(outdir) if f.endswith(".png")),
        key=lambda f: int(f.rsplit("-", 1)[1].split(".")[0]))
    if result.returncode != 0 or not files:
        raise RenderError(f"No se pudo leer el PDF {name}: {result.stderr.strip()}")
    return [
        Page(lambda f=os.path.join(outdir, f): GdkPixbuf.Pixbuf.new_from_file(f), "document", name)
        for f in files
    ]


def render_office(path, workdir, name):
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RenderError("Para imprimir documentos de oficina instala LibreOffice.")
    outdir = tempfile.mkdtemp(dir=workdir)
    # Use a separate profile so it works while LibreOffice is open.
    profile = "file://" + os.path.join(workdir, "lo-profile")
    try:
        subprocess.run(
            [soffice, f"-env:UserInstallation={profile}", "--headless",
             "--convert-to", "pdf", "--outdir", outdir, path],
            capture_output=True, timeout=180)
    except subprocess.TimeoutExpired:
        raise RenderError(f"LibreOffice tardó demasiado en convertir {name}")
    pdfs = [f for f in os.listdir(outdir) if f.endswith(".pdf")]
    if not pdfs:
        raise RenderError(f"LibreOffice no pudo convertir {name}")
    return render_pdf(os.path.join(outdir, pdfs[0]), workdir, name)


def read_text(path):
    with open(path, "rb") as f:
        raw = f.read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def surface_to_pixbuf(surface):
    buf = io.BytesIO()
    surface.write_to_png(buf)
    loader = GdkPixbuf.PixbufLoader.new_with_type("png")
    loader.write(buf.getvalue())
    loader.close()
    return loader.get_pixbuf()


def render_text(text, size_px, mono, name):
    lines = text.expandtabs(4).splitlines() or [""]
    font = Pango.FontDescription.from_string("Monospace" if mono else "Sans")
    font.set_absolute_size(size_px * Pango.SCALE)

    def render_chunk(chunk):
        def load():
            ctx = cairo.Context(cairo.ImageSurface(cairo.FORMAT_RGB24, 1, 1))
            layout = PangoCairo.create_layout(ctx)
            layout.set_width((PRINT_WIDTH - 2 * TEXT_MARGIN) * Pango.SCALE)
            layout.set_wrap(Pango.WrapMode.WORD_CHAR)
            layout.set_font_description(font)
            layout.set_text(chunk, -1)
            height = max(1, layout.get_pixel_extents()[1].height)

            surface = cairo.ImageSurface(cairo.FORMAT_RGB24, PRINT_WIDTH, height)
            ctx = cairo.Context(surface)
            ctx.set_source_rgb(1, 1, 1)
            ctx.paint()
            ctx.set_source_rgb(0, 0, 0)
            ctx.move_to(TEXT_MARGIN, 0)
            PangoCairo.update_layout(ctx, layout)
            PangoCairo.show_layout(ctx, layout)
            return surface_to_pixbuf(surface)
        return load

    # Split in chunks to avoid huge images; they are printed without gaps.
    chunks = ["\n".join(lines[i:i + TEXT_LINES_PER_CHUNK])
              for i in range(0, len(lines), TEXT_LINES_PER_CHUNK)]
    pages = [Page(render_chunk(c), "text", name, gap=0) for c in chunks]
    pages[-1].gap = PAGE_GAP
    return pages
