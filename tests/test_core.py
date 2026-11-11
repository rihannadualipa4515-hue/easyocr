import os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from finder.database import Database
from finder.errors import TextFileError
from finder.services.sentence_matcher import MODE_ALL, MODE_ANY, SentenceMatcher, extract_keywords
from finder.services.sentence_matcher import answer_keywords, highlight_spans
from finder.services.text_processor import SentenceStore, clean_text, split_into_sentences, tokenize

SPEC = ("Information security is important in modern networks.\n"
        "Network security protects information.\n"
        "Cybersecurity includes many different technologies.\n"
        "Information security specialists protect computer systems.\n")


def make_store(text):
    d = tempfile.mkdtemp()
    p = Path(d) / "text.txt"
    p.write_text(text, encoding="utf-8")
    return SentenceStore(lambda: p), p


class TextTests(unittest.TestCase):
    def test_split_example(self):
        s = split_into_sentences("Python is a programming language. Django is a web framework. Python can be used for automation.")
        self.assertEqual([x.text for x in s], ["Python is a programming language.", "Django is a web framework.",
                                              "Python can be used for automation."])

    def test_abbreviation_and_wrap(self):
        s = split_into_sentences("Dr. Smith came here. He left\nlater in the day.\n\nNew paragraph here.")
        self.assertEqual(len(s), 3)
        self.assertEqual(s[1].text, "He left later in the day.")
        self.assertEqual([x.line_number for x in s], [1, 1, 4])

    def test_clean(self):
        self.assertEqual(clean_text("Hello ,  world |\n inform-\nation  ~ is  good ."), "Hello, world information is good.")


class MatchTests(unittest.TestCase):
    def test_modes(self):
        store, _ = make_store(SPEC)
        m = SentenceMatcher(store)
        a = m.match("information security", MODE_ALL)
        self.assertEqual([r.position for r in a.results], [1, 2, 4])
        b = m.match("information cybersecurity", MODE_ANY)
        self.assertEqual(sorted(r.position for r in b.results), [1, 2, 3, 4])
        self.assertEqual(m.match("quantum", MODE_ANY).total_found, 0)

    def test_case_punct_and_whole_word(self):
        store, _ = make_store("Security matters.\nInsecurity is bad.\n")
        r = SentenceMatcher(store).match("SECURITY!!!", MODE_ANY)
        self.assertEqual([x.position for x in r.results], [1])        # not a substring match

    def test_duplicates_removed(self):
        store, _ = make_store("Python rocks.\nPython   rocks!\nOther line here.\n")
        self.assertEqual(SentenceMatcher(store).match("python", MODE_ANY).total_found, 1)

    def test_reload_on_change_and_errors(self):
        store, p = make_store("Alpha beta gamma.\n")
        m = SentenceMatcher(store)
        self.assertEqual(m.match("delta", MODE_ANY).total_found, 0)
        p.write_text("Alpha beta gamma.\nDelta appears here.\n", encoding="utf-8")
        os.utime(p, (p.stat().st_atime, p.stat().st_mtime + 5))
        self.assertEqual(m.match("delta", MODE_ANY).total_found, 1)
        p.write_text("   \n", encoding="utf-8")
        os.utime(p, (p.stat().st_atime, p.stat().st_mtime + 10))
        with self.assertRaises(TextFileError):
            m.match("delta")
        p.unlink()
        with self.assertRaises(TextFileError):
            m.match("delta")

    def test_keywords(self):
        self.assertEqual(extract_keywords("The security of the network"), ["security", "network"])


class DbTests(unittest.TestCase):
    def test_crud_search(self):
        db = Database(Path(tempfile.mkdtemp()) / "t.db")
        cid = db.add_capture("Orig", "clean text", "screenshots/a.png", "all", [(1, 1, "Found sentence 100%.")])
        db.add_capture("x", "other", None, "any", [])
        self.assertEqual(len(db.list_captures()), 2)
        self.assertEqual(len(db.list_captures("clean")), 1)
        self.assertEqual(len(db.list_captures("100%")), 1)
        self.assertEqual(len(db.get_matches(cid)), 1)
        self.assertEqual(db.delete_capture(cid), "screenshots/a.png")
        self.assertEqual(len(db.get_matches(cid)), 0)


