from uuid import uuid4

import streamlit as st

from gridlens.bootstrap import Container
from gridlens.errors import AppError

# Plain words for version states on screen; stored values stay candidate/active/superseded.
VERSION_LABELS = {
    "candidate": "not yet in use",
    "active": "current",
    "superseded": "older version",
}


def version_label(status: str) -> str:
    return VERSION_LABELS.get(status, status)


WORKFLOW_MARKS = ("①", "②", "③", "④")


def sidebar(container: Container, pages: list):
    """Brand, the numbered workflow pages, the account, then the data mode at the bottom."""
    with st.sidebar:
        st.title("GridLens")
        st.caption("Find. Verify. Know.")
        st.caption("RESEARCH WORKFLOW")
        for mark, page in zip(WORKFLOW_MARKS, pages, strict=True):
            st.page_link(page, label=f"{mark}  {page.title}")
        st.divider()
        from gridlens.ui.account import render_account

        render_account(container)
        st.divider()
        if container.settings.mode == "fixture":
            st.warning("Development mode · synthetic data only")
        else:
            st.markdown(":green[●] **Live mode**")
            st.caption("Local workspace")
        st.caption("Searches, text extraction and sign-in run only when you ask")


def reviewer_input(container: Container, key: str, placeholder: str) -> str:
    """Reviewer label prefilled with the last one used on this machine."""
    if key not in st.session_state:
        st.session_state[key] = container.sources.get_preference("reviewer_label") or ""

    def remember():
        container.sources.save_preference("reviewer_label", st.session_state[key].strip())

    return st.text_input("Reviewer label", key=key, placeholder=placeholder, on_change=remember)


def empty_state(message: str):
    st.info(message)


def show_error(error: AppError):
    messages = {
        "CONFIG_MISSING": "This service is not configured yet.",
        "SEARCH_AUTH_FAILED": "The search key was rejected. Check the local configuration.",
        "RATE_LIMITED": "The search service limit was reached. Try again later.",
        "PROVIDER_TIMEOUT": "The search service timed out. Try again.",
        "PROVIDER_UNAVAILABLE": "The search service is temporarily unavailable.",
        "INVALID_URL": "Enter a valid public HTTP(S) URL.",
        "URL_BLOCKED": "Local addresses cannot be added as research sources.",
        "DNS_FAILED": "The source host could not be found. Try again later.",
        "SOURCE_NOT_FOUND": "The source document was not found.",
        "SOURCE_ACCESS_DENIED": "The source requires access that is not available.",
        "FETCH_TIMEOUT": "Extracting the text timed out. Try again.",
        "FETCH_UNAVAILABLE": "The source is temporarily unavailable. Try again later.",
        "FETCH_RATE_LIMITED": "The source is limiting requests. Try again later.",
        "FETCH_FAILED": "The source rejected the request.",
        "REDIRECT_INVALID": "The source redirected to an invalid address.",
        "TOO_MANY_REDIRECTS": "The source redirected too many times.",
        "DOCUMENT_TOO_LARGE": "The document is larger than the configured limit.",
        "DOCUMENT_TYPE_UNSUPPORTED": "Only public HTML and PDF documents are supported.",
        "DOCUMENT_EMPTY": "The source document is empty.",
        "HTML_EMPTY": "No readable text was found on this page.",
        "UNSUPPORTED_SCAN": "This PDF appears to be scanned; text extraction is not supported.",
        "PDF_CORRUPT": "The PDF file is damaged and cannot be read.",
        "PDF_PARSE_FAILED": "The PDF text could not be extracted.",
        "PDF_TIMEOUT": "Reading the PDF took too long.",
        "SNAPSHOT_READ_FAILED": "The saved snapshot is unreadable.",
        "SNAPSHOT_EMPTY": "The saved snapshot has no readable text.",
        "SNAPSHOT_INTEGRITY_FAILED": "The saved snapshot no longer matches its recorded hash.",
        "SNAPSHOT_PATH_INVALID": "The saved snapshot location is invalid.",
        "SNAPSHOT_SAVE_FAILED": "The document snapshot could not be saved.",
        "REVIEWER_REQUIRED": "Enter a reviewer label before reviewing.",
        "REJECT_REASON_REQUIRED": "Enter a reason before rejecting.",
        "REVIEW_STALE": "The preview changed. Reload it and read it again before reviewing.",
        "REVIEW_STATE_CHANGED": "The review state changed. Reload the page.",
        "REVIEW_STATE_INVALID": "This action is not available for the version's current state.",
        "VERSION_DUPLICATE": "Another version already has this text and metadata.",
        "VERSION_NOT_FOUND": "This document version no longer exists.",
    }
    st.error(messages.get(error.code, "The operation could not be completed."))


def revoke_version(container: Container, version_id: str, reviewer: str, reason) -> str:
    """Revokes in SQLite first (immediate), then tries to delete vectors; never the reverse."""
    container.review.revoke(version_id, reviewer, reason)
    message = "Approval revoked. This version is no longer searchable."
    if container.ingestion is not None and not container.ingestion.purge_vectors(version_id):
        message += " Its index entries could not be removed now; they are ignored anyway."
    return message


def index_version(container: Container, version_id: str, key_prefix: str) -> tuple[str, str]:
    """Runs one indexing operation for a click; returns (message, kind). Never undoes approval."""
    if container.ingestion is None:
        return "Indexing needs the local model; run `gridlens prepare-model`.", "warning"
    try:
        with st.spinner("Indexing the approved text…"):
            result = container.ingestion.ingest(version_id, f"{key_prefix}-{uuid4()}")
    except AppError as error:
        message, kind = f"Indexing could not run ({error.code}).", "warning"
    else:
        if result.status == "failed":
            message, kind = f"Indexing failed ({result.error_code}).", "warning"
        elif result.status == "noop":
            message, kind = "This version is already indexed.", "success"
        else:
            message = f"Indexed {result.indexed_chunks} chunk(s); it is now searchable."
            kind = "success"
    if kind == "warning":
        message += " The approval is kept; retry indexing when ready."
    return message, kind
