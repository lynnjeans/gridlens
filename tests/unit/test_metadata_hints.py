from gridlens.documents.metadata import html_hints, normalize_date, pdf_hints, suggest

EMPTY = {
    "title": "Search title",
    "publisher": None,
    "published_at": None,
    "jurisdiction": "UNKNOWN",
    "source_type": "unknown",
}
PAGE = b"""<html><head><title>Tab title | Site</title>
<meta name="citation_title" content="Declared title">
<meta property="og:site_name" content="Site name">
<meta property="article:published_time" content="2025-06-25T09:00:00+12:00">
<script type="application/ld+json">{"@graph": [{"publisher": {"name": "LD Publisher"}}]}</script>
</head><body><main><p>Text.</p></main></body></html>"""


def test_html_hints_read_declared_title_publisher_and_date():
    page = html_hints(PAGE)
    assert page["title"] == "Declared title"
    assert page["page_title"] == "Tab title | Site"
    assert page["publisher"] == "LD Publisher"
    assert page["site_name"] == "Site name"
    assert page["published_at"] == "2025-06-25"


def test_dates_are_normalized_or_dropped():
    assert normalize_date("D:20250625101500+12'00'") == "2025-06-25"
    assert normalize_date("2025-06") == "2025-06"
    assert normalize_date("2025/06/25") == "2025-06-25"
    assert normalize_date("June 25, 2025") == "2025-06-25"
    assert normalize_date("Jun 25, 2025") == "2025-06-25"
    assert normalize_date("last week") is None


def test_pdf_junk_titles_are_ignored():
    assert pdf_hints({"title": "Microsoft Word - draft.docx"})["pdf_title"] is None
    assert pdf_hints({"title": "Title"})["pdf_title"] is None
    assert pdf_hints({"title": "Grid connection guide 2025"})["pdf_title"] == (
        "Grid connection guide 2025"
    )
    assert pdf_hints({"creation_date": "D:20240102"})["pdf_date"] == "2024-01-02"


def test_known_domain_fills_publisher_region_and_type():
    hints = suggest("https://www.ea.govt.nz/documents/x.pdf", EMPTY, {}, prefer_page_title=True)
    assert hints["publisher"] == {"value": "Electricity Authority", "origin": "website domain"}
    assert hints["jurisdiction"]["value"] == "NZ"
    assert hints["source_type"]["value"] == "policy"
    assert "title" not in hints

    nerc = suggest("https://www.nerc.com/report", EMPTY, {}, prefer_page_title=True)
    assert nerc["publisher"]["value"].startswith("North American Electric Reliability")
    assert nerc["jurisdiction"]["value"] == "US"
    assert "source_type" not in nerc  # .com says nothing about the document type


def test_page_metadata_beats_the_domain_table_and_journals_are_papers():
    page = {"publisher": "Optimal Protocol", "journal": None}
    hints = suggest("https://www.ea.govt.nz/submission.pdf", EMPTY, page, prefer_page_title=True)
    assert hints["publisher"] == {"value": "Optimal Protocol", "origin": "page metadata"}
    paper = suggest("https://www.sciencedirect.com/x", EMPTY, {}, prefer_page_title=True)
    assert paper["source_type"]["value"] == "paper"
    assert "jurisdiction" not in paper


def test_existing_values_are_never_replaced():
    current = {
        **EMPTY,
        "publisher": "Reviewer value",
        "jurisdiction": "GLOBAL",
        "source_type": "technical",
        "published_at": "2020",
    }
    page = html_hints(PAGE)
    hints = suggest("https://www.ea.govt.nz/x", current, page, prefer_page_title=False)
    assert set(hints) == set()  # the search title stays unless the page title is preferred
    hints = suggest("https://www.ea.govt.nz/x", current, page, prefer_page_title=True)
    assert hints == {"title": {"value": "Declared title", "origin": "page metadata"}}


def test_bare_hostname_title_is_replaced_by_the_page_title():
    current = {**EMPTY, "title": "example.org"}
    page = {"page_title": "Real page title"}
    hints = suggest("https://example.org/a", current, page, prefer_page_title=False)
    assert hints["title"] == {"value": "Real page title", "origin": "page metadata"}
    pdf = suggest(
        "https://example.org/a.pdf",
        current,
        {"pdf_title": "PDF own title"},
        prefer_page_title=False,
    )
    assert pdf["title"]["origin"] == "PDF file title"
