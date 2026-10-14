"""Deterministic metadata hints from a fetched document; no network calls.

Hints only fill fields that are still empty. Each hint records where it came from so the
reviewer can check it; the reviewer still saves and approves the metadata.
"""

import json
import re
from datetime import datetime
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

# Curated publishers by website domain (a subdomain matches too).
KNOWN_PUBLISHERS = {
    "ea.govt.nz": ("Electricity Authority", "NZ"),
    "transpower.co.nz": ("Transpower New Zealand", "NZ"),
    "mbie.govt.nz": ("Ministry of Business, Innovation and Employment (MBIE)", "NZ"),
    "eeca.govt.nz": ("Energy Efficiency and Conservation Authority (EECA)", "NZ"),
    "comcom.govt.nz": ("Commerce Commission", "NZ"),
    "ferc.gov": ("Federal Energy Regulatory Commission (FERC)", "US"),
    "nerc.com": ("North American Electric Reliability Corporation (NERC)", "US"),
    "eia.gov": ("U.S. Energy Information Administration (EIA)", "US"),
}
PAPER_DOMAINS = (
    "sciencedirect.com",
    "doi.org",
    "arxiv.org",
    "springer.com",
    "ieeexplore.ieee.org",
    "mdpi.com",
    "wiley.com",
    "tandfonline.com",
    "nature.com",
)
EMPTY = {None, "", "UNKNOWN", "unknown"}
JUNK_TITLES = {"title", "untitled", "document", "microsoft word", "powerpoint presentation"}
DATE_FORMATS = ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y")

ORIGIN_PAGE = "page metadata"
ORIGIN_DOMAIN = "website domain"
ORIGIN_PDF_DATE = "PDF file date"
ORIGIN_PDF_TITLE = "PDF file title"


def host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def _on(hostname: str, domain: str) -> bool:
    return hostname == domain or hostname.endswith("." + domain)


def normalize_date(value) -> str | None:
    """ISO date (YYYY-MM-DD, or YYYY-MM / YYYY) from common page and PDF formats."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if match := re.match(r"^D:(\d{4})(\d{2})?(\d{2})?", text):
        return "-".join(part for part in match.groups() if part)
    if match := re.match(r"^(\d{4})(?:[-/](\d{2}))?(?:[-/](\d{2}))?(?:$|[T\s])", text):
        return "-".join(part for part in match.groups() if part)
    for pattern in DATE_FORMATS:
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue
    return None


def _clean(value) -> str | None:
    if not isinstance(value, str):
        return None
    text = re.sub(r"\s+", " ", value).strip()
    return text[:300] or None


def _json_ld(soup: BeautifulSoup) -> list[dict]:
    items: list[dict] = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop(0)
            if isinstance(item, dict):
                items.append(item)
                if isinstance(item.get("@graph"), list):
                    stack.extend(item["@graph"])
    return items


def html_hints(body: bytes | str) -> dict:
    """Title, publisher, date and journal signals declared in the page itself."""
    soup = BeautifulSoup(body, "html.parser")

    def meta(*names: str) -> str | None:
        for name in names:
            for attribute in ("name", "property"):
                tag = soup.find("meta", attrs={attribute: re.compile(f"^{re.escape(name)}$", re.I)})
                if tag and (value := _clean(tag.get("content"))):
                    return value
        return None

    ld = _json_ld(soup)
    ld_publisher = next(
        (
            _clean(item["publisher"].get("name"))
            if isinstance(item.get("publisher"), dict)
            else _clean(item.get("publisher"))
            for item in ld
            if item.get("publisher")
        ),
        None,
    )
    ld_date = next((item.get("datePublished") for item in ld if item.get("datePublished")), None)
    time_tag = soup.find("time", attrs={"datetime": True})
    return {
        "title": meta("citation_title", "og:title", "dc.title"),
        "page_title": _clean(soup.title.string) if soup.title else None,
        "publisher": meta("citation_publisher", "dc.publisher", "dcterms.publisher")
        or ld_publisher,
        "site_name": meta("og:site_name"),
        "published_at": next(
            (
                date
                for date in (
                    normalize_date(meta("citation_publication_date", "citation_date")),
                    normalize_date(meta("article:published_time")),
                    normalize_date(meta("dc.date.issued", "dcterms.issued", "dc.date")),
                    normalize_date(ld_date),
                    normalize_date(time_tag.get("datetime") if time_tag else None),
                )
                if date
            ),
            None,
        ),
        "journal": meta("citation_journal_title"),
    }


def pdf_hints(info: dict) -> dict:
    title = _clean(info.get("title"))
    if title and (
        title.lower() in JUNK_TITLES
        or len(title) < 8
        or title.lower().startswith("microsoft ")
        or re.search(r"\.(docx?|pdf|pptx?)$", title, re.I)
    ):
        title = None
    return {"pdf_title": title, "pdf_date": normalize_date(info.get("creation_date"))}


def suggest(url: str, current: dict, page: dict, *, prefer_page_title: bool) -> dict[str, dict]:
    """{field: {"value", "origin"}} for empty fields.

    The title is also replaced when it is only the hostname, or, with prefer_page_title (a
    first extraction, whose title came from the search result), when the page declares one.
    """
    hostname = host(url)
    known = next((v for domain, v in KNOWN_PUBLISHERS.items() if _on(hostname, domain)), None)
    candidates: dict[str, tuple[str | None, str]] = {}

    title = current.get("title")
    bare_title = title in EMPTY or host(f"//{title}") == hostname
    if page.get("title") and (prefer_page_title or bare_title):
        candidates["title"] = (page["title"], ORIGIN_PAGE)
    elif bare_title:
        if page.get("page_title"):
            candidates["title"] = (page["page_title"], ORIGIN_PAGE)
        elif page.get("pdf_title"):
            candidates["title"] = (page["pdf_title"], ORIGIN_PDF_TITLE)

    if page.get("publisher"):
        candidates["publisher"] = (page["publisher"], ORIGIN_PAGE)
    elif known:
        candidates["publisher"] = (known[0], ORIGIN_DOMAIN)
    elif page.get("site_name"):
        candidates["publisher"] = (page["site_name"], ORIGIN_PAGE)

    if page.get("published_at"):
        candidates["published_at"] = (page["published_at"], ORIGIN_PAGE)
    elif page.get("pdf_date"):
        candidates["published_at"] = (page["pdf_date"], ORIGIN_PDF_DATE)

    if known:
        candidates["jurisdiction"] = (known[1], ORIGIN_DOMAIN)
    elif hostname.endswith(".nz"):
        candidates["jurisdiction"] = ("NZ", ORIGIN_DOMAIN)
    elif hostname.endswith((".gov", ".mil")):
        candidates["jurisdiction"] = ("US", ORIGIN_DOMAIN)

    if any(_on(hostname, domain) for domain in PAPER_DOMAINS) or page.get("journal"):
        candidates["source_type"] = ("paper", ORIGIN_DOMAIN)
    elif hostname.endswith((".govt.nz", ".gov")):
        candidates["source_type"] = ("policy", ORIGIN_DOMAIN)

    hints = {}
    for field, (value, origin) in candidates.items():
        replace_title = field == "title" and value != title
        if value and (field == "title" and replace_title or current.get(field) in EMPTY):
            hints[field] = {"value": value, "origin": origin}
    return hints
