"""Text helpers: OCR cleaning, sentence splitting of text.txt, cached word index.

Pure standard library - no OCR / GUI imports.
"""
from __future__ import annotations

import bisect
import re
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..errors import TextFileError

# --------------------------------------------------------------------------- words
WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
PREFIX_LEN = 4


def fold_word(word: str) -> str:
    """Case- and diacritics-insensitive form: Türkmenistanyň -> turkmenistanyn (robust against OCR accent errors)."""
    w = word.casefold().replace("\u0131", "i")
    return "".join(c for c in unicodedata.normalize("NFD", w) if not unicodedata.combining(c))


def tokenize(text: str) -> list[str]:
    """Folded words; punctuation is never part of a word."""
    return [fold_word(w) for w in WORD_RE.findall(unicodedata.normalize("NFC", text))]


def normalize_key(text: str) -> str:
    """Case / punctuation / whitespace insensitive key used to avoid duplicate results."""
    return " ".join(tokenize(text))


# --------------------------------------------------------------------------- OCR cleaning
_QUOTE_MAP = str.maketrans({
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u2018": "'", "\u2019": "'",
    "\u2013": "-", "\u2014": "-", "\u2212": "-", "\u2026": "...",
})
_ARTIFACTS_RE = re.compile(r"[|_~^`{}\\*<>\u2022\u00b7\u25a0\u25a1\u25c6\u25ba\u25b6\u25aa\u25cf\u25cb\u00ab\u00bb]+")
_LONELY_SYMBOL_RE = re.compile(r"(?<!\S)[^\w\s.,;:!?()\"'%&/+-](?!\S)")


