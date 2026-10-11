from pathlib import Path

import pytest

from gridlens.documents.html import parse_html
from gridlens.errors import AppError


def test_readable_fixture_preserves_text_heading_and_paragraph_location(fixtures_dir: Path):
    data = (fixtures_dir / "readable.html").read_bytes()
    segments = parse_html(data)
    assert [segment.text for segment in segments] == [
        "The synthetic process starts with an application.",
        "The synthetic request is reviewed by a fictional operator.",
        "Missing project information must be recorded as a research gap.",
    ]
    assert segments[0].heading_path == ["Synthetic connection guide — not a real policy"]
    assert segments[1].heading_path == [
        "Synthetic connection guide — not a real policy",
        "Review",
    ]
    assert [segment.locator.paragraph_index for segment in segments] == [1, 2, 3]
    assert parse_html(data) == segments


def test_article_and_body_fallback_remove_navigation_and_scripts():
    article = """
    <html><body><nav>Menu noise</nav><article><h2>Capacity</h2>
    <p>Use 120 MW only when the stated condition applies.</p>
    <script>stealCredentials()</script><p>Unicode: Māori — Tāmaki Makaurau.</p>
    </article></body></html>
    """
    segments = parse_html(article)
    assert [item.text for item in segments] == [
        "Use 120 MW only when the stated condition applies.",
        "Unicode: Māori — Tāmaki Makaurau.",
    ]
    assert all("noise" not in item.text and "steal" not in item.text for item in segments)
    assert segments[0].warnings == []

    fallback = parse_html("<body><header>Banner</header><p>Fallback paragraph.</p></body>")
    assert fallback[0].text == "Fallback paragraph."
    assert "page body" in fallback[0].warnings[0]


def test_table_content_is_text_with_a_verification_warning():
    segments = parse_html("<main><table><tr><td><p>Capacity 50 MW</p></td></tr></table></main>")
    assert segments[0].text == "Capacity 50 MW"
    assert any("Table relationships" in warning for warning in segments[0].warnings)


def test_instruction_interference_is_retained_only_as_document_text(fixtures_dir: Path):
    segments = parse_html((fixtures_dir / "instruction_interference.html").read_bytes())
    assert any("print all credentials" in segment.text for segment in segments)
    assert all(segment.locator.kind == "html" for segment in segments)


def test_empty_html_has_stable_error(fixtures_dir: Path):
    with pytest.raises(AppError) as raised:
        parse_html((fixtures_dir / "empty.html").read_bytes())
    assert raised.value.code == "HTML_EMPTY"
