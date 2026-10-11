"""Deterministic HTML text extraction with paragraph locators."""

import hashlib
import re

from bs4 import BeautifulSoup, Tag

from gridlens.contracts import Locator, ParsedSegment
from gridlens.errors import AppError

CONTENT_TAGS = {"p", "li", "pre", "blockquote"}


def parse_html(data: bytes | str) -> list[ParsedSegment]:
    soup = BeautifulSoup(data, "html.parser")
    for tag in soup.select("script, style, nav, noscript, template, svg"):
        tag.decompose()
    root = soup.find("main") or soup.find("article")
    warnings: list[str] = []
    if root is None:
        root = soup.body or soup
        warnings.append("No main/article element; extracted paragraph content from the page body.")
    if root.find("table"):
        warnings.append(
            "Table relationships were not reconstructed; verify table content in the original."
        )

    headings: list[str] = []
    extracted: list[tuple[str, list[str]]] = []
    for element in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", *CONTENT_TAGS]):
        if not isinstance(element, Tag):
            continue
        text = _normalized_text(element)
        if not text:
            continue
        if element.name.startswith("h"):
            level = int(element.name[1])
            headings = headings[: level - 1]
            while len(headings) < level - 1:
                headings.append("")
            headings.append(text)
            continue
        if element.find_parent(CONTENT_TAGS):
            continue
        extracted.append((text, [heading for heading in headings if heading]))
    if not extracted:
        raise AppError("HTML_EMPTY", "No readable paragraph text was found in the HTML source.")

    document_hash = hashlib.sha256(str(soup).encode("utf-8")).hexdigest()
    return [
        ParsedSegment(
            segment_id=f"html-{index:04d}-{document_hash[:12]}",
            text=text,
            heading_path=heading_path,
            locator=Locator(kind="html", paragraph_index=index),
            warnings=warnings,
        )
        for index, (text, heading_path) in enumerate(extracted, start=1)
    ]


def _normalized_text(tag: Tag) -> str:
    return re.sub(r"\s+", " ", tag.get_text(" ", strip=True)).strip()
