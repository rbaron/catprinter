"""User settings, stored in ~/.config/catprinter/gui.json."""
import json
import os

PATH = os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
    "catprinter", "gui.json")

# Bumped when stored values must be reset because their meaning changed.
VERSION = 3

# Values the official iPrint app uses for the SC03h: speed 10 and a base
# energy of 5000 for images and 8000 for text. Each concentration level above
# or below the default adds or removes 15 % of energy.
SPEED_RANGE = (5, 40)
LEVEL_RANGE = (1, 9)
DEFAULT_LEVEL = 4
IMAGE_ENERGY = 5000
TEXT_ENERGY = 8000

DEFAULTS = {
    "mode": "auto",
    "brightness": 0,
    "contrast": 0,
    "rotate": False,
    "crop": True,
    "bold": True,
    "text_size": 22,
    "level": DEFAULT_LEVEL,
    # Higher values print slower and darker.
    "speed": 10,
}


def load():
    settings = dict(DEFAULTS)
    try:
        with open(PATH) as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return settings
    if saved.get("version", 1) < VERSION:
        saved.pop("speed", None)
    settings.update({k: v for k, v in saved.items() if k in DEFAULTS})
    if not SPEED_RANGE[0] <= settings["speed"] <= SPEED_RANGE[1]:
        settings["speed"] = DEFAULTS["speed"]
    if not LEVEL_RANGE[0] <= settings["level"] <= LEVEL_RANGE[1]:
        settings["level"] = DEFAULT_LEVEL
    return settings


def save(settings):
    try:
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        with open(PATH, "w") as f:
            json.dump(dict(settings, version=VERSION), f, indent=2)
    except OSError:
        pass


def energy_value(level, text_mode):
    '''Thermal energy for a concentration level, as the official app computes it.'''
    base = TEXT_ENERGY if text_mode else IMAGE_ENERGY
    return round(base * (1 + (level - DEFAULT_LEVEL) * 0.15))
