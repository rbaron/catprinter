import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from catprinter_gui import APP_ID, APP_NAME, DATA_DIR, VERSION, integration  # noqa: E402
from catprinter_gui.window import Window  # noqa: E402


class Application(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self.window = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        # The icon ships with the app, so it shows even when not installed.
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        theme.add_search_path(DATA_DIR)
        for name, callback in (("install", self.on_install),
                               ("uninstall", self.on_uninstall),
                               ("about", self.on_about)):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)
        self.set_accels_for_action("window.close", ["<Control>w", "<Control>q"])

    def get_window(self):
        if self.window is None:
            self.window = Window(self)
        return self.window

    def do_activate(self):
        self.get_window().present()

    def do_open(self, files, n_files, hint):
        window = self.get_window()
        paths = [f.get_path() for f in files if f.get_path()]
        if paths:
            window.load_files(paths)
        window.present()

    def message(self, heading, body):
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("ok", "Aceptar")
        dialog.present(self.window)

    def on_install(self, *_):
        try:
            self.message("Integración lista", integration.install())
        except Exception as e:
            self.message("No se pudo integrar", str(e))

    def on_uninstall(self, *_):
        self.message("Integración eliminada", integration.uninstall())

    def on_about(self, *_):
        Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon=APP_ID,
            version=VERSION,
            developer_name="Gabriel Cortés",
            comments="Imprime imágenes, PDF, documentos y texto en impresoras "
                     "térmicas Bluetooth (GT01, GB0x, SC03h y similares).",
            website="https://github.com/TetradogOther/catprinter",
            license_type=Gtk.License.MIT_X11,
        ).present(self.window)
