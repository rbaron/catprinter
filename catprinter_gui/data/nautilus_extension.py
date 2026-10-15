# Installed by the catprinter AppImage. Adds "Imprimir en impresora térmica"
# to the context menu of Files. Requires: sudo apt install python3-nautilus
import subprocess

from gi.repository import GObject, Nautilus

EXEC = "@EXEC@"
SUPPORTED = (
    "image/", "text/", "application/pdf", "application/rtf",
    "application/msword", "application/vnd.ms-", "application/vnd.oasis.opendocument.",
    "application/vnd.openxmlformats-officedocument.",
)


class CatPrinterMenu(GObject.GObject, Nautilus.MenuProvider):
    def get_file_items(self, files):
        paths = []
        for f in files:
            location = f.get_location()
            path = location.get_path() if location else None
            if f.is_directory() or not path or not f.get_mime_type().startswith(SUPPORTED):
                return []
            paths.append(path)
        if not paths:
            return []
        item = Nautilus.MenuItem(
            name="CatPrinter::print",
            label="Imprimir en impresora térmica",
            icon="io.github.catprinter.Gui",
        )
        item.connect("activate", lambda *_: subprocess.Popen(
            [EXEC, *paths], start_new_session=True))
        return [item]

    def get_background_items(self, *args):
        return []
