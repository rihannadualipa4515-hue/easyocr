"""Sentence matching.

* match()        - word based search: Mode A (all words) / Mode B (at least one word)
* best_answers() - "question -> answer": ranks sentences by weighted word coverage, word ORDER and
                   word ADJACENCY, tolerant to Turkmen suffixes and small OCR mistakes.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from .text_processor import PREFIX_LEN, WORD_RE, SentenceStore, fold_word, tokenize

MODE_ALL = "all"
MODE_ANY = "any"
MODE_LABELS = {MODE_ALL: "All words match", MODE_ANY: "Partial word match"}

_STOP_EN = """
a about above after again against all am an and any are as at be because been before being below between
both but by can could did do does doing down during each few for from further had has have having he her here
hers him his how i if in into is it its itself just me more most my no nor not now of off on once only or other
our out over own same she should so some such than that the their them then there these they this those through
to too under until up very was we were what when where which while who whom why will with would you your yours
""".split()
# question words / particles that carry no content (Turkmen, Russian)
_STOP_TK = """nire nirede nireden nirä näme nämedir nämeler näçe näçenji näçinji näçeden nähili nädip nädogry
haýsy haýsylar haýsydyr haçan haçandyr kim kimdir kimiň kime kimden niçik niçe üçin bilen we ýa hem bu şu ol bir
ýaly diýen diýip""".split()
_STOP_RU = """что где кто когда как какой какая какое какие сколько почему зачем это и в на с по из от для или
а но не же ли чем чей куда откуда""".split()
STOPWORDS = frozenset(fold_word(w) for w in _STOP_EN + _STOP_TK + _STOP_RU)


def extract_keywords(text: str, min_length: int = 3) -> list[str]:
    """Unique meaningful (folded) words of the OCR text, in order of appearance."""
    unique = list(dict.fromkeys(tokenize(text)))
    meaningful = [w for w in unique
                  if w not in STOPWORDS and (len(w) >= min_length or (w.isdigit() and len(w) >= 2))]
    if not meaningful:                          # e.g. the screenshot only contains "to be or not"
        meaningful = [w for w in unique if len(w) >= 2]
    return meaningful


def answer_keywords(text: str) -> list[str]:
    """Content words of a question / phrase (question words and particles removed)."""
    return [w for w in dict.fromkeys(tokenize(text)) if w not in STOPWORDS and len(w) >= 2]


# ------------------------------------------------------------------ fuzzy word comparison
def _within_edits(a: str, b: str, k: int) -> bool:
    """Levenshtein distance <= k (early exit)."""
    if abs(len(a) - len(b)) > k:
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        if min(cur) > k:
            return False
        prev = cur
    return prev[-1] <= k


def tokens_match(a: str, b: str) -> bool:
    """Same word, same stem (Turkmen suffixes: Türkmenistanyň ~ Türkmenistan) or 1-2 OCR typos."""
    if a == b:
        return True
    m = min(len(a), len(b))
    if m < 4:
        return False
    p = 0
    while p < m and a[p] == b[p]:
        p += 1
    if p >= max(4, int(m * 0.7)):
        return True
    return (m >= 6 and _within_edits(a, b, 1)) or (m >= 9 and _within_edits(a, b, 2))


def highlight_spans(text: str, keywords) -> list[tuple[int, int]]:
    """Character ranges of the words in `text` that match one of the (folded) keywords."""
    spans = []
    for m in WORD_RE.finditer(text):
        w = fold_word(m.group())
        if any(tokens_match(k, w) for k in keywords):
            spans.append((m.start(), m.end()))
    return spans


# ------------------------------------------------------------------ results
@dataclass(frozen=True)
class MatchResult:
    position: int
    line_number: int
    text: str
    matched_words: tuple[str, ...]
    score: int


@dataclass
class MatchOutcome:
    mode: str
    keywords: list[str]
    total_found: int = 0
    results: list[MatchResult] = field(default_factory=list)


@dataclass(frozen=True)
class AnswerResult:
    position: int
    line_number: int
    text: str
    score: float        # 0..1
    coverage: float     # 0..1 share of the (rarity weighted) question words found


class SentenceMatcher:
    def __init__(self, store: SentenceStore):
        self.store = store

    # -------------------------------------------------------------- Mode A / Mode B
    def match(self, cleaned_text: str, mode: str = MODE_ALL, min_word_length: int = 3,
              max_results: int = 500) -> MatchOutcome:
        corpus = self.store.ensure_loaded()                # reloads text.txt only if it changed
        sentences, index = corpus.sentences, corpus.index
        mode = mode if mode in (MODE_ALL, MODE_ANY) else MODE_ALL
        keywords = extract_keywords(cleaned_text, min_word_length)
        outcome = MatchOutcome(mode=mode, keywords=keywords)
        if not keywords:
            return outcome

        postings = [index.get(w) for w in keywords]
        if mode == MODE_ALL:
            if any(p is None for p in postings):
                return outcome
            postings.sort(key=len)
            candidates = set(postings[0])
            for p in postings[1:]:
                candidates.intersection_update(p)
                if not candidates:
                    return outcome
            scores = {i: len(keywords) for i in candidates}
        else:
            counter: Counter[int] = Counter()
            for p in postings:
                if p:
                    counter.update(p)
            scores = dict(counter)

        seen: set[str] = set()
        for i in sorted(scores, key=lambda n: (-scores[n], n)):
            sentence = sentences[i]
            if sentence.key in seen:                       # avoid duplicate results
                continue
            seen.add(sentence.key)
            outcome.total_found += 1
            if len(outcome.results) < max_results:
                present = set(sentence.tokens)
                words = tuple(w for w in keywords if w in present)
                outcome.results.append(MatchResult(sentence.position, sentence.line_number,
                                                   sentence.text, words, scores[i]))
        return outcome

    # -------------------------------------------------------------- question -> answer
    def best_answers(self, cleaned_text: str, top_n: int = 3, min_coverage: float = 0.5) -> list[AnswerResult]:
        corpus = self.store.ensure_loaded()
        q = answer_keywords(cleaned_text)
        if not q or top_n < 1:
            return []
        sentences, n = corpus.sentences, len(corpus.sentences)

        candidates: set[int] = set()
        weights = []
        for w in q:
            hits = corpus.prefix_index.get(w[:PREFIX_LEN])
            weights.append(math.log(1 + n / max(len(hits) if hits else 1, 1)))    # rare words weigh more
            if hits:
                candidates.update(hits)
        total_weight = sum(weights) or 1.0

        scored: list[tuple[float, int, float]] = []
        for i in candidates:
            tokens = sentences[i].tokens
            occ = [[j for j, t in enumerate(tokens) if tokens_match(w, t)] for w in q]
            matched = [k for k, o in enumerate(occ) if o]
            if not matched:
                continue
            coverage = sum(weights[k] for k in matched) / total_weight
            if coverage < min_coverage:
                continue
            if len(q) > 1:                                  # question words that stand next to each other
                pairs = 0
                for k in range(len(q) - 1):
                    if occ[k] and occ[k + 1]:
                        nxt = set(occ[k + 1])
                        pairs += any(j + 1 in nxt for j in occ[k])
                adjacency = pairs / (len(q) - 1)
            else:
                adjacency = 1.0
            cur, chain = -1, 0                              # question words in the same order
            for k in matched:
                pos = next((j for j in occ[k] if j > cur), None)
                if pos is not None:
                    chain += 1
                    cur = pos
            order = chain / len(matched)
            hit_positions = {j for o in occ for j in o}
            density = min(1.0, len(hit_positions) / max(len(tokens), 1))
            scored.append((0.6 * coverage + 0.2 * adjacency + 0.1 * order + 0.1 * density, i, coverage))

        scored.sort(key=lambda x: (-x[0], x[1]))
        answers: list[AnswerResult] = []
        seen: set[str] = set()
        for score, i, coverage in scored:
            s = sentences[i]
            if s.key in seen:
                continue
            seen.add(s.key)
            answers.append(AnswerResult(s.position, s.line_number, s.text, round(score, 4), round(coverage, 4)))
            if len(answers) >= top_n:
                break
        return answers
