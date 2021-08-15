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
$ python print.py --help
usage: print.py [-h] [--log-level {debug,info,warn,error}] [--img-binarization-algo {mean-threshold,floyd-steinberg}] [--show-preview] filename

prints an image on your cat thermal printer

positional arguments:
  filename

optional arguments:
  -h, --help            show this help message and exit
  --log-level {debug,info,warn,error}
  --img-binarization-algo {mean-threshold,floyd-steinberg}
                        Which image binarization algorithm to use.
  --show-preview        If set, displays the final image and asks the user for confirmation before printing.
```

# Example
```bash
% python print.py --show-preview test.png
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