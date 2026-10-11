from uuid import uuid4

import streamlit as st

from gridlens.bootstrap import Container
from gridlens.errors import AppError


def sidebar(container: Container):
    with st.sidebar:
        st.title("GridLens")
        st.caption("Evidence for grid research")
        if container.settings.mode == "fixture":
            st.warning("Development mode · synthetic data only")
        else:
            st.info("Live mode · local workspace")
        st.divider()
        from gridlens.ui.account import render_account

        render_account(container)
        st.divider()
        st.caption("Searches, captures and sign-in run only when you ask")


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
        "FETCH_TIMEOUT": "Capturing the document timed out. Try again.",
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
