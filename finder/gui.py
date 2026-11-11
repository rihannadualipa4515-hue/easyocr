"""Tkinter dashboard: Dashboard / History / Settings."""
from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import ImageTk
from PIL import Image

from . import __version__
from .config import (DATA_DIR, DB_PATH, IMAGE_FILETYPES, MODELS_DIR, SCREENSHOT_DIR, Settings,
                     resolve_path, to_stored_path)
from .database import Database
from .errors import AppError
from .pipeline import Pipeline
from .services.clipboard_monitor import ClipboardMonitor
from .services.ocr_engine import OCREngine
from .services.screenshot_capture import load_image_file
from .services.sentence_matcher import (MODE_ALL, MODE_ANY, MODE_LABELS, SentenceMatcher, answer_keywords,
                                        extract_keywords, highlight_spans)
from .services.text_processor import SentenceStore

log = logging.getLogger(__name__)
FONT = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
ACCENT = "#2563eb"


# =============================================================================== result view
def split_rows(rows):
    """DB rows -> (best answers sorted by score, ordinary matching sentences)."""
    answers = sorted([r for r in rows if r["is_best"]], key=lambda r: -r["score"])
    return answers, [r for r in rows if not r["is_best"]]


class ResultView(ttk.Frame):
    """Screenshot preview + best answer + OCR texts + matching sentences (Dashboard and History)."""
    PREVIEW = (360, 320)

    def __init__(self, master):
        super().__init__(master)
        self._photo = None
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        self.info_var = tk.StringVar(value="Waiting for a screenshot...")
        ttk.Label(self, textvariable=self.info_var, font=FONT_BOLD).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 4))

        left = ttk.LabelFrame(self, text="Screenshot")
        left.grid(row=1, column=0, sticky="nsew", padx=(8, 4), pady=4)
        self.preview = ttk.Label(left, text="No screenshot yet", anchor="center")
        self.preview.pack(padx=6, pady=6)

        right = ttk.Frame(self)
        right.grid(row=1, column=1, sticky="nsew", padx=(4, 8), pady=4)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(3, weight=1)

        # --- best answer panel (the sentence from text.txt that answers the captured text)
        self.answer_frame = ttk.LabelFrame(right, text="Answer from text.txt")
        self.answer_frame.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.answer = self._text(self.answer_frame, 6)
        self.answer.configure(background="#f0fdf4")
        a = self.answer
        a.tag_configure("meta", font=("Segoe UI", 9, "bold"), foreground="#6b7280", spacing1=4, lmargin1=8, lmargin2=8)
        a.tag_configure("best", font=("Segoe UI", 15, "bold"), foreground="#065f46", lmargin1=8, lmargin2=8, spacing3=6)
        a.tag_configure("alt", font=("Segoe UI", 11), foreground="#1f2937", lmargin1=8, lmargin2=8, spacing3=4)
        a.tag_configure("hl", background="#fde68a")
        a.tag_configure("empty", font=("Segoe UI", 11, "italic"), foreground="#6b7280", lmargin1=8, spacing1=8)

        self.original_box = self._box(right, "Original OCR text", 1, 3)
        self.cleaned_box = self._box(right, "Cleaned OCR text", 2, 3)
        self.match_frame = ttk.LabelFrame(right, text="Matching sentences (0)")
        self.match_frame.grid(row=3, column=0, sticky="nsew", pady=(4, 0))
        self.matches = self._text(self.match_frame, 8)
        m = self.matches
        m.tag_configure("head", font=("Segoe UI", 9, "bold"), foreground=ACCENT, spacing1=8, lmargin1=8, lmargin2=8)
        m.tag_configure("body", font=("Segoe UI", 11), lmargin1=16, lmargin2=16, spacing3=6)
        m.tag_configure("hl", background="#fde68a")
        m.tag_configure("sep", foreground="#d1d5db", lmargin1=8)
        m.tag_configure("empty", font=("Segoe UI", 11, "italic"), foreground="#6b7280", lmargin1=12, spacing1=10)
        m.tag_configure("error", font=("Segoe UI", 10), foreground="#b91c1c", lmargin1=12, lmargin2=12, spacing1=10)

    # -- helpers
    def _text(self, parent, height):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True, padx=4, pady=4)
        text = tk.Text(frame, wrap="word", height=height, font=("Segoe UI", 10), relief="flat",
                       borderwidth=0, highlightthickness=1, highlightbackground="#d1d5db", state="disabled")
        bar = ttk.Scrollbar(frame, command=text.yview)
        text.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        return text

    def _box(self, parent, title, row, height):
        lf = ttk.LabelFrame(parent, text=title)
        lf.grid(row=row, column=0, sticky="ew", pady=(0, 4))
        return self._text(lf, height)

    @staticmethod
    def _set(widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _show_preview(self, path) -> None:
        try:
            img = Image.open(path)
            img.thumbnail(self.PREVIEW)
            self._photo = ImageTk.PhotoImage(img)
            self.preview.configure(image=self._photo, text="")
        except Exception:                                                  # noqa: BLE001
            self._photo = None
            self.preview.configure(image="", text="Screenshot file not found")

    # -- public
    def clear(self) -> None:
        self.info_var.set("Waiting for a screenshot...")
        self._photo = None
        self.preview.configure(image="", text="No screenshot yet")
        self._set(self.original_box, "")
        self._set(self.cleaned_box, "")
        self._set(self.answer, "")
        self.match_frame.configure(text="Matching sentences (0)")
        self._set(self.matches, "")

    def _render_answers(self, answers, a_keywords, error) -> None:
        w = self.answer
        w.configure(state="normal")
        w.delete("1.0", "end")
        if error:
            w.insert("end", "Not available (see the message below).\n", "empty")
        elif not answers:
            w.insert("end", "No matching answer found in text.txt.\n", "empty")
        else:
            for rank, ans in enumerate(answers):
                label = "BEST MATCH" if rank == 0 else f"Alternative {rank}"
                w.insert("end", f"{label}   {int(round(ans['score'] * 100))}%   line {ans['line_number']}\n", "meta")
                start = w.index("end-1c")
                w.insert("end", ans["sentence"] + "\n", "best" if rank == 0 else "alt")
                for s0, e0 in highlight_spans(ans["sentence"], a_keywords):
                    w.tag_add("hl", f"{start}+{s0}c", f"{start}+{e0}c")
        w.configure(state="disabled")
        w.yview_moveto(0)

    def show(self, capture, matches, keywords, answers=(), answer_kw=(), total=None, error=None) -> None:
        total = len(matches) if total is None else total
        mode = MODE_LABELS.get(capture["match_mode"], capture["match_mode"])
        self.info_var.set(f"Captured: {capture['created_at']}     Mode: {mode}     Matching sentences: {total}")
        self._set(self.original_box, capture["original_text"])
        self._set(self.cleaned_box, capture["cleaned_text"])
        if capture["screenshot"]:
            self._show_preview(resolve_path(capture["screenshot"]))
        else:
            self._photo = None
            self.preview.configure(image="", text="No screenshot saved")
        self._render_answers(answers, answer_kw, error)
        self.match_frame.configure(text=f"Matching sentences ({total})")

        w = self.matches
        w.configure(state="normal")
        w.delete("1.0", "end")
        if error:
            w.insert("end", f"Matching was not possible: {error}\n", "error")
        elif not matches:
            w.insert("end", "No matching sentences found.\n", "empty")
        else:
            for i, m in enumerate(matches, 1):
                w.insert("end", f"#{i}   line {m['line_number']}   sentence {m['position']}\n", "head")
                start = w.index("end-1c")
                sentence = m["sentence"]
                w.insert("end", sentence + "\n", "body")
                for s0, e0 in highlight_spans(sentence, keywords):
                    w.tag_add("hl", f"{start}+{s0}c", f"{start}+{e0}c")
                w.insert("end", "-" * 90 + "\n", "sep")
            if total > len(matches):
                w.insert("end", f"\nShowing the first {len(matches)} of {total} matching sentences.\n", "empty")
        w.configure(state="disabled")
        w.yview_moveto(0)


# =============================================================================== application
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"OCR Text Finder {__version__}")
        self.geometry("1200x780")
        self.minsize(980, 640)

        DATA_DIR.mkdir(exist_ok=True)
        SCREENSHOT_DIR.mkdir(exist_ok=True)
        self.settings = Settings()
        self.db = Database(DB_PATH)
        self.store = SentenceStore(lambda: resolve_path(self.settings["text_file"]))
        self.matcher = SentenceMatcher(self.store)
        self.ocr = OCREngine(self.settings["ocr_languages"], self.settings["use_gpu"], MODELS_DIR)
        self.pipeline = Pipeline(self.settings, self.db, self.ocr, self.matcher)
        self.ui_queue: queue.Queue = queue.Queue()
        self.jobs: queue.Queue = queue.Queue()
        self.monitor = ClipboardMonitor(self._on_clipboard_image, lambda m: self.ui_queue.put(("error", m)))
        self.dash_capture_id: int | None = None

        self._style()
        self._build_ui()

        threading.Thread(target=self._worker, daemon=True, name="ocr-worker").start()
        threading.Thread(target=self._warm_up, daemon=True, name="ocr-warmup").start()
        if self.settings["monitor_clipboard"]:
            self.monitor.start()
        self._sync_monitor_button()
        self._refresh_history()
        self._check_text_file()
        self.after(120, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ UI construction
    def _style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("vista" if "vista" in style.theme_names() else "clam")
        style.configure(".", font=FONT)
        style.configure("Treeview", rowheight=24)
        style.configure("Title.TLabel", font=("Segoe UI", 15, "bold"), foreground=ACCENT)
        style.configure("Hint.TLabel", foreground="#6b7280")

    def _build_ui(self) -> None:
        header = ttk.Frame(self)
        header.pack(fill="x", padx=12, pady=(10, 4))
        ttk.Label(header, text="OCR Text Finder", style="Title.TLabel").pack(side="left")
        self.monitor_btn = ttk.Button(header, command=self._toggle_monitor)
        self.monitor_btn.pack(side="right")
        ttk.Button(header, text="Open image...", command=self._open_image).pack(side="right", padx=6)
        ttk.Label(self, style="Hint.TLabel",
                  text="Press WIN + SHIFT + S, select an area - the text is recognised and matched automatically."
                  ).pack(anchor="w", padx=14)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=8)
        self.tab_dash = ttk.Frame(self.notebook)
        self.tab_hist = ttk.Frame(self.notebook)
        self.tab_sett = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_dash, text="  Dashboard  ")
        self.notebook.add(self.tab_hist, text="  History  ")
        self.notebook.add(self.tab_sett, text="  Settings  ")

        self.dash_view = ResultView(self.tab_dash)
        self.dash_view.pack(fill="both", expand=True)
        self._build_history()
        self._build_settings()

        self.status_var = tk.StringVar(value="Starting...")
        self.status_lbl = ttk.Label(self, textvariable=self.status_var, relief="sunken", anchor="w", padding=(8, 3))
        self.status_lbl.pack(fill="x", side="bottom")

    def _build_history(self) -> None:
        top = ttk.Frame(self.tab_hist)
        top.pack(fill="x", padx=8, pady=8)
        self.search_var = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.search_var, width=40)
        entry.pack(side="left")
        entry.bind("<Return>", lambda _e: self._refresh_history())
        ttk.Button(top, text="Search", command=self._refresh_history).pack(side="left", padx=4)
        ttk.Button(top, text="Clear", command=lambda: (self.search_var.set(""), self._refresh_history())).pack(side="left")
        ttk.Button(top, text="Delete selected", command=self._delete_selected).pack(side="right")

        pane = ttk.PanedWindow(self.tab_hist, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        left = ttk.Frame(pane)
        pane.add(left, weight=1)
        cols = ("id", "date", "text", "matches")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
        for col, title, width in (("id", "ID", 45), ("date", "Date / time", 135),
                                  ("text", "Recognised text", 200), ("matches", "Found", 50)):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, anchor="w" if col == "text" else "center", stretch=(col == "text"))
        bar = ttk.Scrollbar(left, command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_history_select)
        self.hist_view = ResultView(pane)
        pane.add(self.hist_view, weight=3)

    def _build_settings(self) -> None:
        s = self.settings
        f = ttk.Frame(self.tab_sett, padding=20)
        f.pack(anchor="nw")
        self.v_file = tk.StringVar(value=s["text_file"])
        self.v_mode = tk.StringVar(value=s["match_mode"])
        self.v_min = tk.IntVar(value=s["min_word_length"])
        self.v_max = tk.IntVar(value=s["max_results"])
        self.v_ans = tk.IntVar(value=s["answer_count"])
        self.v_cov = tk.IntVar(value=int(round(s["answer_min_coverage"] * 100)))
        self.v_lang = tk.StringVar(value=",".join(s["ocr_languages"]))
        self.v_gpu = tk.BooleanVar(value=s["use_gpu"])
        self.v_mon = tk.BooleanVar(value=s["monitor_clipboard"])
        self.v_front = tk.BooleanVar(value=s["bring_to_front"])

        ttk.Label(f, text="Text file (text.txt):", font=FONT_BOLD).grid(row=0, column=0, sticky="w", pady=6)
        row = ttk.Frame(f)
        row.grid(row=0, column=1, sticky="w", padx=10)
        ttk.Entry(row, textvariable=self.v_file, width=60).pack(side="left")
        ttk.Button(row, text="Browse...", command=self._browse_text).pack(side="left", padx=4)

        ttk.Label(f, text="Matching mode:", font=FONT_BOLD).grid(row=1, column=0, sticky="nw", pady=6)
        modes = ttk.Frame(f)
        modes.grid(row=1, column=1, sticky="w", padx=10)
        ttk.Radiobutton(modes, variable=self.v_mode, value=MODE_ALL,
                        text="Mode A - sentence must contain ALL meaningful words").pack(anchor="w")
        ttk.Radiobutton(modes, variable=self.v_mode, value=MODE_ANY,
                        text="Mode B - sentence must contain AT LEAST ONE meaningful word").pack(anchor="w")

        ttk.Label(f, text="Minimum word length:", font=FONT_BOLD).grid(row=2, column=0, sticky="w", pady=6)
        ttk.Spinbox(f, from_=1, to=10, textvariable=self.v_min, width=6).grid(row=2, column=1, sticky="w", padx=10)
        ttk.Label(f, text="Max. results per capture:", font=FONT_BOLD).grid(row=3, column=0, sticky="w", pady=6)
        ttk.Spinbox(f, from_=10, to=5000, increment=50, textvariable=self.v_max, width=8).grid(row=3, column=1, sticky="w", padx=10)
        ttk.Label(f, text="OCR languages:", font=FONT_BOLD).grid(row=4, column=0, sticky="w", pady=6)
        lang = ttk.Frame(f)
        lang.grid(row=4, column=1, sticky="w", padx=10)
        ttk.Entry(lang, textvariable=self.v_lang, width=20).pack(side="left")
        ttk.Label(lang, text="  comma separated EasyOCR codes, e.g. en  or  en,ru", style="Hint.TLabel").pack(side="left")

        ttk.Label(f, text="Answers to show:", font=FONT_BOLD).grid(row=5, column=0, sticky="w", pady=6)
        ans = ttk.Frame(f)
        ans.grid(row=5, column=1, sticky="w", padx=10)
        ttk.Spinbox(ans, from_=1, to=10, textvariable=self.v_ans, width=6).pack(side="left")
        ttk.Label(ans, text="  best sentences from text.txt for the captured question", style="Hint.TLabel").pack(side="left")
        ttk.Label(f, text="Minimum word coverage (%):", font=FONT_BOLD).grid(row=6, column=0, sticky="w", pady=6)
        cov = ttk.Frame(f)
        cov.grid(row=6, column=1, sticky="w", padx=10)
        ttk.Spinbox(cov, from_=10, to=100, increment=5, textvariable=self.v_cov, width=6).pack(side="left")
        ttk.Label(cov, text="  share of the question words an answer sentence must contain", style="Hint.TLabel").pack(side="left")

        ttk.Checkbutton(f, text="Watch the clipboard for screenshots (WIN+SHIFT+S)", variable=self.v_mon).grid(
            row=7, column=1, sticky="w", padx=10, pady=(10, 0))
        ttk.Checkbutton(f, text="Bring the window to the front after a capture", variable=self.v_front).grid(
            row=8, column=1, sticky="w", padx=10)
        ttk.Checkbutton(f, text="Use GPU for OCR (needs CUDA-enabled PyTorch)", variable=self.v_gpu).grid(
            row=9, column=1, sticky="w", padx=10)

        btns = ttk.Frame(f)
        btns.grid(row=10, column=1, sticky="w", padx=10, pady=18)
        ttk.Button(btns, text="Save settings", command=self._save_settings).pack(side="left")
        ttk.Button(btns, text="Reload text file", command=lambda: self._check_text_file(announce=True)).pack(side="left", padx=8)
        self.file_info = ttk.Label(f, text="", style="Hint.TLabel")
        self.file_info.grid(row=11, column=1, sticky="w", padx=10)

    # ------------------------------------------------------------------ background work
    def _on_clipboard_image(self, image) -> None:
        self.ui_queue.put(("busy", None))
        self.jobs.put(image)

    def _warm_up(self) -> None:
        self.ui_queue.put(("status", "Loading the OCR model (the first start can take a while)..."))
        try:
            self.ocr.warm_up()
            log.info("OCR model ready")
            self.ui_queue.put(("ready", None))
        except AppError as exc:
            self.ui_queue.put(("error", str(exc)))

    def _worker(self) -> None:
        while True:
            image = self.jobs.get()
            if image is None:
                return
            try:
                log.info("Processing an image (%sx%s)", *image.size)
                result = self.pipeline.process(image)
                log.info("Capture %s saved, %s matching sentences", result.capture_id, result.total_found)
                self.ui_queue.put(("result", result))
            except AppError as exc:
                self.ui_queue.put(("error", str(exc)))
            except Exception as exc:                                       # noqa: BLE001
                log.exception("Unexpected failure while processing a capture")
                self.ui_queue.put(("error", f"Unexpected error: {exc}"))

    def _poll(self) -> None:
        try:
            while True:
                try:
                    kind, payload = self.ui_queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    self._handle(kind, payload)
                except Exception as exc:                                   # noqa: BLE001
                    log.exception("UI update failed")
                    self._set_status(f"Display error: {type(exc).__name__}: {exc}", error=True)
        finally:
            self.after(120, self._poll)         # never stop polling, whatever happens

    def _handle(self, kind, payload) -> None:
        if kind == "status":
            self._set_status(payload)
        elif kind == "error":
            self._set_status(payload, error=True)
        elif kind == "busy":
            self._set_status("Image received - recognising text (the first one may take a minute)...")
        elif kind == "ready":
            self._set_status("Ready. Press WIN + SHIFT + S to capture text.")
        elif kind == "result":
            self._on_result(payload)

    def _on_result(self, res) -> None:
        try:
            capture = self.db.get_capture(res.capture_id)
            answers, matches = split_rows(self.db.get_matches(res.capture_id))
        except AppError as exc:
            self._set_status(str(exc), error=True)
            return
        self.dash_capture_id = res.capture_id
        self.dash_view.show(capture, matches, res.keywords, answers, res.answer_keywords,
                            res.total_found, res.match_error)
        self._refresh_history()
        self.notebook.select(self.tab_dash)
        if res.match_error:
            self._set_status(f"Text recognised and saved, but matching failed: {res.match_error}", error=True)
        elif answers:
            self._set_status(f"Answer found (line {answers[0]['line_number']}). "
                             f"{res.total_found} sentence(s) contain the recognised words.")
        else:
            self._set_status(f"No direct answer found. {res.total_found} sentence(s) contain the recognised words.")
        if self.settings["bring_to_front"]:
            self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
            self.after(400, lambda: self.attributes("-topmost", False))

    def _set_status(self, text: str, error: bool = False) -> None:
        self.status_var.set(text)
        self.status_lbl.configure(foreground="#b91c1c" if error else "#111827")

    # ------------------------------------------------------------------ actions
    def _sync_monitor_button(self) -> None:
        self.monitor_btn.configure(text="Monitoring: ON  (click to pause)" if self.monitor.running
                                   else "Monitoring: OFF  (click to start)")

    def _toggle_monitor(self) -> None:
        if self.monitor.running:
            self.monitor.stop()
        else:
            self.monitor.start()
        self.settings["monitor_clipboard"] = self.monitor.running
        self.v_mon.set(self.monitor.running)
        try:
            self.settings.save()
        except OSError:
            pass
        self.after(100, self._sync_monitor_button)

    def _open_image(self) -> None:
        path = filedialog.askopenfilename(title="Select an image", filetypes=IMAGE_FILETYPES)
        if not path:
            return
        try:
            image = load_image_file(path)
        except AppError as exc:
            self._set_status(str(exc), error=True)
            return
        self.ui_queue.put(("busy", None))
        self.jobs.put(image)

    def _check_text_file(self, announce: bool = False) -> None:
        try:
            self.store.ensure_loaded()
            msg = f"{self.store.sentence_count} sentences loaded from {resolve_path(self.settings['text_file']).name}"
            self.file_info.configure(text=msg, foreground="#166534")
            if announce:
                self._set_status(msg)
        except AppError as exc:
            self.file_info.configure(text=str(exc), foreground="#b91c1c")
            self._set_status(str(exc), error=True)

    def _browse_text(self) -> None:
        path = filedialog.askopenfilename(title="Select text file", filetypes=[("Text", "*.txt"), ("All files", "*.*")])
        if path:
            from pathlib import Path
            self.v_file.set(to_stored_path(Path(path)))

    def _save_settings(self) -> None:
        try:
            min_len, max_res = int(self.v_min.get()), int(self.v_max.get())
            ans_n, cov = int(self.v_ans.get()), int(self.v_cov.get())
        except (tk.TclError, ValueError):
            messagebox.showerror("Settings", "Word length and result limit must be numbers.")
            return
        langs = [x.strip() for x in self.v_lang.get().split(",") if x.strip()]
        if not langs or not self.v_file.get().strip():
            messagebox.showerror("Settings", "Text file and OCR language cannot be empty.")
            return
        s = self.settings
        s["text_file"], s["match_mode"] = self.v_file.get().strip(), self.v_mode.get()
        s["min_word_length"], s["max_results"] = max(1, min_len), max(1, max_res)
        s["answer_count"], s["answer_min_coverage"] = max(1, ans_n), min(100, max(0, cov)) / 100
        s["ocr_languages"], s["use_gpu"] = langs, self.v_gpu.get()
        s["monitor_clipboard"], s["bring_to_front"] = self.v_mon.get(), self.v_front.get()
        try:
            s.save()
        except OSError as exc:
            messagebox.showerror("Settings", f"Cannot save settings: {exc}")
            return
        self.ocr.configure(langs, self.v_gpu.get())
        threading.Thread(target=self._warm_up, daemon=True).start()
        if s["monitor_clipboard"] and not self.monitor.running:
            self.monitor.start()
        elif not s["monitor_clipboard"] and self.monitor.running:
            self.monitor.stop()
        self.after(100, self._sync_monitor_button)
        self._check_text_file()
        self._set_status("Settings saved.")

    # ------------------------------------------------------------------ history
    def _refresh_history(self) -> None:
        try:
            rows = self.db.list_captures(self.search_var.get())
        except AppError as exc:
            self._set_status(str(exc), error=True)
            return
        self.tree.delete(*self.tree.get_children())
        for r in rows:
            preview = (r["cleaned_text"] or "")[:70]
            self.tree.insert("", "end", iid=str(r["id"]), values=(r["id"], r["created_at"], preview, r["match_count"]))

    def _on_history_select(self, _event=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        try:
            cid = int(sel[0])
            capture = self.db.get_capture(cid)
            answers, matches = split_rows(self.db.get_matches(cid))
        except AppError as exc:
            self._set_status(str(exc), error=True)
            return
        if capture is None:
            return
        kws = extract_keywords(capture["cleaned_text"], int(self.settings["min_word_length"]))
        self.hist_view.show(capture, matches, kws, answers, answer_keywords(capture["cleaned_text"]))

    def _delete_selected(self) -> None:
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("History", "Select a record first.")
            return
        cid = int(sel[0])
        if not messagebox.askyesno("Delete", f"Delete record #{cid} and its screenshot?"):
            return
        try:
            shot = self.db.delete_capture(cid)
        except AppError as exc:
            self._set_status(str(exc), error=True)
            return
        if shot:
            try:
                resolve_path(shot).unlink(missing_ok=True)
            except OSError:
                pass
        self.hist_view.clear()
        if self.dash_capture_id == cid:
            self.dash_view.clear()
            self.dash_capture_id = None
        self._refresh_history()
        self._set_status(f"Record #{cid} deleted.")

    def _on_close(self) -> None:
        self.monitor.stop()
        self.jobs.put(None)
        self.destroy()
