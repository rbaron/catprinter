"""Main window: file preview, print settings and printer connection."""
import os
import shutil
import tempfile
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from catprinter.cmds import PRINT_WIDTH  # noqa: E402
from catprinter_gui import APP_ID, APP_NAME, process, render, settings  # noqa: E402
from catprinter_gui.printer import PrinterService, friendly_error  # noqa: E402

DOTS_PER_MM = 8  # 203 dpi
RECONNECT_INTERVAL_S = 15
KEEP_ALIVE_INTERVAL_S = 60
RECONNECT_DELAY_S = 2
LOW_BATTERY = 20
REPROCESS_DELAY_MS = 250
RELOAD_DELAY_MS = 400

MODE_LABELS = ("Automático", "Foto (tramado)", "Texto y dibujos (nítido)", "Suave (Atkinson)")

CSS = """
.preview-area { background-color: alpha(@window_fg_color, 0.06); }
.paper {
  background-color: white;
  box-shadow: 0 1px 3px alpha(black, 0.25), 0 4px 12px alpha(black, 0.12);
  border-radius: 2px;
  padding: 8px 0;
}
.status-dot { min-width: 10px; min-height: 10px; border-radius: 5px; }
.status-dot.connected { background-color: @success_color; }
.status-dot.disconnected { background-color: @warning_color; }
.status-dot.busy { background-color: @accent_color; }
.battery { font-feature-settings: "tnum"; }
.battery.low { color: @warning_color; }
"""


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=APP_NAME, default_width=1000,
                         default_height=740, icon_name=APP_ID)
        self.settings = settings.load()
        self.printer = PrinterService(self.on_disconnected)
        self.workdir = tempfile.mkdtemp(prefix="catprinter-")

        # Printer state.
        self.device = None
        self.scanning = False
        self.connecting = False
        self.connected = False
        self.querying = False
        self.printing = False
        self.status = None
        self.error = None

        # Document state. The generation counters discard results of
        # background work that was superseded by newer work.
        self.files = []
        self.pages = []
        self.rows = []
        self.text_mode = False
        self.load_generation = 0
        self.process_generation = 0
        self.process_timeout = 0
        self.reload_timeout = 0

        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.toasts = Adw.ToastOverlay()
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(self.build_header())
        self.banner = Adw.Banner()
        self.banner.connect("button-clicked", lambda *_: self.refresh())
        toolbar.add_top_bar(self.banner)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.add_named(self.build_empty(), "empty")
        self.stack.add_named(self.build_loading(), "loading")
        self.stack.add_named(self.build_main(), "main")
        toolbar.set_content(self.stack)
        self.toasts.set_child(toolbar)
        self.set_content(self.toasts)

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self.on_drop)
        self.add_controller(drop)
        self.connect("close-request", self.on_close)

        self.scan()
        GLib.timeout_add_seconds(RECONNECT_INTERVAL_S, self.auto_reconnect)
        GLib.timeout_add_seconds(KEEP_ALIVE_INTERVAL_S, self.keep_alive)

    # ------------------------------------------------------------ Widgets

    def build_header(self):
        header = Adw.HeaderBar()
        title_box = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        self.status_dot = Gtk.Box(valign=Gtk.Align.CENTER, css_classes=["status-dot"])
        self.title = Adw.WindowTitle(title=APP_NAME)
        title_box.append(self.status_dot)
        title_box.append(self.title)
        header.set_title_widget(title_box)

        open_button = Gtk.Button(icon_name="document-open-symbolic",
                                 tooltip_text="Abrir archivos")
        open_button.connect("clicked", lambda *_: self.choose_files())
        header.pack_start(open_button)

        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=build_menu(),
                                       primary=True, tooltip_text="Menú principal"))
        self.refresh_button = Gtk.Button(icon_name="view-refresh-symbolic",
                                         tooltip_text="Reconectar o actualizar la batería")
        self.refresh_button.connect("clicked", lambda *_: self.refresh())
        header.pack_end(self.refresh_button)

        self.battery_box = Gtk.Box(spacing=4, css_classes=["battery"], visible=False)
        self.battery_icon = Gtk.Image()
        self.battery_label = Gtk.Label()
        self.battery_box.append(self.battery_icon)
        self.battery_box.append(self.battery_label)
        header.pack_end(self.battery_box)
        return header

    def build_empty(self):
        button = Gtk.Button(label="Abrir archivo…", halign=Gtk.Align.CENTER,
                            css_classes=["pill", "suggested-action"])
        button.connect("clicked", lambda *_: self.choose_files())
        return Adw.StatusPage(
            icon_name=APP_ID,
            title="Imprime lo que quieras",
            description="Arrastra aquí imágenes, PDF, documentos o archivos de texto",
            child=button)

    def build_loading(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        box.append(Adw.Spinner(width_request=48, height_request=48))
        self.loading_label = Gtk.Label(css_classes=["dim-label"])
        box.append(self.loading_label)
        return box

    def build_main(self):
        content = Gtk.Box()

        # A strip of paper showing exactly what will be printed.
        self.paper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["paper"],
                             halign=Gtk.Align.CENTER, valign=Gtk.Align.START,
                             margin_top=24, margin_bottom=24, margin_start=24, margin_end=24)
        scroller = Gtk.ScrolledWindow(hexpand=True, vexpand=True, child=self.paper,
                                      css_classes=["preview-area"],
                                      hscrollbar_policy=Gtk.PolicyType.NEVER,
                                      min_content_width=PRINT_WIDTH + 48)
        overlay = Gtk.Overlay(child=scroller)
        self.preview_spinner = Adw.Spinner(width_request=32, height_request=32,
                                           halign=Gtk.Align.END, valign=Gtk.Align.START,
                                           margin_top=12, margin_end=12, visible=False)
        overlay.add_overlay(self.preview_spinner)
        content.append(overlay)
        content.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, width_request=400,
                          hexpand=False)
        page = Adw.PreferencesPage(vexpand=True)
        page.add(self.build_file_group())
        page.add(self.build_image_group())
        page.add(self.build_print_group())
        sidebar.append(page)
        sidebar.append(self.build_print_bar())
        content.append(sidebar)
        return content

    def build_file_group(self):
        group = Adw.PreferencesGroup(title="Archivo")
        self.file_row = Adw.ActionRow()
        add_button = Gtk.Button(icon_name="list-add-symbolic", valign=Gtk.Align.CENTER,
                                tooltip_text="Añadir más archivos", css_classes=["flat"])
        add_button.connect("clicked", lambda *_: self.choose_files(append=True))
        clear_button = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                                  tooltip_text="Quitar todo", css_classes=["flat"])
        clear_button.connect("clicked", lambda *_: self.clear())
        self.file_row.add_suffix(add_button)
        self.file_row.add_suffix(clear_button)
        group.add(self.file_row)

        self.pages_row = Adw.EntryRow(title="Páginas (ej. 1-3, 5)")
        self.pages_row.connect("changed", lambda *_: self.schedule_process())
        group.add(self.pages_row)
        return group

    def build_image_group(self):
        s = self.settings
        group = Adw.PreferencesGroup(title="Imagen")

        self.mode_row = Adw.ComboRow(title="Modo", subtitle="Fotos con tramado, documentos nítidos",
                                     model=Gtk.StringList.new(MODE_LABELS),
                                     selected=process.MODES.index(s["mode"]))
        self.mode_row.connect("notify::selected", self.on_image_setting_changed)
        group.add(self.mode_row)

        self.brightness = self.scale_row(group, "Brillo", -100, 100, s["brightness"])
        self.contrast = self.scale_row(group, "Contraste", -100, 100, s["contrast"])

        self.bold_row = Adw.SwitchRow(title="Engrosar trazos", active=s["bold"],
                                      subtitle="El texto fino sale más oscuro y legible")
        self.crop_row = Adw.SwitchRow(title="Recortar márgenes blancos", active=s["crop"],
                                      subtitle="Aprovecha todo el ancho del papel")
        self.rotate_row = Adw.SwitchRow(title="Girar 90°", active=s["rotate"],
                                        subtitle="Útil para imágenes y páginas horizontales")
        for row in (self.bold_row, self.crop_row, self.rotate_row):
            row.connect("notify::active", self.on_image_setting_changed)
            group.add(row)

        self.text_size_row = Adw.SpinRow.new_with_range(12, 60, 1)
        self.text_size_row.set_title("Tamaño de letra")
        self.text_size_row.set_subtitle("Para archivos de texto")
        self.text_size_row.set_value(s["text_size"])
        self.text_size_row.connect("notify::value", self.on_text_size_changed)
        group.add(self.text_size_row)
        return group

    def build_print_group(self):
        s = self.settings
        group = Adw.PreferencesGroup(
            title="Impresión",
            description="Si sale clarito, sube la concentración de a un nivel. Con poca "
                        "batería puede imprimir en blanco.")
        self.level = self.scale_row(group, "Concentración", *settings.LEVEL_RANGE, s["level"],
                                    affects_preview=False,
                                    subtitle="4 = normal (como la app oficial)")
        self.level.add_mark(settings.DEFAULT_LEVEL, Gtk.PositionType.BOTTOM, None)
        self.speed = self.scale_row(group, "Lentitud", *settings.SPEED_RANGE, s["speed"],
                                    affects_preview=False, subtitle="Más lenta = más oscura")
        return group

    def scale_row(self, group, title, low, high, value, affects_preview=True, subtitle=None):
        row = Adw.ActionRow(title=title, subtitle=subtitle)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, low, high, 1)
        scale.set_value(value)
        scale.set_hexpand(True)
        scale.set_size_request(170, -1)
        scale.set_value_pos(Gtk.PositionType.LEFT)
        scale.set_draw_value(True)
        if low < 0:
            scale.add_mark(0, Gtk.PositionType.BOTTOM, None)
        scale.connect("value-changed", self.on_image_setting_changed if affects_preview
                      else self.save_settings)
        row.add_suffix(scale)
        group.add(row)
        return scale

    def build_print_bar(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                      margin_top=12, margin_bottom=18, margin_start=18, margin_end=18)
        self.length_label = Gtk.Label(css_classes=["dim-label", "caption"])
        self.progress = Gtk.ProgressBar(visible=False)
        self.print_button = Gtk.Button(
            css_classes=["pill", "suggested-action"],
            child=Adw.ButtonContent(icon_name="printer-symbolic", label="Imprimir"))
        self.print_button.connect("clicked", lambda *_: self.print())
        bar.append(self.length_label)
        bar.append(self.progress)
        bar.append(self.print_button)
        return bar

    # ------------------------------------------------------------ Printer
    #
    # The window finds the printer, connects and stays connected like the
    # phone app does. If the connection drops, it looks for it again.

    @property
    def busy(self):
        return self.scanning or self.connecting or self.printing or self.querying

    def scan(self):
        if self.busy:
            return
        self.scanning = True
        self.update_status()
        self.printer.scan(self.on_scan_done)

    def on_scan_done(self, device, error):
        self.scanning = False
        self.device = device
        self.error = friendly_error(error) if error else None
        self.update_status()
        if device:
            self.connect_printer()

    def connect_printer(self):
        if self.busy or not self.device:
            return
        self.connecting = True
        self.update_status()
        self.printer.connect(self.device, self.on_connected)

    def on_connected(self, status, error):
        self.connecting = False
        if error:
            # auto_reconnect() will try again.
            self.device = None
            self.error = "No se pudo conectar: " + friendly_error(error)
            self.update_status()
            return
        self.connected = True
        self.error = None
        self.set_status(status)

    def on_disconnected(self):
        was_connected = self.connected
        self.connected = False
        self.device = None
        self.status = None
        self.error = "Se perdió la conexión con la impresora. Reconectando…"
        self.update_status()
        if was_connected and not self.printing:
            GLib.timeout_add_seconds(RECONNECT_DELAY_S, lambda: self.scan() or GLib.SOURCE_REMOVE)

    def auto_reconnect(self):
        if not self.connected and not self.busy:
            if self.device:
                self.connect_printer()
            else:
                self.scan()
        return GLib.SOURCE_CONTINUE

    def keep_alive(self):
        # Polling the state keeps the link active and the battery level fresh.
        if self.connected and not self.busy:
            self.query_status(quiet=True)
        return GLib.SOURCE_CONTINUE

    def refresh(self):
        if self.connected:
            self.query_status()
        elif self.device:
            self.connect_printer()
        else:
            self.scan()

    def query_status(self, quiet=False):
        if self.busy or not self.connected:
            return
        self.querying = True
        if not quiet:
            self.update_status()
        self.printer.query_status(lambda status, error: self.on_status(status, error, quiet))

    def on_status(self, status, error, quiet=False):
        self.querying = False
        if error:
            if not quiet:
                self.toasts.add_toast(Adw.Toast(
                    title="No se pudo leer el estado: " + friendly_error(error), timeout=5))
            self.update_status()
            return
        self.set_status(status)

    def set_status(self, status):
        if status.battery is None and self.status:
            status.battery = self.status.battery
        self.status = status
        self.update_status()

    def update_status(self):
        name = self.device.name if self.device else ""
        if self.printing:
            state, subtitle = "busy", f"Imprimiendo en {name}…"
        elif self.connecting:
            state, subtitle = "busy", f"Conectando con {name}…"
        elif self.connected:
            state, subtitle = "connected", f"{name} conectada"
        elif self.scanning:
            state, subtitle = "busy", "Buscando impresora…"
        else:
            state, subtitle = "disconnected", "Impresora no conectada"
        self.status_dot.set_css_classes(["status-dot", state])
        self.title.set_subtitle(subtitle)

        problems = self.status_problems()
        if not self.connected and not self.busy:
            self.banner.set_title(
                self.error or "No se encontró la impresora. Enciéndela y acércala al equipo.")
            self.banner.set_button_label("Buscar de nuevo")
            self.banner.set_revealed(True)
        elif self.connected and problems:
            self.banner.set_title(" · ".join(problems))
            self.banner.set_button_label("Comprobar")
            self.banner.set_revealed(True)
        else:
            self.banner.set_revealed(False)
        self.update_battery()
        self.refresh_button.set_sensitive(not self.busy)
        self.update_print_button()

    def status_problems(self):
        s = self.status
        if not s:
            return []
        problems = []
        if s.no_paper:
            problems.append("Sin papel")
        if s.cover_open:
            problems.append("Tapa abierta")
        if s.overheat:
            problems.append("Cabezal caliente: espera unos minutos")
        if self.battery_low():
            problems.append("Batería baja: carga la impresora, puede imprimir en blanco")
        return problems

    def battery_low(self):
        s = self.status
        return bool(s) and not s.charging and (
            s.low_battery or (s.battery is not None and s.battery <= LOW_BATTERY))

    def update_battery(self):
        battery = self.status.battery if self.status and self.connected else None
        self.battery_box.set_visible(battery is not None)
        if battery is None:
            return
        level = min(100, round(battery / 10) * 10)
        if self.status.charging:
            suffix = "-charged" if level == 100 else "-charging"
            tooltip = f"Batería de la impresora: {battery} % (cargando)"
        else:
            suffix, tooltip = "", f"Batería de la impresora: {battery} %"
        self.battery_icon.set_from_icon_name(f"battery-level-{level}{suffix}-symbolic")
        self.battery_label.set_label(f"{battery} %")
        self.battery_box.set_tooltip_text(tooltip)
        if self.battery_low():
            self.battery_box.add_css_class("low")
        else:
            self.battery_box.remove_css_class("low")

    def update_print_button(self):
        self.print_button.set_sensitive(bool(self.connected and self.rows and not self.busy))
        self.print_button.set_tooltip_text(
            None if self.connected else "Esperando a que se conecte la impresora")

    def print(self):
        if not (self.connected and self.rows) or self.busy:
            return
        self.printing = True
        self.save_settings()
        self.progress.set_fraction(0)
        self.progress.set_visible(True)
        self.update_status()
        self.printer.print_rows(
            list(self.rows),
            settings.energy_value(int(self.level.get_value()), self.text_mode),
            int(self.speed.get_value()), self.text_mode,
            self.progress.set_fraction, self.on_print_done)

    def on_print_done(self, status, error):
        self.printing = False
        self.progress.set_visible(False)
        if error:
            self.show_error("No se pudo imprimir", friendly_error(error))
            if self.printer.is_connected:
                self.update_status()
            else:
                self.on_disconnected()
                self.scan()
        else:
            self.toasts.add_toast(Adw.Toast(title="¡Impreso!", timeout=3))
            self.set_status(status)

    # -------------------------------------------------------------- Files

    def choose_files(self, append=False):
        dialog = Gtk.FileDialog(title="Elegir archivos para imprimir")

        def done(dialog, result):
            try:
                files = dialog.open_multiple_finish(result)
            except GLib.Error:
                return  # Cancelled.
            paths = [f.get_path() for f in files if f.get_path()]
            if paths:
                self.load_files(paths, append)

        dialog.open_multiple(self, None, done)

    def on_drop(self, _target, value, _x, _y):
        paths = [f.get_path() for f in value.get_files() if f.get_path()]
        if paths:
            self.load_files(paths, append=bool(self.files))
        return True

    def load_files(self, paths, append=False):
        files = (self.files if append else []) + list(paths)
        self.load_generation += 1
        generation = self.load_generation
        self.loading_label.set_label(
            "Abriendo " + ", ".join(os.path.basename(p) for p in paths) + "…")
        self.stack.set_visible_child_name("loading")
        text_size = int(self.text_size_row.get_value())

        def work():
            loaded, pages, errors = [], [], []
            for path in files:
                try:
                    pages += render.render_file(path, self.workdir, text_size)
                    loaded.append(path)
                except Exception as e:
                    errors.append(str(e))
            GLib.idle_add(self.on_files_loaded, generation, loaded, pages, errors)

        threading.Thread(target=work, daemon=True).start()

    def on_files_loaded(self, generation, files, pages, errors):
        if generation != self.load_generation:
            return
        for error in errors:
            self.toasts.add_toast(Adw.Toast(title=error, timeout=6))
        if not pages:
            self.clear()
            return
        self.files = files
        self.pages = pages
        names = [os.path.basename(f) for f in files]
        if len(names) == 1:
            title = names[0]
            subtitle = f"{len(pages)} página" + ("s" if len(pages) != 1 else "")
        else:
            title = f"{len(names)} archivos"
            subtitle = ", ".join(names[:3]) + ("…" if len(names) > 3 else "")
        self.file_row.set_title(GLib.markup_escape_text(title))
        self.file_row.set_subtitle(GLib.markup_escape_text(subtitle))
        self.pages_row.set_visible(len(pages) > 1)
        self.text_size_row.set_visible(any(p.kind == "text" for p in pages))
        self.stack.set_visible_child_name("main")
        self.process_now()

    def clear(self):
        self.load_generation += 1
        self.process_generation += 1
        self.files, self.pages, self.rows = [], [], []
        self.pages_row.set_text("")
        self.stack.set_visible_child_name("empty")
        self.update_print_button()

    # --------------------------------------------------------- Processing

    def options(self):
        return process.Options(
            mode=process.MODES[self.mode_row.get_selected()],
            brightness=int(self.brightness.get_value()),
            contrast=int(self.contrast.get_value()),
            rotate=self.rotate_row.get_active(),
            crop=self.crop_row.get_active(),
            bold=self.bold_row.get_active())

    def on_image_setting_changed(self, *_):
        self.save_settings()
        self.schedule_process()

    def on_text_size_changed(self, *_):
        # Text is rendered when loading, so text files have to be reloaded.
        self.save_settings()
        if not any(p.kind == "text" for p in self.pages):
            return
        if self.reload_timeout:
            GLib.source_remove(self.reload_timeout)

        def reload():
            self.reload_timeout = 0
            self.load_files(self.files)
            return GLib.SOURCE_REMOVE

        self.reload_timeout = GLib.timeout_add(RELOAD_DELAY_MS, reload)

    def schedule_process(self):
        if not self.pages:
            return
        if self.process_timeout:
            GLib.source_remove(self.process_timeout)
        self.process_timeout = GLib.timeout_add(REPROCESS_DELAY_MS, self.process_now)

    def process_now(self):
        self.process_timeout = 0
        try:
            selected = process.parse_page_range(self.pages_row.get_text(), len(self.pages))
            self.pages_row.remove_css_class("error")
        except ValueError:
            self.pages_row.add_css_class("error")
            return GLib.SOURCE_REMOVE

        self.process_generation += 1
        generation = self.process_generation
        pages = [self.pages[i] for i in selected]
        opts = self.options()
        # Like the official app: text mode and energy only if everything is sharp.
        text_mode = bool(pages) and all(
            process.resolve_mode(opts.mode, p.kind) == "sharp" for p in pages)
        self.preview_spinner.set_visible(True)

        def work():
            chunks = []
            try:
                for page in pages:
                    if generation != self.process_generation:
                        return
                    rows = process.process_page(page, opts)
                    chunks.append((rows, [bytes(PRINT_WIDTH)] * page.gap))
            except Exception as e:
                GLib.idle_add(self.on_processed, generation, None, text_mode, str(e))
                return
            GLib.idle_add(self.on_processed, generation, chunks, text_mode, None)

        threading.Thread(target=work, daemon=True).start()
        return GLib.SOURCE_REMOVE

    def on_processed(self, generation, chunks, text_mode, error):
        if generation != self.process_generation:
            return
        self.preview_spinner.set_visible(False)
        if error:
            self.toasts.add_toast(Adw.Toast(title=f"Error al procesar: {error}", timeout=6))
            return
        # The printer feeds paper at the end, so drop the last page's gap.
        if chunks:
            chunks[-1] = (chunks[-1][0], [])

        while child := self.paper.get_first_child():
            self.paper.remove(child)
        self.rows = []
        self.text_mode = text_mode
        for rows, gap in chunks:
            self.rows += rows + gap
            # One picture per page: GPUs can't show textures that are too tall.
            texture = Gdk.MemoryTexture.new(
                PRINT_WIDTH, len(rows), Gdk.MemoryFormat.G8,
                GLib.Bytes.new(process.preview_bytes(rows)), PRINT_WIDTH)
            self.paper.append(Gtk.Picture(paintable=texture, can_shrink=False,
                                          margin_bottom=len(gap)))

        cm = len(self.rows) / DOTS_PER_MM / 10
        self.length_label.set_label(f"Largo aproximado: {cm:.1f} cm de papel")
        self.update_print_button()

    # -------------------------------------------------------------- Misc

    def save_settings(self, *_):
        s = self.settings
        s["mode"] = process.MODES[self.mode_row.get_selected()]
        s["brightness"] = int(self.brightness.get_value())
        s["contrast"] = int(self.contrast.get_value())
        s["rotate"] = self.rotate_row.get_active()
        s["crop"] = self.crop_row.get_active()
        s["bold"] = self.bold_row.get_active()
        s["text_size"] = int(self.text_size_row.get_value())
        s["level"] = int(self.level.get_value())
        s["speed"] = int(self.speed.get_value())
        settings.save(s)

    def show_error(self, heading, body):
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("ok", "Aceptar")
        dialog.present(self)

    def on_close(self, *_):
        self.save_settings()
        self.printer.close()
        shutil.rmtree(self.workdir, ignore_errors=True)
        return False


def build_menu():
    menu = Gio.Menu()
    integration = Gio.Menu()
    integration.append("Integrar con Archivos y el menú de apps", "app.install")
    integration.append("Quitar integración", "app.uninstall")
    menu.append_section(None, integration)
    about = Gio.Menu()
    about.append(f"Acerca de {APP_NAME}", "app.about")
    menu.append_section(None, about)
    return menu