def clean_text(text: str) -> str:
    """Collapse whitespace / line breaks, keep meaningful punctuation, drop OCR artifacts."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text).replace("\u00ad", "")
    t = re.sub(r"(\w)-[ \t]*\n[ \t]*(\w)", r"\1\2", t)        # inform-\nation -> information
    t = t.translate(_QUOTE_MAP)
    t = re.sub(r"\s+", " ", t)
    t = _ARTIFACTS_RE.sub(" ", t)
    t = _LONELY_SYMBOL_RE.sub(" ", t)
    t = re.sub(r"\s+([.,;:!?%)])", r"\1", t)
    t = re.sub(r"\(\s+", "(", t)
    return re.sub(r"\s+", " ", t).strip()


# --------------------------------------------------------------------------- sentence splitting
_BOUNDARY_RE = re.compile(r"([.!?\u2026]+[\"'\u201d\u2019)\]]*)\s+")
_CLOSERS = "\"'\u201d\u2019)]"
_TERMINAL_END_RE = re.compile(r"[.!?\u2026][\"'\u201d\u2019)\]]*$")
_ABBREVIATIONS = frozenset({
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "inc", "ltd", "fig", "eq",
    "approx", "dept", "vol", "al", "e.g", "i.e", "cf", "viz",
})


def _starts_new_sentence(rest: str) -> bool:
    rest = rest.lstrip("\"'\u201c\u2018([")
    return bool(rest) and (rest[0].isupper() or rest[0].isdigit())


def split_sentences_with_offsets(text: str) -> list[tuple[str, int]]:
    """Returns [(sentence, start_offset)] for one logical block of text."""
    result: list[tuple[str, int]] = []
    start = 0

    def add(a: int, b: int) -> None:
        raw = text[a:b]
        stripped = raw.strip()
        if stripped:
            result.append((stripped, a + len(raw) - len(raw.lstrip())))

    for m in _BOUNDARY_RE.finditer(text):
        term = m.group(1)
        bare = term.rstrip(_CLOSERS)
        if set(bare) <= {"."}:
            if not _starts_new_sentence(text[m.end():]):
                continue
            if bare == ".":
                w = re.search(r"([\w.]+)$", text[start:m.start(1)])
                word = w.group(1).casefold() if w else ""
                if (word in _ABBREVIATIONS or (len(word) == 1 and word.isalpha())
                        or re.fullmatch(r"(?:[a-z]\.)+[a-z]", word)):
                    continue
        add(start, m.end(1))
        start = m.end()
    add(start, len(text))
    return result


def _continues(prev: str, cur: str) -> bool:
    """Is `cur` (a new physical line) a continuation of the sentence started on `prev`?"""
    if _TERMINAL_END_RE.search(prev):
        return False
    return cur[0].islower() or len(prev) >= 60      # hard-wrapped paragraph


def _logical_blocks(text: str) -> list[tuple[str, list[tuple[int, int]]]]:
    """Joins hard-wrapped lines. Returns [(block_text, [(char_offset, line_number), ...])]."""
    blocks: list[tuple[str, list[tuple[int, int]]]] = []
    buf, marks, last = "", [], ""

    def flush() -> None:
        nonlocal buf, marks, last
        if buf:
            blocks.append((buf, marks))
        buf, marks, last = "", [], ""

    for number, line in enumerate(text.split("\n"), 1):
        s = line.strip()
        if not s:
            flush()
            continue
        if buf and not _continues(last, s):
            flush()
        if buf:
            buf += " "
        marks.append((len(buf), number))
        buf += s
        last = s
    flush()
    return blocks


@dataclass(frozen=True, slots=True)
class Sentence:
    position: int       # 1-based sentence number in the file
    line_number: int    # physical line in text.txt where the sentence starts
    text: str
    key: str            # normalized text, used for de-duplication
    tokens: tuple       # folded words in their original order


def split_into_sentences(text: str) -> list[Sentence]:
    text = unicodedata.normalize("NFC", text.lstrip("\ufeff"))
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u2028", "\n").replace("\u2029", "\n")
    sentences: list[Sentence] = []
    for block, marks in _logical_blocks(text):
        offsets = [o for o, _ in marks]
        for sentence, offset in split_sentences_with_offsets(block):
            clean = re.sub(r"\s+", " ", sentence)
            tokens = tuple(tokenize(clean))
            key = " ".join(tokens)
            if not key:                                  # e.g. "-----"
                continue
            line = marks[max(bisect.bisect_right(offsets, offset) - 1, 0)][1]
            sentences.append(Sentence(len(sentences) + 1, line, clean, key, tokens))
    return sentences


# --------------------------------------------------------------------------- cached store
def _decode(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    for enc in ("utf-8-sig", "cp1250"):          # cp1250 (ANSI) contains all Turkmen letters: ä ň ž ý ş ç ö ü
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


@dataclass(frozen=True)
class Corpus:
    sentences: list
    index: dict            # folded word   -> sentence numbers (exact word search)
    prefix_index: dict     # first 4 chars -> sentence numbers (fuzzy / suffix tolerant search)


_EMPTY = Corpus([], {}, {})


class SentenceStore:
    """Reads text.txt once, splits it, builds word indexes and caches everything.
    The file is re-read automatically when its modification time / size / path changes."""

    def __init__(self, path_provider: Callable[[], Path]):
        self._path_provider = path_provider
        self._lock = threading.RLock()
        self._signature: tuple | None = None
        self._corpus = _EMPTY

    def ensure_loaded(self) -> Corpus:
        with self._lock:
            path = Path(self._path_provider())
            try:
                st = path.stat()
            except FileNotFoundError:
                self._reset()
                raise TextFileError(f"The text file was not found: {path}") from None
            except OSError as exc:
                self._reset()
                raise TextFileError(f"Cannot access the text file: {exc}") from exc
            signature = (str(path), st.st_mtime_ns, st.st_size)
            if signature != self._signature:
                self._load(path, signature)
            return self._corpus

    @property
    def sentence_count(self) -> int:
        return len(self._corpus.sentences)

    def _reset(self) -> None:
        self._signature, self._corpus = None, _EMPTY

    def _load(self, path: Path, signature: tuple) -> None:
        try:
            text = _decode(path.read_bytes())
        except OSError as exc:
            self._reset()
            raise TextFileError(f"Cannot read the text file: {exc}") from exc
        if not text.strip():
            self._reset()
            raise TextFileError(f"The text file is empty: {path.name}")
        sentences = split_into_sentences(text)
        if not sentences:
            self._reset()
            raise TextFileError(f"No sentences were found in {path.name}")
        index: dict[str, list[int]] = {}
        prefix: dict[str, list[int]] = {}
        for i, sentence in enumerate(sentences):
            for word in set(sentence.tokens):
                index.setdefault(word, []).append(i)
            for pre in {w[:PREFIX_LEN] for w in sentence.tokens}:
                prefix.setdefault(pre, []).append(i)
        self._corpus, self._signature = Corpus(sentences, index, prefix), signature
