"""Entry point: python main.py   (or OCRTextFinder.exe)"""
import multiprocessing
import os
import sys


def _fix_std_streams() -> None:
    # windowed .exe has no console: sys.stdout/stderr are None, which breaks libraries that print
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w"))


def main() -> None:
    _fix_std_streams()
    import logging
    from logging.handlers import RotatingFileHandler
    from finder.config import LOG_PATH

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=2, encoding="utf-8")])
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)      # sharp text on high-DPI screens
    except Exception:                                      # noqa: BLE001
        pass
    try:
        from finder.gui import App
        App().mainloop()
    except Exception as exc:                               # noqa: BLE001
        logging.getLogger("main").exception("Fatal error")
        try:
            import tkinter
            from tkinter import messagebox
            root = tkinter.Tk()
            root.withdraw()
            messagebox.showerror("OCR Text Finder", f"The application could not start:\n\n{exc}\n\nSee app.log for details.")
        except Exception:                                  # noqa: BLE001
            pass
        raise


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
