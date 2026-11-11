"""Paths and persistent settings (settings.json next to the program)."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):          # running as .exe (PyInstaller)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _base_dir()
DATA_DIR = BASE_DIR / "data"
SCREENSHOT_DIR = BASE_DIR / "screenshots"
MODELS_DIR = BASE_DIR / "models"
DB_PATH = BASE_DIR / "finder.db"
SETTINGS_PATH = BASE_DIR / "settings.json"
LOG_PATH = BASE_DIR / "app.log"

IMAGE_FILETYPES = [
    ("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff"),
    ("All files", "*.*"),
]

DEFAULTS = {
    "text_file": "data/text.txt",   # relative to the program folder, or absolute
    "match_mode": "all",            # "all"  = Mode A, "any" = Mode B
    "ocr_languages": ["tr", "en"],     # Latin model: reads Turkmen letters ä ň ž ý ş ç ö ü
    "use_gpu": False,
    "min_word_length": 3,
    "max_results": 500,
    "answer_count": 3,              # how many "best answer" sentences are shown
    "answer_min_coverage": 0.5,     # share of the question words a sentence must contain (0..1)
    "monitor_clipboard": True,
    "bring_to_front": True,
}


def resolve_path(value) -> Path:
    p = Path(value)
    return p if p.is_absolute() else BASE_DIR / p


def to_stored_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(BASE_DIR).as_posix()
    except ValueError:
        return str(path)


class Settings:
    def __init__(self, path: Path = SETTINGS_PATH):
        self.path = path
        self._data = dict(DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data.update({k: v for k, v in raw.items() if k in DEFAULTS})
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            log.warning("Could not read settings: %s", exc)

    def save(self) -> None:
        self.path.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        if key not in DEFAULTS:
            raise KeyError(key)
        self._data[key] = value
