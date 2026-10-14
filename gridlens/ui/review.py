import json
import re
from collections import Counter

import streamlit as st
from pydantic import ValidationError

from gridlens.bootstrap import Container
from gridlens.contracts import MetadataCorrection
from gridlens.errors import AppError
from gridlens.ui.common import (
    empty_state,
    index_version,
    reviewer_input,
    revoke_version,
    show_error,
    version_label,
)

STATUS_ORDER = {"pending": 0, "rejected": 1, "revoked": 2, "approved": 3}
JURISDICTIONS = ["NZ", "US", "GLOBAL", "UNKNOWN"]
SOURCE_TYPES = ["policy", "technical", "paper", "industry_report", "product", "unknown"]
MAX_PREVIEW_SEGMENTS = 200
SECTIONS = ("capture", "review", "reviewed")
SECTION_NAMES = {"capture": "1 · To extract", "review": "2 · To review", "reviewed": "Reviewed"}
SECTION_HELP = {
    "capture": "Step 1 · Extract text saves a fixed copy of each selected source's current text.",
    "review": "Step 2 · Read each extracted document, fix its metadata, then approve or reject.",
    "reviewed": "Approved, rejected and revoked documents. Approval adds a document to the "
    "knowledge base.",
}
_CURRENT = object()


def _notice(message: str, kind: str = "success", *, focus=_CURRENT):
    # Shown once after an action's rerun; never stores review eligibility. `focus` is the
    # version to show next (default: the one acted on), applied before widgets are created.
    if focus is _CURRENT:
        focus = st.session_state.get("review_version_id")
    st.session_state["review_notice"] = (kind, message)
    st.session_state["review_focus"] = focus
    st.rerun()


def _index(container: Container, version_id: str, prefix: str):
    message, kind = index_version(container, version_id, "review")
    _notice(f"{prefix} {message}", kind)


def _capture_queue(container: Container, queue: list[dict]):
    # The queue is persisted in SQLite, so every selection survives reruns and reloads;
    # a source leaves the queue once it has a captured version.
    if not queue:
        empty_state("Nothing to extract. Select sources in Discover with Select for review.")
        return
    for source in queue:
        source_id = source["id"]
        with st.container(border=True):
            st.write(source["title"])
            st.caption(source["original_url"])
            left, middle, right = st.columns(3)
            left.link_button("Open original", source["original_url"])
            capture = middle.button("Extract text", key=f"capture-{source_id}")
            # Drawn before any capture error so a failed source can still leave the queue.
            if right.button("Remove from queue", key=f"dequeue-{source_id}"):
                container.sources.remove_from_review_queue(source_id)
                _notice(
                    "Removed from the Review queue. The search result is kept.", "info", focus=None
                )
            if capture:
                try:
                    preview = container.snapshots.capture(source_id)
                except AppError as error:
                    show_error(error)
                    if not error.retryable:
                        st.caption(
                            "Trying again will not help. Use Remove from queue, "
                            "or open the original to read it yourself."
                        )
                    continue
                st.session_state.pop("review_seen", None)
                # Stay in step 1 so more sources can be extracted; step 2 opens on this one.
                st.session_state["review_preselect"] = preview.version_id
                _notice(
                    "This text was already extracted; it is in 2 · To review."
                    if preview.reused
                    else "Text extracted. Read it in 2 · To review, then approve or reject.",
                    focus=None,
                )


def _label(version: dict) -> str:
    title = json.loads(version["metadata_json"]).get("title") or version["title"]
    # The distinguishing part comes first so a narrow dropdown does not cut it off.
    older = "Older version · " if version["version_status"] == "superseded" else ""
    return f"{older}{title} · {version['review_status']}"


def _labels(versions: list[dict]) -> dict[str, str]:
    """Unique dropdown labels: Streamlit maps a picked label back to the first equal one."""
    labels = {v["id"]: _label(v) for v in versions}
    counts = Counter(labels.values())
    return {
        v["id"]: (f"Snapshot {v['snapshot_sha256'][:12]} · " if counts[label] > 1 else "") + label
        for v in versions
        for label in [labels[v["id"]]]
    }


