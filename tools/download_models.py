"""Downloads the EasyOCR models into ./models so the program (and the .exe) also works offline."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from finder.config import MODELS_DIR, Settings

if __name__ == "__main__":
    import easyocr
    langs = Settings()["ocr_languages"]
    MODELS_DIR.mkdir(exist_ok=True)
    print(f"Downloading EasyOCR models for {langs} ...")
    easyocr.Reader(langs, gpu=False, model_storage_directory=str(MODELS_DIR), verbose=True)
    print("Done:", MODELS_DIR)
