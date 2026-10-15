![Cat Printer](./media/hackoclock.jpg)

Cat printer is a portable thermal printer sold on AliExpress for around $20.

This repository contains Python code for talking to the cat printer over Bluetooth Low Energy (BLE). The code has been reverse engineered from the [official Android app](https://play.google.com/store/apps/details?id=com.frogtosea.iprint&hl=en_US&gl=US).

# Installation
```bash
# Clone the repository.
$ git clone git@github.com:rbaron/catprinter.git
$ cd catprinter
# Create a virtualenv on venv/ and activate it.
$ virtualenv --python=python3 venv
$ source venv/bin/activate
# Install requirements from requirements.txt.
$ pip install -r requirements.txt
```

# Usage
```bash
$ ./print.py --help
usage: print.py [-h] [-l {debug,info,warn,error}] [-b {mean-threshold,floyd-steinberg,atkinson,halftone,none}] [-s] [-d DEVICE] [-e ENERGY]
                [-S SPEED] filename

prints an image on your cat thermal printer

positional arguments:
  filename

options:
  -h, --help            show this help message and exit
  -l {debug,info,warn,error}, --log-level {debug,info,warn,error}
  -b {mean-threshold,floyd-steinberg,atkinson,halftone,none}, --img-binarization-algo {mean-threshold,floyd-steinberg,atkinson,halftone,none}
                        Which image binarization algorithm to use. If 'none' is used, no binarization will be used. In this case the image has to
                        have a width of 384 px.
  -s, --show-preview    If set, displays the final image and asks the user for confirmation before printing.
  -d DEVICE, --device DEVICE
                        The printer's Bluetooth Low Energy (BLE) address (MAC address on Linux; UUID on macOS) or advertisement name (e.g.:
                        "GT01", "GB02", "GB03"). If omitted, the the script will try to auto discover the printer based on its advertised BLE
                        services.
  -e ENERGY, --energy ENERGY
                        Thermal energy. Between 0x0000 (light) and 0xffff (darker, default).
  -S SPEED, --speed SPEED
                        Print speed. Higher values print slower and darker. The official app uses 10 for the SC03h.
```

# Desktop app (AppImage)

There is also a GTK 4 desktop app (in Spanish) in `catprinter_gui/`. It
stays connected to the printer, shows its battery level and prints images,
PDFs, office documents (through LibreOffice) and text files with a preview
of the exact dots that will be printed.

It runs on the system's Python and GTK, so on Debian/Ubuntu you need:

```bash
$ sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 poppler-utils
```

Build the AppImage (about 1 MB) and run it:

```bash
$ ./appimage/build.sh
$ ./dist/CatPrinter-*-x86_64.AppImage
```

From the app menu, "Integrar con Archivos y el menú de apps" (or
`--instalar` on the command line) copies the AppImage to `~/.local/bin` and
adds it to the application menu, to "Open With" and to the context menu of
Files. For a top-level entry in that context menu, also install
`python3-nautilus` and restart Files with `nautilus -q`.

# Web app

`docs/` contains a web app (in Spanish) that prints from the browser through
Web Bluetooth, with the same processing and print settings as the desktop
app. It is a PWA: it can be installed, works offline once loaded, appears in
the Android share sheet and, when installed on the desktop, in "Open With".

Publish it with GitHub Pages (Settings → Pages → Deploy from a branch →
`main`, `/docs`). Web Bluetooth needs Chrome, Edge or Opera on Windows,
macOS, Android or ChromeOS; on other browsers the page explains the
alternatives. To try it locally, serve `docs/` over `http://localhost`.

# Dual-mode printers (SC03h)

Some printers, like the SC03h, also offer classic Bluetooth. BlueZ may then
try to connect over classic Bluetooth and fail with
`br-connection-profile-unavailable`. To fix it:

- Don't pair the printer in the system's Bluetooth settings. If you did,
  remove it there: these printers don't need pairing.
- With BlueZ 5.80 or newer, set `Experimental = true` in the `[General]`
  section of `/etc/bluetooth/main.conf` and run
  `sudo systemctl restart bluetooth`. This lets catprinter ask BlueZ to use
  Bluetooth Low Energy for the printer.

If prints come out blank, charge the printer: with a low battery it feeds
the paper but doesn't heat the print head.

# Example
```bash
% ./print.py --show-preview test.png
⏳ Applying Floyd-Steinberg dithering to image...
✅ Done.
ℹ️ Displaying preview.
🤔 Go ahead with print? [Y/n]?
✅ Read image: (42, 384) (h, w) pixels
✅ Generated BLE commands: 2353 bytes
⏳ Looking for a BLE device named GT01...
✅ Got it. Address: 09480C21-65B5-477B-B475-C797CD0D6B1C: GT01
⏳ Connecting to 09480C21-65B5-477B-B475-C797CD0D6B1C: GT01...
✅ Connected: True; MTU: 104
⏳ Sending 2353 bytes of data in chunks of 101 bytes...
✅ Done.
```


# Different Algorithms

**Mean Threshold:**

![Mean threshold](./media/grumpymeanthreshold.png)


**Floyd Steinberg (default):**

![Floyd Steinberg](./media/grumpyfloydsteinbergexample.png)

**Atkinson:**

![Atkinson](./media/grumpyatkinsonexample.png)

**Halftone dithering:**

![Halftone](./media/grumpyhalftone.png)

**None (image must be 384px wide):**

![None](./media/grumpynone.png)
