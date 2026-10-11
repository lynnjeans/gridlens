import json

import streamlit as st

from gridlens.bootstrap import Container
from gridlens.errors import AppError
from gridlens.ui.common import empty_state, index_version, show_error


def _status(version: dict, run: dict | None, searchable: bool) -> str:
    """Plain status; Approved is never shown as answerable unless SQLite says eligible."""
    review, ingestion = version["review_status"], version["ingestion_status"]
    if version["version_status"] == "superseded":
        return "Superseded by a newer version"
    if review == "pending":
        return "Waiting for review"
    if review == "rejected":
        return "Rejected"
    if review == "revoked":
        return "Approval revoked · not searchable"
    if searchable:
        return "Searchable"
    if ingestion == "processing":
        stage = run["stage"] if run else "starting"
        return f"Approved · indexing ({stage})"
    if ingestion == "failed":
        code = run["error_code"] if run and run["error_code"] else "unknown error"
        return f"Approved · indexing failed ({code})"
    if ingestion == "ready":
        return "Approved · indexed with another configuration"
    return "Approved · not indexed yet"


def _detail(container: Container, version: dict, run: dict | None, searchable: bool, reviewer):
    meta = json.loads(version["metadata_json"])
    st.subheader(meta.get("title") or "Untitled")
    st.caption(_status(version, run, searchable))
    if notice := st.session_state.pop("kb_notice", None):
        kind, message = notice
        (st.warning if kind == "warning" else st.success)(message)
    left, right = st.columns(2)
    left.markdown(
        f"**Review:** {version['review_status']}  \n"
        f"**Ingestion:** {version['ingestion_status']}  \n"
        f"**Version:** {version['version_status']}"
    )
    right.markdown(
        f"**Region:** {meta.get('jurisdiction', 'UNKNOWN')}  \n"
        f"**Type:** {meta.get('source_type', 'unknown')}  \n"
        f"**Published:** {meta.get('published_at') or 'Date unknown'}"
    )
    st.link_button("Open original", meta["original_url"])
    if notes := json.loads(version["extraction_notes_json"]):
        st.warning("Extraction limits: " + "; ".join(notes))
    if run:
        # Real stage and counts only; no estimated percentage.
        st.markdown(
            f"**Latest indexing run:** attempt {run['attempt']} · {run['status']} · "
            f"stage {run['stage']} · {run['indexed_chunks']}/{run['expected_chunks']} chunk(s)"
            + (f" · error {run['error_code']}" if run["error_code"] else "")
        )
    else:
        st.caption("No indexing run yet.")

    version_id = version["id"]
    processing = version["ingestion_status"] == "processing"
    if version["review_status"] == "approved" and version["version_status"] != "superseded":
        if version["ingestion_status"] in {"not_started", "failed", "processing"}:
            if st.button(
                "Retry indexing",
                key=f"kb-retry-{version_id}",
                disabled=processing or container.ingestion is None,
            ):
                message, kind = index_version(container, version_id, "kb-retry")
                st.session_state["kb_notice"] = (kind, message)
                st.rerun()
            if processing:
                st.info("Indexing is in progress. Reload the status to see the latest stage.")
        with st.form(f"kb-revoke-{version_id}"):
            reason = st.text_input("Revocation reason (optional)", key=f"kb-reason-{version_id}")
            revoke = st.form_submit_button("Revoke approval")
        if revoke:
            try:
                container.review.revoke(version_id, reviewer, reason)
            except AppError as error:
                show_error(error)
            else:
                st.session_state["kb_notice"] = (
                    "success",
                    "Approval revoked. This version is no longer searchable.",
                )
                st.rerun()


def render(container: Container):
    st.title("Knowledge Base")
    st.write("Only reviewed and fully processed documents can support an answer.")
    versions = container.research.list_versions()
    if not versions:
        empty_state("Your knowledge base is empty. Start by discovering and reviewing sources.")
        return
    searchable = (
        {
            v["id"]
            for v in container.research.eligible_versions(
                container.ingestion.fingerprint, jurisdiction=None
            )
        }
        if container.ingestion
        else set()
    )
    runs = container.research.latest_ingestion_runs()
    rows = []
    for version in versions:
        meta = json.loads(version["metadata_json"])
        rows.append(
            {
                "Title": meta.get("title") or version["title"],
                "Region": meta.get("jurisdiction", "UNKNOWN"),
                "Type": meta.get("source_type", "unknown"),
                "Review": version["review_status"],
                "Ingestion": version["ingestion_status"],
                "Version": version["version_status"],
                "Searchable": "yes" if version["id"] in searchable else "no",
                "Status": _status(version, runs.get(version["id"]), version["id"] in searchable),
            }
        )
    counts = {
        "searchable": len(searchable),
        "awaiting review": sum(v["review_status"] == "pending" for v in versions),
        "approved, not searchable": sum(
            v["review_status"] == "approved"
            and v["version_status"] != "superseded"
            and v["id"] not in searchable
            for v in versions
        ),
    }
    st.caption(" · ".join(f"{n} {label}" for label, n in counts.items()))
    st.dataframe(rows, hide_index=True)
    if container.ingestion is None:
        st.info("Indexing needs the local model; run `gridlens prepare-model` for live mode.")

    st.divider()
    reviewer = st.text_input("Reviewer label", key="kb_reviewer", placeholder="Name or initials")
    labels = {v["id"]: f"{r['Title']} · {r['Status']}" for v, r in zip(versions, rows, strict=True)}
    version_id = st.selectbox(
        "Version details", list(labels), format_func=labels.__getitem__, key="kb_version_id"
    )
    if st.button("Reload status", key="kb-reload"):
        st.rerun()
    version = next(v for v in versions if v["id"] == version_id)
    _detail(container, version, runs.get(version_id), version_id in searchable, reviewer)