class AnswerTests(unittest.TestCase):
    TK = ("Aşgabat şäheri örän uly.\n"
          "Türkmenistanyň paýtagty Aşgabat şäheridir.\n"
          "Daşoguz welaýaty demirgazykda ýerleşýär.\n"
          "Paýtagt barada köp kitap ýazylypdyr.\n")

    def test_fold(self):
        self.assertEqual(tokenize("Türkmenistanyň PAÝTAGTY"), ["turkmenistanyn", "paytagty"])
        self.assertEqual(answer_keywords("Türkmenistanyň paýtagty nire?"), ["turkmenistanyn", "paytagty"])

    def test_turkmen_question(self):
        store, _ = make_store(self.TK)
        ans = SentenceMatcher(store).best_answers("Türkmenistanyň paytagty nire?")
        self.assertEqual(ans[0].position, 2)
        self.assertTrue(ans[0].score > 0.9)

    def test_suffix_and_ocr_typo(self):
        store, _ = make_store(self.TK)
        m = SentenceMatcher(store)
        self.assertEqual(m.best_answers("Türkmenistan paytagty näme?")[0].position, 2)   # suffix dropped
        self.assertEqual(m.best_answers("Türkmenistanyn paytagtv nire")[0].position, 2)  # OCR typo

    def test_order_and_adjacency_win(self):
        store, _ = make_store("Python is used with Django daily.\nDjango is a web framework written in Python.\n"
                              "Python web framework Django is popular.\n")
        ans = SentenceMatcher(store).best_answers("web framework", top_n=3, min_coverage=0.5)
        self.assertEqual({a.position for a in ans}, {2, 3})
        self.assertEqual(SentenceMatcher(store).best_answers("kubernetes cluster"), [])

    def test_highlight(self):
        spans = highlight_spans("Türkmenistanyň paýtagty Aşgabat", ["turkmenistanyn", "paytagty"])
        self.assertEqual(len(spans), 2)

    def test_all_turkmen_letters_fold(self):
        self.assertEqual(tokenize("äçžňöşüý ÄÇŽŇÖŞÜÝ"), ["acznosuy", "acznosuy"])
        self.assertEqual(tokenize("y\u0301 n\u030c"), ["y", "n"])            # decomposed (NFD) input

    def test_ascii_ocr_output_still_matches(self):
        store, _ = make_store("Türkmenistanyň paýtagty Aşgabat şäheridir.\nÇärjew şäheri Amyderýanyň boýunda ýerleşýär.\n"
                              "Köpetdag daglary Ýaýlada ýerleşýär.\n")
        m = SentenceMatcher(store)
        for q in ("Turkmenistanyn paytagty nire?", "TÜRKMENISTANYŇ PAÝTAGTY NIRE?", "Turkmenistanyň paýtagty"):
            self.assertEqual(m.best_answers(q)[0].position, 1, q)
        self.assertEqual(m.best_answers("Carjew saheri Amyderya")[0].position, 2)
        self.assertEqual(m.match("koepetdag dag", MODE_ANY).total_found, 0)   # not a Turkmen spelling
        self.assertEqual(m.match("Kopetdag daglary", MODE_ALL).total_found, 1)
        self.assertEqual(m.match("YAYLADA", MODE_ANY).results[0].position, 3)

    def test_two_typos_in_long_word(self):
        from finder.services.sentence_matcher import tokens_match
        self.assertTrue(tokens_match("dowletmanlyk", "dowletmenlik"))
        self.assertFalse(tokens_match("dowletmanlyk", "kitapmanlyk"))

    def test_history_search_ignores_diacritics(self):
        db = Database(Path(tempfile.mkdtemp()) / "h.db")
        db.add_capture("Türkmenistanyň PAÝTAGTY nire?", "Türkmenistanyň paýtagty nire?", None, "all", [])
        for q in ("paytagty", "PAÝTAGTY", "turkmenistanyn paytagty", "Türkmenistanyň"):
            self.assertEqual(len(db.list_captures(q)), 1, q)
        self.assertEqual(len(db.list_captures("Aşgabat")), 0)

    def test_ansi_cp1250_text_file(self):
        d = Path(tempfile.mkdtemp()) / "text.txt"
        d.write_bytes("Türkmenistanyň paýtagty Aşgabat şäheridir. Ýaňy ňŋž.\n".encode("cp1250", errors="replace"))
        store = SentenceStore(lambda: d)
        self.assertIn("paýtagty", store.ensure_loaded().sentences[0].text)

    def test_db_answers_and_migration(self):
        import sqlite3
        path = Path(tempfile.mkdtemp()) / "old.db"
        con = sqlite3.connect(path)       # database created by the previous version
        con.executescript("CREATE TABLE captured_text (id INTEGER PRIMARY KEY AUTOINCREMENT, original_text TEXT, "
                          "cleaned_text TEXT, screenshot TEXT, match_mode TEXT, created_at TEXT);"
                          "CREATE TABLE found_sentence (id INTEGER PRIMARY KEY AUTOINCREMENT, capture_id INTEGER, "
                          "line_number INTEGER, position INTEGER, sentence TEXT);")
        con.close()
        db = Database(path)
        cid = db.add_capture("o", "c", None, "all", [(1, 1, "plain")], [(2, 2, "answer", 0.9)])
        rows = db.get_matches(cid)
        self.assertEqual([(r["is_best"], r["sentence"]) for r in rows], [(0, "plain"), (1, "answer")])
        self.assertEqual(db.list_captures()[0]["match_count"], 1)


if __name__ == "__main__":
    unittest.main()
