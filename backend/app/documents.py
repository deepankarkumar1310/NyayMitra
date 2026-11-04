"""Handling of uploaded worker documents (PDFs and photos)."""

import io
from dataclasses import dataclass

from pypdf import PdfReader

from . import config


class DocumentError(ValueError):
    """Raised for unsupported or unreadable uploads."""


@dataclass
class Document:
    name: str
    mime_type: str
    data: bytes
    text: str = ""  # extracted text (PDF only)

    @property
    def is_image(self) -> bool:
        return self.mime_type in config.IMAGE_TYPES


def load_document(name: str, mime_type: str, data: bytes) -> Document:
    mime_type = (mime_type or "").lower()
    if not data:
        raise DocumentError("The uploaded file is empty.")
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise DocumentError("The file is too large (max 15 MB).")

    if mime_type == config.PDF_TYPE or name.lower().endswith(".pdf"):
        return Document(name, config.PDF_TYPE, data, extract_pdf_text(data))
    if mime_type in config.IMAGE_TYPES:
        return Document(name, mime_type, data)
    raise DocumentError("Only PDF, JPG, PNG or WEBP files are supported.")


def extract_pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:  # pypdf raises many different error types
        raise DocumentError("This PDF could not be read.") from exc
    text = " ".join(text.split())
    return text[: config.MAX_DOC_CHARS]
