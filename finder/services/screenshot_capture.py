"""Image helpers: validate, load from a file, save screenshots."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from ..errors import EmptyScreenshotError, StorageError, UnsupportedImageError

MIN_SIZE = 8


def validate_image(image) -> Image.Image:
    if image is None:
        raise EmptyScreenshotError("The screenshot is empty.")
    if not isinstance(image, Image.Image):
        raise UnsupportedImageError("The clipboard content is not a supported image.")
    try:
        rgb = image.convert("RGB")
    except Exception as exc:                                  # noqa: BLE001
        raise UnsupportedImageError(f"Unsupported image format: {exc}") from exc
    if rgb.width < MIN_SIZE or rgb.height < MIN_SIZE:
        raise EmptyScreenshotError("The screenshot is too small to contain text.")
    return rgb


def load_image_file(path: str | Path) -> Image.Image:
    try:
        with Image.open(path) as img:
            img.load()
            return img.copy()
    except (UnidentifiedImageError, ValueError) as exc:
        raise UnsupportedImageError("Unsupported image format. Use PNG, JPG, BMP, GIF, WEBP or TIFF.") from exc
    except OSError as exc:
        raise UnsupportedImageError(f"Cannot open the image: {exc}") from exc


def save_screenshot(image: Image.Image, directory: Path) -> Path:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / datetime.now().strftime("capture_%Y%m%d_%H%M%S_%f.png")
        image.save(path, "PNG")
        return path
    except OSError as exc:
        raise StorageError(f"Cannot save the screenshot: {exc}") from exc