def _reflow(text: str) -> str:
    # Display only: joins hard line breaks left by PDF/HTML extraction inside a paragraph so
    # the preview reads at full width. The captured snapshot and citations are unchanged.
    paragraphs = re.split(r"\n\s*\n", text)
    return "\n\n".join(
        " ".join(line.strip() for line in paragraph.splitlines() if line.strip())
        for paragraph in paragraphs
        if paragraph.strip()
    )


def _segments(segments):
    with st.expander(f"Document text · {len(segments)} segment(s)", expanded=True):
        st.caption("Line breaks are joined for reading; the saved text is unchanged.")
        body = st.container(height=560)
    with body:
        for segment in segments[:MAX_PREVIEW_SEGMENTS]:
            locator = segment.locator
            place = (
                f"page {locator.file_page}"
                if locator.kind == "pdf"
                else f"paragraph {locator.paragraph_index}"
            )
            st.caption(" › ".join([*segment.heading_path, place]))
            st.text(_reflow(segment.text))
        if len(segments) > MAX_PREVIEW_SEGMENTS:
            st.caption(
                f"{len(segments) - MAX_PREVIEW_SEGMENTS} more segment(s) are not shown. "
                "Open the original to read the full document before approving."
            )


FIELD_LABELS = {
    "title": "Title",
    "publisher": "Publisher",
    "published_at": "Published date",
    "jurisdiction": "Region",
    "source_type": "Source type",
}
EMPTY_VALUES = {None, "", "UNKNOWN", "unknown"}


def _auto_filled(meta: dict) -> list[str]:
    # A hint stays visible until the reviewer saves a different value for that field.
    return [
        f"{FIELD_LABELS[field]} ({hint['origin']})"
        for field, hint in meta.get("metadata_hints", {}).items()
        if field in FIELD_LABELS and meta.get(field) == hint["value"]
    ]


def _fill_from_page(container: Container, version_id: str, seen_hash: str, meta: dict):
    try:
        hints = container.snapshots.page_hints(version_id)
        if not hints:
            st.info("The saved page does not declare any of the empty fields.")
            return
        values = {field: meta.get(field) for field in FIELD_LABELS}
        values.update({field: hint["value"] for field, hint in hints.items()})
        result = container.review.update_metadata(
            version_id, seen_hash, MetadataCorrection(**values), hints
        )
    except (AppError, ValidationError) as error:
        if isinstance(error, AppError):
            show_error(error)
        else:
            st.error("The values found on the page could not be used.")
        return
    st.session_state["review_seen"] = {"version_id": version_id, "hash": result.snapshot_sha256}
    filled = ", ".join(FIELD_LABELS[field] for field in hints)
    _notice(f"Filled from the saved page: {filled}. Check them before approving.")


def _metadata_form(container: Container, version_id: str, seen_hash: str, meta: dict, stale):
    suffix = f"{version_id}-{seen_hash[:12]}"
    if any(meta.get(field) in EMPTY_VALUES for field in FIELD_LABELS) and st.button(
        "Fill empty fields from the page",
        key=f"fill-{suffix}",
        disabled=stale,
        help="Reads the saved copy of this document; nothing is fetched.",
    ):
        _fill_from_page(container, version_id, seen_hash, meta)
    with st.form(f"metadata-{suffix}"):
        st.markdown("**Reviewed metadata**")
        if auto := _auto_filled(meta):
            st.caption("Filled automatically, check before approving: " + " · ".join(auto))
        title = st.text_input("Title", value=meta.get("title") or "", key=f"title-{suffix}")
        left, right = st.columns(2)
        publisher = left.text_input(
            "Publisher", value=meta.get("publisher") or "", key=f"publisher-{suffix}"
        )
        published_at = right.text_input(
            "Published date",
            value=meta.get("published_at") or "",
            placeholder="Unknown",
            key=f"published-{suffix}",
        )
        jurisdiction = left.selectbox(
            "Region",
            JURISDICTIONS,
            index=JURISDICTIONS.index(meta.get("jurisdiction", "UNKNOWN")),
            key=f"jurisdiction-{suffix}",
        )
        source_type = right.selectbox(
            "Source type",
            SOURCE_TYPES,
            index=SOURCE_TYPES.index(meta.get("source_type", "unknown")),
            key=f"type-{suffix}",
        )
        saved = st.form_submit_button("Save metadata", disabled=stale)
    if saved:
        try:
            correction = MetadataCorrection(
                title=title,
                publisher=publisher,
                published_at=published_at,
                jurisdiction=jurisdiction,
                source_type=source_type,
            )
        except ValidationError:
            st.error("A title is required, and fields must stay within their length limits.")
            return
        try:
            result = container.review.update_metadata(version_id, seen_hash, correction)
        except AppError as error:
            show_error(error)
            return
        if result.changed:
            st.session_state["review_seen"] = {
                "version_id": version_id,
                "hash": result.snapshot_sha256,
            }
            _notice("Metadata saved. Review the updated version before approving.")
        st.info("No metadata changed.")


