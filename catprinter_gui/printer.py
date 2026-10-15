"""Printer access for the GUI: an asyncio loop in a background thread that
keeps a connection open to the printer while the app is running."""
import asyncio
import logging
import logging.handlers
import os
import threading
from dataclasses import replace

from gi.repository import GLib

from catprinter import ble, logger
from catprinter.cmds import cmds_print_img

SCAN_TIMEOUT_S = 6

# Everything the printer answers is logged here, which helps diagnosing models.
LOG_PATH = os.path.join(
    os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
    "catprinter", "printer.log")
LOG_MAX_BYTES = 1024 * 1024


def setup_logging():
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            LOG_PATH, maxBytes=LOG_MAX_BYTES, backupCount=1)
    except OSError:
        return
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)


def friendly_error(error):
    '''Turns a Bluetooth error into a message for the user.'''
    text = str(error)
    if "br-connection-profile-unavailable" in text:
        return ("BlueZ intentó conectar por Bluetooth clásico. Si emparejaste la impresora en "
                "Configuración → Bluetooth, elimínala de ahí: no hace falta emparejarla. "
                "Si sigue fallando, activa «Experimental = true» en /etc/bluetooth/main.conf "
                "y ejecuta: sudo systemctl restart bluetooth")
    if "NotReady" in text or "No Bluetooth adapters" in text or "Powered" in text:
        return "El Bluetooth está apagado. Actívalo en la configuración del sistema."
    if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
        return "La impresora no respondió a tiempo. ¿Sigue encendida y cerca?"
    if isinstance(error, PrinterNotConnected):
        return "La impresora no está conectada."
    if "not found" in text.lower() or "UnknownObject" in text:
        return "No se encontró la impresora. ¿Está encendida?"
    return f"Error de Bluetooth: {text or type(error).__name__}"


class PrinterNotConnected(Exception):
    pass


class PrinterService:
    '''Runs printer operations in the background. Every on_done callback is
    called in the GTK thread as on_done(result, error).'''

    def __init__(self, on_disconnect):
        setup_logging()
        self.on_disconnect = on_disconnect
        self.connection = None
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    @property
    def is_connected(self):
        return self.connection is not None and self.connection.is_connected

    def scan(self, on_done):
        '''Finds a printer. The result is a BLEDevice or None.'''
        self._submit(ble.find_printer(SCAN_TIMEOUT_S), on_done)

    def connect(self, device, on_done):
        '''Connects to device and reads its state. The result is a PrinterStatus.'''
        async def job():
            await self._close()

            def lost():
                # Called by bleak in the asyncio thread.
                if self.connection is connection:
                    self.connection = None
                    GLib.idle_add(self.on_disconnect)

            connection = ble.PrinterConnection(device, lost)
            await connection.open()
            self.connection = connection
            return replace(await connection.query_status())

        self._submit(job(), on_done)

    def query_status(self, on_done):
        '''Reads the printer state. The result is a PrinterStatus.'''
        async def job():
            return replace(await self._require_connection().query_status())

        self._submit(job(), on_done)

    def print_rows(self, rows, energy, speed, text_mode, on_progress, on_done):
        '''Prints rows of dots. on_progress is called with the fraction sent so
        far. The result is the PrinterStatus after printing.'''
        async def job():
            connection = self._require_connection()
            data = await self.loop.run_in_executor(
                None, lambda: cmds_print_img(rows, energy=energy, speed=speed, text_mode=text_mode))
            status = await connection.send(data, lambda p: GLib.idle_add(on_progress, p))
            return replace(status)

        self._submit(job(), on_done)

    def close(self):
        '''Disconnects when the app closes, waiting a few seconds at most.'''
        try:
            asyncio.run_coroutine_threadsafe(self._close(), self.loop).result(timeout=3)
        except Exception:
            pass

    def _submit(self, coro, on_done):
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)

        def done(f):
            error = f.exception()
            GLib.idle_add(on_done, None if error else f.result(), error)

        future.add_done_callback(done)

    def _require_connection(self):
        if not self.is_connected:
            raise PrinterNotConnected()
        return self.connection

    async def _close(self):
        connection, self.connection = self.connection, None
        if connection is not None:
            await connection.close()
