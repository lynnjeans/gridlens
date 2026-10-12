import json

import streamlit as st
from pydantic import ValidationError

from gridlens.bootstrap import Container
from gridlens.contracts import MetadataCorrection
from gridlens.errors import AppError
from gridlens.ui.common import empty_state, index_version, revoke_version, show_error

STATUS_ORDER = {"pending": 0, "rejected": 1, "revoked": 2, "approved": 3}
JURISDICTIONS = ["NZ", "US", "GLOBAL", "UNKNOWN"]
SOURCE_TYPES = ["policy", "technical", "paper", "industry_report", "product", "unknown"]
MAX_PREVIEW_SEGMENTS = 200
SECTIONS = ("capture", "review", "reviewed")
SECTION_HELP = {
    "capture": "Step 1 · Capture saves a fixed copy of each selected source's current text.",
    "review": "Step 2 · Read each captured document, correct its metadata, then approve or reject.",
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
        empty_state("Nothing to capture. Select sources in Discover with Select for review.")
        return
    for source in queue:
        source_id = source["id"]
        with st.container(border=True):
            st.write(source["title"])
            st.caption(source["original_url"])
            left, middle, right = st.columns(3)
            left.link_button("Open original", source["original_url"])
            if middle.button("Capture document", key=f"capture-{source_id}"):
                try:
                    preview = container.snapshots.capture(source_id)
                except AppError as error:
                    show_error(error)
                    continue
                st.session_state.pop("review_seen", None)
                _notice(
                    "This text was already captured; the existing version is shown."
                    if preview.reused
                    else "Snapshot saved. Read it below, then approve or reject.",
                    focus=preview.version_id,
                )
            if right.button("Remove from queue", key=f"dequeue-{source_id}"):
                container.sources.remove_from_review_queue(source_id)
                _notice(
                    "Removed from the Review queue. The search result is kept.", "info", focus=None
                )


def _label(version: dict) -> str:
    title = json.loads(version["metadata_json"]).get("title") or version["title"]
    return f"{title} · {version['review_status']}"


def _segments(segments):
    with st.expander(f"Document text · {len(segments)} segment(s)", expanded=True):
        for segment in segments[:MAX_PREVIEW_SEGMENTS]:
            locator = segment.locator
            place = (
                f"page {locator.file_page}"
                if locator.kind == "pdf"
                else f"paragraph {locator.paragraph_index}"
            )
            st.caption(" › ".join([*segment.heading_path, place]))
            st.text(segment.text)
        if len(segments) > MAX_PREVIEW_SEGMENTS:
            st.caption(
                f"{len(segments) - MAX_PREVIEW_SEGMENTS} more segment(s) are not shown. "
                "Open the original to read the full document before approving."
            )


def _metadata_form(container: Container, version_id: str, seen_hash: str, meta: dict, stale):
    suffix = f"{version_id}-{seen_hash[:12]}"
    with st.form(f"metadata-{suffix}"):
        st.markdown("**Reviewed metadata**")
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
            "Jurisdiction",
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


def _pending_actions(container, version_id, seen_hash, reviewer, *, stale, readable):
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
        f"version: {row['version_status']} · snapshot {current_hash[:12]}"
    )
    link_left, link_right = st.columns(2)
    link_left.link_button("Open original", meta["original_url"])
    if meta.get("final_url") and meta["final_url"] != meta["original_url"]:
        link_right.caption(f"Captured from redirect target: {meta['final_url']}")
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
        st.caption("An unreadable snapshot cannot be approved. Capture the source again.")
    if notes := json.loads(row["extraction_notes_json"]):
        st.warning("Extraction limits: " + "; ".join(notes))
    if segments:
        _segments(segments)

    if row["review_status"] == "pending":
        _metadata_form(container, version_id, seen_hash, meta, stale)
        _pending_actions(
            container, version_id, seen_hash, reviewer, stale=stale, readable=bool(segments)
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
    labels = {v["id"]: _label(v) for v in versions}
    if st.session_state.get("review_version_id") not in labels:
        st.session_state["review_version_id"] = versions[0]["id"]
    left, right = st.columns([1, 2])
    with left:
        version_id = st.radio(
            "Documents",
            list(labels),
            format_func=labels.__getitem__,
            key="review_version_id",
        )
    with right:
        _version_detail(container, version_id, reviewer)


def render(container: Container):
    st.title("Review")
    st.write("Read the original document before approving it for the knowledge base.")
    reviewer = st.text_input(
        "Reviewer label", key="review_reviewer", placeholder="Your name or initials"
    )
    queue = container.sources.review_queue()
    versions = sorted(
        container.research.list_versions(),
        key=lambda v: STATUS_ORDER.get(v["review_status"], 9),
    )
    pending = [v for v in versions if v["review_status"] == "pending"]
    reviewed = [v for v in versions if v["review_status"] != "pending"]
    if focus := st.session_state.pop("review_focus", None):
        # Follow the document just captured or acted on into the step where it now is.
        status = next((v["review_status"] for v in versions if v["id"] == focus), None)
        if status:
            st.session_state["review_section"] = "review" if status == "pending" else "reviewed"
            st.session_state["review_version_id"] = focus
    if st.session_state.get("review_section") not in SECTIONS:
        st.session_state["review_section"] = "review" if pending or not queue else "capture"
    if notice := st.session_state.pop("review_notice", None):
        kind, message = notice
        {"warning": st.warning, "info": st.info}.get(kind, st.success)(message)
    titles = {
        "capture": f"1 · To capture ({len(queue)})",
        "review": f"2 · To review ({len(pending)})",
        "reviewed": f"Reviewed ({len(reviewed)})",
    }
    section = st.radio(
        "Review step",
        SECTIONS,
        format_func=titles.__getitem__,
        horizontal=True,
        key="review_section",
        label_visibility="collapsed",
    )
    st.caption(SECTION_HELP[section])
    if section == "capture":
        _capture_queue(container, queue)
    elif section == "review":
        _version_list(
            container,
            pending,
            reviewer,
            "No captured documents are waiting for review. Capture a source first.",
        )
    else:
        _version_list(container, reviewed, reviewer, "No documents have been reviewed yet.")
