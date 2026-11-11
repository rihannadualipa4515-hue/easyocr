"""Application specific exceptions (messages are shown to the user)."""


class AppError(Exception):
    """Base class: the message is always safe to show in the UI."""


class EmptyScreenshotError(AppError):
    pass


class UnsupportedImageError(AppError):
    pass


class OCRError(AppError):
    pass


class TextFileError(AppError):
    pass


class StorageError(AppError):
    pass


class ClipboardError(AppError):
    pass
