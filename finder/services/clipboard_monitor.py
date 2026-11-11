"""Detects new screenshots (WIN+SHIFT+S) by watching the Windows clipboard.

Windows' own Snipping Tool handles the hotkey and puts the selected area into the clipboard, so the
default screenshot behaviour is never touched or intercepted - we only *read* the clipboard when the
clipboard sequence number changes.
"""
from __future__ import annotations

import hashlib
import logging
import sys
import threading
from typing import Callable

from ..errors import ClipboardError

log = logging.getLogger(__name__)


def _sequence_number() -> int | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        return int(ctypes.windll.user32.GetClipboardSequenceNumber())
    except Exception:                                                     # noqa: BLE001
        return None


class ClipboardMonitor:
    def __init__(self, on_image: Callable, on_error: Callable[[str], None], interval: float = 0.4):
        self._on_image, self._on_error, self._interval = on_image, on_error, interval
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(self._stop,), name="clipboard-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------
    @staticmethod
    def _grab():
        from PIL import ImageGrab
        return ImageGrab.grabclipboard()

    def _run(self, stop: threading.Event) -> None:
        last_seq = _sequence_number()          # whatever is in the clipboard now is ignored
        last_sig = None
        retries = 0
        while not stop.wait(self._interval):
            seq = _sequence_number()
            if seq is not None and seq == last_seq and retries == 0:
                continue
            try:
                data = self._grab()
            except Exception as exc:                                       # noqa: BLE001
                retries += 1
                if retries >= 3:
                    log.warning("Clipboard access failed: %s", exc)
                    self._on_error(str(ClipboardError(f"Cannot read the clipboard: {exc}")))
                    last_seq, retries = seq, 0
                continue
            if data is None and retries < 2 and seq is not None:
                retries += 1                  # the image may still be on its way into the clipboard
                continue
            retries = 0
            last_seq = seq
            if data is None or isinstance(data, list):
                last_sig = None
                continue
            try:
                sig = (data.size, hashlib.md5(data.convert("RGB").resize((48, 48)).tobytes()).hexdigest())
                if seq is None and sig == last_sig:       # non-Windows fallback: compare content
                    continue
                last_sig = sig
                self._on_image(data.copy())
            except Exception as exc:                                       # noqa: BLE001
                log.exception("Screenshot handling failed")
                self._on_error(f"Unexpected screenshot capture failure: {exc}")