def _approval_check(meta: dict):
    # Approve uses the saved metadata, not unsaved edits in the form above.
    region = meta.get("jurisdiction", "UNKNOWN")
    source_type = meta.get("source_type", "unknown")
    st.markdown(f"**Approve with saved metadata:** region {region} · type {source_type}")
    st.caption("Changed the form? Click Save metadata first; unsaved edits are not approved.")
    if region == "UNKNOWN":
        st.warning(
            "Region is UNKNOWN: questions filtered to NZ, US or GLOBAL will not use this "
            "document. Set the region and save before approving if it is known."
        )
    if source_type == "unknown":
        st.warning("Source type is unknown. Set it and save before approving if it is known.")


def _pending_actions(container, version_id, seen_hash, reviewer, *, meta, stale, readable):
    _approval_check(meta)
    if st.button(
        "Approve",
        type="primary",
        disabled=stale or not readable,
        key=f"approve-{version_id}-{seen_hash[:12]}",
    ):
        try:
            container.review.approve(version_id, seen_hash, reviewer)
        except AppError as error:
            show_error(error)
        else:
            _index(container, version_id, "Approved.")
    with st.form(f"reject-{version_id}"):
        reason = st.text_area("Rejection reason", key=f"reject-reason-{version_id}")
        rejected = st.form_submit_button("Reject")
    if rejected:
        try:
            container.review.reject(version_id, reviewer, reason)
        except AppError as error:
            show_error(error)
        else:
            _notice("Rejected. The reason was saved with the review history.")


def _closed_actions(container, version_id, row, reviewer):
    status = row["review_status"]
    if status == "approved" and row["ingestion_status"] in {"not_started", "failed"}:
        if st.button("Retry indexing", key=f"ingest-{version_id}"):
            _index(container, version_id, "Retried.")
    if status == "approved":
        action, label, done = "revoke", "Revoke approval", "Approval revoked."
    elif row["version_status"] != "superseded":
        action, label, done = "reopen", "Reopen for review", "Reopened for review."
    else:
        return
    with st.form(f"{action}-{version_id}"):
        reason = st.text_input("Reason (optional)", key=f"{action}-reason-{version_id}")
        submitted = st.form_submit_button(label)
    if submitted:
        try:
            if action == "revoke":
                done = revoke_version(container, version_id, reviewer, reason)
            else:
                container.review.reopen(version_id, reviewer, reason)
        except AppError as error:
            show_error(error)
        else:
            st.session_state.pop("review_seen", None)
            _notice(done)


