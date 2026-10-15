"""Desktop integration for the AppImage: application menu, "Open With" and
the context menu of Files (Nautilus)."""
import glob
import os
import shutil
import subprocess

from catprinter_gui import APP_ID, APP_NAME, DATA_DIR
from catprinter_gui.render import MIME_TYPES

HOME = os.path.expanduser("~")
DATA_HOME = os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share")

APPIMAGE_DEST = os.path.join(HOME, ".local", "bin", "CatPrinter.AppImage")
DESKTOP_FILE = os.path.join(DATA_HOME, "applications", f"{APP_ID}.desktop")
ICON_FILE = os.path.join(DATA_HOME, "icons", "hicolor", "scalable", "apps", f"{APP_ID}.svg")
NAUTILUS_SCRIPT = os.path.join(DATA_HOME, "nautilus", "scripts", "Imprimir en impresora térmica")
NAUTILUS_EXTENSION = os.path.join(
    DATA_HOME, "nautilus-python", "extensions", "catprinter_nautilus.py")

SCRIPT = """#!/bin/sh
# Installed by the catprinter AppImage.
set -f
IFS='
'
[ -n "$NAUTILUS_SCRIPT_SELECTED_FILE_PATHS" ] && set -- $NAUTILUS_SCRIPT_SELECTED_FILE_PATHS
exec "{exec}" "$@"
"""

DESKTOP = """[Desktop Entry]
Type=Application
Name={name}
GenericName=Impresora térmica Bluetooth
Comment=Imprime imágenes, PDF, documentos y texto en tu impresora térmica
Exec="{exec}" %F
Icon={app_id}
Terminal=false
Categories=Graphics;Utility;
Keywords=printer;thermal;cat;impresora;térmica;bluetooth;
MimeType={mime};
StartupNotify=true
StartupWMClass={app_id}
"""


def is_appimage():
    return bool(os.environ.get("APPIMAGE"))


def nautilus_python_available():
    return bool(glob.glob("/usr/lib/*/nautilus/extensions-4/libnautilus-python.so"))


def is_installed():
    return os.path.exists(DESKTOP_FILE)


def _write(path, content, executable=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    if executable:
        os.chmod(path, 0o755)


def install():
    '''Copies the AppImage to ~/.local/bin and installs the launchers.
    Returns a summary for the user.'''
    source = os.environ.get("APPIMAGE")
    if not source:
        raise RuntimeError("La integración solo está disponible al ejecutar la AppImage.")
    os.makedirs(os.path.dirname(APPIMAGE_DEST), exist_ok=True)
    if os.path.realpath(source) != os.path.realpath(APPIMAGE_DEST):
        tmp = APPIMAGE_DEST + ".new"
        shutil.copy2(source, tmp)
        os.chmod(tmp, 0o755)
        os.replace(tmp, APPIMAGE_DEST)

    os.makedirs(os.path.dirname(ICON_FILE), exist_ok=True)
    shutil.copy(os.path.join(DATA_DIR, f"{APP_ID}.svg"), ICON_FILE)
    _write(DESKTOP_FILE, DESKTOP.format(
        name=APP_NAME, exec=APPIMAGE_DEST, app_id=APP_ID, mime=";".join(MIME_TYPES)))
    _write(NAUTILUS_SCRIPT, SCRIPT.format(name=APP_NAME, exec=APPIMAGE_DEST), executable=True)
    with open(os.path.join(DATA_DIR, "nautilus_extension.py")) as f:
        _write(NAUTILUS_EXTENSION, f.read().replace("@EXEC@", APPIMAGE_DEST))

    for cmd in (["update-desktop-database", os.path.dirname(DESKTOP_FILE)],
                ["gtk-update-icon-cache", "-qtf", os.path.join(DATA_HOME, "icons", "hicolor")]):
        try:
            subprocess.run(cmd, capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            pass

    lines = [
        f"Instalado en {APPIMAGE_DEST}",
        "Aparece en el menú de aplicaciones y en «Abrir con» de Archivos.",
    ]
    if nautilus_python_available():
        lines.append("Menú contextual de Archivos: «Imprimir en impresora térmica» "
                     "(reinicia Archivos con: nautilus -q).")
    else:
        lines.append("Menú contextual de Archivos: Scripts → «Imprimir en impresora térmica». "
                     "Para tenerlo directo en el menú: sudo apt install python3-nautilus && nautilus -q")
    return "\n".join(lines)


def uninstall():
    for path in (DESKTOP_FILE, ICON_FILE, NAUTILUS_SCRIPT, NAUTILUS_EXTENSION, APPIMAGE_DEST):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
    try:
        subprocess.run(["update-desktop-database", os.path.dirname(DESKTOP_FILE)],
                       capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "Integración eliminada."
