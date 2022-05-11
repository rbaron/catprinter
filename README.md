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
usage: print.py [-h] [--filename FILENAME] [--text TEXT] [--log-level {debug,info,warn,error}]
                [--img-binarization-algo {mean-threshold,floyd-steinberg,halftone,none}] [--show-preview]
                [--devicename DEVICENAME] [--darker]

prints an image on your cat thermal printer

options:
  -h, --help            show this help message and exit
  --filename FILENAME   Path to image file to print.
  --text TEXT           Prints provided text messages. Either --filename or --text should be provided, but not both.
  --log-level {debug,info,warn,error}
  --img-binarization-algo {mean-threshold,floyd-steinberg,halftone,none}
                        Which image binarization algorithm to use. If 'none' is used, no binarization will be used. In this
                        case the image has to have a width of 384 px.
  --show-preview        If set, displays the final image and asks the user for confirmation before printing.
  --devicename DEVICENAME
                        Specify the Bluetooth Low Energy (BLE) device name to search for. If not specified, the script will
                        try to auto discover the printer based on its advertised BLE service UUIDs. Common names are similar
                        to "GT01", "GB02", "GB03".
  --darker              Print the image in text mode. This leads to more contrast, but slower speed.
```

# Example
```bash
% python print.py --show-preview --filename test.png
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

Mean Threshold:
![Mean threshold](./media/grumpy_mean_threshold.png)

Floyd Steinberg (default)
![Floyd Steinberg](./media/grumpy_floydsteinberg.png)

Halftone dithering
![Halftone](./media/grumpy_halftone.png)
