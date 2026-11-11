"""EasyOCR wrapper. Independent of the GUI and of the database.

The Reader (and its neural-network models) is created once and reused for every screenshot.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from ..errors import EmptyScreenshotError, OCRError

log = logging.getLogger(__name__)
MIN_CONFIDENCE = 0.20


class OCREngine:
    def __init__(self, languages: list[str], gpu: bool, model_dir: Path):
        self.languages = list(languages) or ["en"]
        self.gpu = bool(gpu)
        self.model_dir = Path(model_dir)
        self._reader = None
        self._init_error: str | None = None
        self._lock = threading.RLock()

    def configure(self, languages: list[str], gpu: bool) -> None:
        languages = list(languages) or ["en"]
        with self._lock:
            if languages != self.languages or bool(gpu) != self.gpu:
                self.languages, self.gpu, self._reader = languages, bool(gpu), None

    def _get_reader(self):
        with self._lock:
            if self._reader is None:
                if self._init_error:        # torch cannot be re-imported after a failed import: keep the real cause
                    raise OCRError(self._init_error)
                try:
                    import easyocr
                    self.model_dir.mkdir(parents=True, exist_ok=True)
                    log.info("Loading EasyOCR models %s (gpu=%s)", self.languages, self.gpu)
                    self._reader = easyocr.Reader(self.languages, gpu=self.gpu, verbose=False,
                                                  model_storage_directory=str(self.model_dir))
                except Exception as exc:                                   # noqa: BLE001
                    log.exception("EasyOCR initialisation failed")
                    self._init_error = (
                        f"Could not load the OCR engine: {type(exc).__name__}: {exc}\n"
                        "Fix the problem (see README / check_torch.bat), then RESTART the program.")
                    raise OCRError(self._init_error) from exc
            return self._reader

    def warm_up(self) -> None:
        self._get_reader()

    def extract_text(self, image) -> str:
        """Returns the recognised text, one visual line per text line."""
        import numpy as np
        import cv2

        rgb = image.convert("RGB")
        arr = np.array(rgb)
        h, w = arr.shape[:2]
        if h < 8 or w < 8:
            raise EmptyScreenshotError("The screenshot is too small to contain text.")
        scale = 1.0
        if h < 150:
            scale = 2.0                                  # tiny snips are upscaled for better accuracy
        elif max(h, w) > 3200:
            scale = 3200 / max(h, w)
        if scale != 1.0:
            arr = cv2.resize(arr, None, fx=scale, fy=scale,
                             interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)
        with self._lock:
            reader = self._get_reader()
            try:
                results = reader.readtext(arr, detail=1, paragraph=False)
            except Exception as exc:                                       # noqa: BLE001
                log.exception("OCR failed")
                raise OCRError(f"Text recognition failed: {exc}") from exc
        return boxes_to_text(results)


def boxes_to_text(results) -> str:
    """Groups EasyOCR boxes into visual lines (top to bottom, left to right)."""
    items = []
    for bbox, text, conf in results:
        text = str(text).strip()
        if not text or conf < MIN_CONFIDENCE:
            continue
        ys = [float(p[1]) for p in bbox]
        xs = [float(p[0]) for p in bbox]
        items.append({"x": min(xs), "y": (min(ys) + max(ys)) / 2, "h": max(ys) - min(ys), "text": text})
    items.sort(key=lambda i: i["y"])
    lines: list[dict] = []
    for it in items:
        if lines and abs(it["y"] - lines[-1]["y"]) <= 0.5 * max(it["h"], lines[-1]["h"]):
            line = lines[-1]
            line["items"].append(it)
            line["y"] = sum(i["y"] for i in line["items"]) / len(line["items"])
            line["h"] = max(line["h"], it["h"])
        else:
            lines.append({"y": it["y"], "h": it["h"], "items": [it]})
    return "\n".join(" ".join(i["text"] for i in sorted(l["items"], key=lambda i: i["x"])) for l in lines)
