"""Time-bounded PDF text extraction in a terminable subprocess."""

import hashlib
import io
import multiprocessing
import re
from collections.abc import Callable

from pypdf import PdfReader

from gridlens.contracts import Locator, ParsedSegment
from gridlens.errors import AppError

Worker = Callable[[bytes, int, object], None]
LAYOUT_WARNING = (
    "PDF text extraction may not preserve complex tables or multi-column reading order; "
    "verify the original."
)


def _extract_worker(data: bytes, max_pages: int, connection) -> None:
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            connection.send({"error": "PDF_ENCRYPTED"})
            return
        if len(reader.pages) > max_pages:
            connection.send({"error": "PDF_PAGE_LIMIT", "pages": len(reader.pages)})
            return
        pages = []
        for index, page in enumerate(reader.pages, start=1):
            pages.append((index, page.extract_text() or ""))
        connection.send({"pages": pages, "info": _info(reader)})
    except Exception:
        connection.send({"error": "PDF_CORRUPT"})
    finally:
        connection.close()


def _info(reader: PdfReader) -> dict:
    # The document info dictionary is optional and often wrong; it only feeds review hints.
    try:
        info = reader.metadata or {}
        return {
            "title": str(info.get("/Title") or "") or None,
            "creation_date": str(info.get("/CreationDate") or "") or None,
        }
    except Exception:
        return {}


def _info_worker(data: bytes, max_pages: int, connection) -> None:
    try:
        connection.send({"info": _info(PdfReader(io.BytesIO(data), strict=False))})
    except Exception:
        connection.send({"info": {}})
    finally:
        connection.close()


def read_pdf_info(data: bytes, *, timeout_seconds: float) -> dict:
    """Only the PDF's own title/creation date, without extracting page text."""
    result = _run(data, 0, timeout_seconds, _info_worker)
    return result.get("info") or {}


def _run(data: bytes, max_pages: int, timeout_seconds: float, worker: Worker) -> dict:
    context = multiprocessing.get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    process = context.Process(target=worker, args=(data, max_pages, send), daemon=True)
    process.start()
    send.close()
    try:
        if not receive.poll(timeout_seconds):
            process.terminate()
            process.join(timeout=1)
            raise AppError("PDF_TIMEOUT", "PDF extraction timed out.", retryable=True)
        return receive.recv()
    except EOFError:
        raise AppError("PDF_PARSE_FAILED", "PDF extraction stopped unexpectedly.") from None
    finally:
        receive.close()
        if process.is_alive():
            process.terminate()
        process.join(timeout=1)


def parse_pdf(
    data: bytes,
    *,
    max_pages: int,
    timeout_seconds: float,
    worker: Worker = _extract_worker,
) -> list[ParsedSegment]:
    return parse_pdf_document(
        data, max_pages=max_pages, timeout_seconds=timeout_seconds, worker=worker
    )[0]


def parse_pdf_document(
    data: bytes,
    *,
    max_pages: int,
    timeout_seconds: float,
    worker: Worker = _extract_worker,
) -> tuple[list[ParsedSegment], dict]:
    """Segments plus the PDF's own title/creation-date info (empty when unavailable)."""
    if not data:
        raise AppError("PDF_CORRUPT", "The PDF file is empty or damaged.")
    result = _run(data, max_pages, timeout_seconds, worker)

    error = result.get("error")
    if error == "PDF_ENCRYPTED":
        raise AppError(error, "Encrypted PDF files are not supported.")
    if error == "PDF_PAGE_LIMIT":
        raise AppError(error, f"The PDF exceeds the {max_pages}-page limit.")
    if error:
        raise AppError(error, "The PDF file is damaged or cannot be parsed.")

    pages = result.get("pages", [])
    document_hash = hashlib.sha256(data).hexdigest()
    blank_pages = [number for number, text in pages if not text.strip()]
    segments = [
        ParsedSegment(
            segment_id=f"pdf-{number:04d}-{document_hash[:12]}",
            text=_normalize_text(text),
            locator=Locator(kind="pdf", file_page=number),
            warnings=[LAYOUT_WARNING]
            + ([f"Pages without extractable text: {blank_pages}."] if blank_pages else []),
        )
        for number, text in pages
        if text.strip()
    ]
    if not segments:
        raise AppError("UNSUPPORTED_SCAN", "The PDF has no extractable text; OCR is not supported.")
    return segments, result.get("info") or {}


def _normalize_text(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.replace("\r", "\n").split("\n")]
    return "\n".join(line for line in lines if line)