def _version_detail(container: Container, version_id: str, reviewer: str):
    row = container.sources.get_version(version_id)
    if row is None:
        empty_state("This version no longer exists.")
        return
    meta = json.loads(row["metadata_json"])
    current_hash = row["snapshot_sha256"]
    seen = st.session_state.get("review_seen")
    if not seen or seen["version_id"] != version_id:
        seen = {"version_id": version_id, "hash": current_hash}
        st.session_state["review_seen"] = seen
    seen_hash = seen["hash"]
    stale = seen_hash != current_hash

    st.subheader(meta.get("title") or "Untitled")
    st.caption(
        f"Review: {row['review_status']} · ingestion: {row['ingestion_status']} · "
        f"version: {version_label(row['version_status'])} · snapshot {current_hash[:12]}"
    )
    link_left, link_right = st.columns(2)
    link_left.link_button("Open original", meta["original_url"])
    if meta.get("final_url") and meta["final_url"] != meta["original_url"]:
        link_right.caption(f"Extracted from redirect target: {meta['final_url']}")
    if stale:
        st.warning(
            "This document changed after you opened it. Reload the preview and read it again "
            "before reviewing."
        )
        if st.button("Reload preview", key=f"reload-{version_id}"):
            st.session_state["review_seen"] = {"version_id": version_id, "hash": current_hash}
            st.rerun()

    try:
        segments = container.review.load_snapshot(version_id)
    except AppError as error:
        segments = []
        show_error(error)
        st.caption("An unreadable snapshot cannot be approved. Extract the text again.")
    if notes := json.loads(row["extraction_notes_json"]):
        st.warning("Extraction limits: " + "; ".join(notes))
    if segments:
        _segments(segments)

    if row["review_status"] == "pending":
        _metadata_form(container, version_id, seen_hash, meta, stale)
        _pending_actions(
            container,
            version_id,
            seen_hash,
            reviewer,
            meta=meta,
            stale=stale,
            readable=bool(segments),
        )
    else:
        _closed_actions(container, version_id, row, reviewer)

    if events := container.research.review_events(version_id):
        st.markdown("**Review history**")
        st.dataframe(
            [
                {
                    "Action": event["action"],
                    "Reviewer": event["reviewer_label"],
                    "Reason": event["reason"] or "",
                    "Time": event["created_at"],
                }
                for event in events
            ],
            hide_index=True,
        )


def _version_list(container: Container, versions: list[dict], reviewer: str, empty: str):
    if not versions:
        empty_state(empty)
        return
    labels = _labels(versions)
    if st.session_state.get("review_version_id") not in labels:
        st.session_state["review_version_id"] = versions[0]["id"]
    version_id = st.selectbox(
        f"Document ({len(labels)})",
        list(labels),
        format_func=labels.__getitem__,
        key="review_version_id",
    )
    st.divider()
    _version_detail(container, version_id, reviewer)


def render(container: Container):
    st.title("Review")
    st.write("Read the original document before approving it for the knowledge base.")
    reviewer = reviewer_input(container, "review_reviewer", "Your name or initials")
    queue = container.sources.review_queue()
    versions = sorted(
        container.research.list_versions(),
        key=lambda v: STATUS_ORDER.get(v["review_status"], 9),
    )
    pending = [v for v in versions if v["review_status"] == "pending"]
    reviewed = [v for v in versions if v["review_status"] != "pending"]
    if preselect := st.session_state.pop("review_preselect", None):
        st.session_state["review_version_id"] = preselect
    if focus := st.session_state.pop("review_focus", None):
        # Follow the document just acted on into the step where it now is.
        status = next((v["review_status"] for v in versions if v["id"] == focus), None)
        if status:
            st.session_state["review_section"] = "review" if status == "pending" else "reviewed"
            st.session_state["review_version_id"] = focus
    if st.session_state.get("review_section") not in SECTIONS:
        st.session_state["review_section"] = "review" if pending or not queue else "capture"
    if notice := st.session_state.pop("review_notice", None):
        kind, message = notice
        {"warning": st.warning, "info": st.info}.get(kind, st.success)(message)
    counts = {"capture": len(queue), "review": len(pending), "reviewed": len(reviewed)}
    titles = {key: f"{SECTION_NAMES[key]} ({counts[key]})" for key in SECTIONS}
    # Streamlit remembers a radio's picked label, whose count changes after an action, and
    # would then lose the step. The step lives in session state and the widget key carries
    # the counts, so a count change draws a fresh radio at the saved step while clicks on an
    # unchanged radio keep working.
    section = st.radio(
        "Review step",
        SECTIONS,
        index=SECTIONS.index(st.session_state["review_section"]),
        format_func=titles.__getitem__,
        horizontal=True,
        key="review_step_" + "_".join(str(counts[key]) for key in SECTIONS),
        label_visibility="collapsed",
    )
    st.session_state["review_section"] = section
    st.caption(SECTION_HELP[section])
    if section == "capture":
        _capture_queue(container, queue)
    elif section == "review":
        _version_list(
            container,
            pending,
            reviewer,
            "No extracted documents are waiting for review. Extract a source's text first.",
        )
    else:
        _version_list(container, reviewed, reviewer, "No documents have been reviewed yet.")
