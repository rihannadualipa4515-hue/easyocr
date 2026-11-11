"""Connects the independent modules: image -> OCR -> cleaning -> matching -> database."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .config import SCREENSHOT_DIR, Settings, to_stored_path
from .database import Database
from .errors import OCRError, StorageError, TextFileError
from .services.ocr_engine import OCREngine
from .services.screenshot_capture import save_screenshot, validate_image
from .services.sentence_matcher import SentenceMatcher, answer_keywords
from .services.text_processor import clean_text

log = logging.getLogger(__name__)


@dataclass
class ProcessResult:
    capture_id: int
    total_found: int = 0
    keywords: list[str] = field(default_factory=list)
    answer_keywords: list[str] = field(default_factory=list)
    answers_found: int = 0
    match_error: str | None = None


class Pipeline:
    def __init__(self, settings: Settings, db: Database, ocr: OCREngine, matcher: SentenceMatcher):
        self.settings, self.db, self.ocr, self.matcher = settings, db, ocr, matcher

    def process(self, image) -> ProcessResult:
        rgb = validate_image(image)
        original = self.ocr.extract_text(rgb)
        cleaned = clean_text(original)
        if not cleaned:
            raise OCRError("No text was recognised in the screenshot.")

        mode = self.settings["match_mode"]
        keywords, matches, total, match_error, answers = [], [], 0, None, []
        try:
            outcome = self.matcher.match(cleaned, mode, int(self.settings["min_word_length"]),
                                         int(self.settings["max_results"]))
            keywords, total, mode = outcome.keywords, outcome.total_found, outcome.mode
            matches = [(r.line_number, r.position, r.text) for r in outcome.results]
            answers = [(a.line_number, a.position, a.text, a.score) for a in self.matcher.best_answers(
                cleaned, int(self.settings["answer_count"]), float(self.settings["answer_min_coverage"]))]
        except TextFileError as exc:               # OCR result is still saved
            match_error = str(exc)

        path = save_screenshot(rgb, SCREENSHOT_DIR)
        try:
            capture_id = self.db.add_capture(original, cleaned, to_stored_path(path), mode, matches, answers)
        except StorageError:
            path.unlink(missing_ok=True)
            raise
        return ProcessResult(capture_id, total, keywords, answer_keywords(cleaned), len(answers), match_error)
