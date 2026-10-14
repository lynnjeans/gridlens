import io
import time
from pathlib import Path

import pytest
from pypdf import PdfWriter

from gridlens.documents.pdf import parse_pdf, parse_pdf_document, read_pdf_info
from gridlens.errors import AppError


def slow_worker(data, max_pages, connection):
    time.sleep(2)


def test_extracts_two_pages_with_one_based_file_page(fixtures_dir: Path):
    data = (fixtures_dir / "readable.pdf").read_bytes()
    segments = parse_pdf(data, max_pages=10, timeout_seconds=5)
    assert [segment.text for segment in segments] == [
        "Synthetic application stage.",
        "Synthetic review stage.",
    ]
    assert [segment.locator.file_page for segment in segments] == [1, 2]
    assert all(segment.locator.printed_page is None for segment in segments)
    assert parse_pdf(data, max_pages=10, timeout_seconds=5) == segments
    assert all("complex tables" in segment.warnings[0] for segment in segments)


def test_scan_has_stable_unsupported_error(fixtures_dir: Path):
    with pytest.raises(AppError) as raised:
        parse_pdf((fixtures_dir / "scan.pdf").read_bytes(), max_pages=10, timeout_seconds=5)
    assert raised.value.code == "UNSUPPORTED_SCAN"


def test_corrupt_pdf_has_stable_error(fixtures_dir: Path):
    with pytest.raises(AppError) as raised:
        parse_pdf((fixtures_dir / "corrupt.pdf").read_bytes(), max_pages=10, timeout_seconds=5)
    assert raised.value.code == "PDF_CORRUPT"


def test_page_limit_is_checked_before_extraction(fixtures_dir: Path):
    with pytest.raises(AppError) as raised:
        parse_pdf((fixtures_dir / "readable.pdf").read_bytes(), max_pages=1, timeout_seconds=5)
    assert raised.value.code == "PDF_PAGE_LIMIT"


def test_encrypted_pdf_is_rejected():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("synthetic-password")
    buffer = io.BytesIO()
    writer.write(buffer)
    with pytest.raises(AppError) as raised:
        parse_pdf(buffer.getvalue(), max_pages=10, timeout_seconds=5)
    assert raised.value.code == "PDF_ENCRYPTED"


def test_controlled_worker_timeout_is_terminated(fixtures_dir: Path):
    started = time.monotonic()
    with pytest.raises(AppError) as raised:
        parse_pdf(
            (fixtures_dir / "readable.pdf").read_bytes(),
            max_pages=10,
            timeout_seconds=0.05,
            worker=slow_worker,
        )
    assert raised.value.code == "PDF_TIMEOUT"
    assert raised.value.retryable
    assert time.monotonic() - started < 1.5


def test_pdf_info_is_read_with_and_without_page_text(fixtures_dir: Path):
    buffer = io.BytesIO()
    writer = PdfWriter(clone_from=fixtures_dir / "readable.pdf")
    writer.add_metadata({"/Title": "Synthetic guide", "/CreationDate": "D:20240102030405"})
    writer.write(buffer)
    data = buffer.getvalue()
    expected = {"title": "Synthetic guide", "creation_date": "D:20240102030405"}
    assert parse_pdf_document(data, max_pages=10, timeout_seconds=5)[1] == expected
    assert read_pdf_info(data, timeout_seconds=5) == expected
