import json
from uuid import uuid4

import streamlit as st

from gridlens.bootstrap import Container
from gridlens.contracts import AnswerEnvelope, RetrievalFilters
from gridlens.errors import AppError
from gridlens.services.citations import quotes_by_chunk, source_statuses
from gridlens.ui.common import empty_state, show_error

REGIONS = {
    "New Zealand (+ global)": "NZ",
    "United States (+ global)": "US",
    "Global only": "GLOBAL",
    "All regions (includes unknown)": "ALL",
}
SOURCE_TYPES = {
    "Policy": "policy",
    "Technical": "technical",
    "Paper": "paper",
    "Industry report": "industry_report",
    "Product": "product",
    "Unknown": "unknown",
}
FAILURES = {
    "AUTH_REQUIRED": "Sign in with ChatGPT and choose a model in the sidebar to generate answers.",
    "AUTH_EXPIRED": "The ChatGPT session ended. Sign in again from the sidebar.",
    "ACCOUNT_CHANGED": "The selected account changed during the request. Ask again.",
    "PLAN_PERMISSION_MISSING": "This account has not granted ChatGPT plan usage to GridLens.",
    "USAGE_LIMITED": "Your ChatGPT plan usage limit was reached. Check usage and try later.",
    "MODEL_UNAVAILABLE": "The selected model is not available. Choose another in the sidebar.",
    "STREAM_INCOMPLETE": "The answer stream did not complete, so nothing was published.",
    "PROVIDER_TIMEOUT": "The answer took too long. Try again.",
    "PROVIDER_UNAVAILABLE": "ChatGPT is temporarily unavailable. Try again later.",
    "OUTPUT_INVALID": "The answer did not match the required format, even after one repair.",
    "CITATION_INVALID": "The answer cited text not in the evidence, so it was withheld.",
    "OUTPUT_MODE_UNSUPPORTED": "The model rejected structured output.",
    "GENERATION_TOO_LARGE": "The answer was larger than allowed.",
    "GENERATION_FAILED": "ChatGPT could not complete the answer.",
}


def _provider(container: Container):
    if container.settings.mode == "fixture":
        return container.answers
    from gridlens.providers.chatgpt_oauth import ChatGPTAnswerProvider
    from gridlens.ui.account import selected_model

    choice = selected_model(container)
    if choice is None:
        return None
    handle, slug = choice
    return ChatGPTAnswerProvider(
        container.sessions, handle, slug, timeout_seconds=container.settings.model_timeout_seconds
    )


def _missing_provider_hint(container: Container) -> str:
    """Name only the step still missing: sign-in, plan permission or a model."""
    handle = container.sessions.current()
    if handle is None:
        return FAILURES["AUTH_REQUIRED"]
    if not container.sessions.plan_usage_enabled(handle):
        return FAILURES["PLAN_PERMISSION_MISSING"] + " Reauthorize in the sidebar."
    return "Choose a model in the sidebar to generate answers."


def _location(locator: dict) -> str:
    if locator.get("kind") == "pdf":
        text = f"File page {locator.get('file_page')}"
        if locator.get("printed_page"):
            text += f" (printed page {locator['printed_page']})"
        return text
    parts = [*locator.get("heading_path", []), f"paragraph {locator.get('paragraph_index')}"]
    return " › ".join(str(p) for p in parts if p)


def _show_answer(envelope: AnswerEnvelope, statuses: dict[str, str]):
    if envelope.mode == "fixture":
        st.caption("Synthetic development answer — not real grid research.")
    if envelope.execution_status == "failed":
        code = (envelope.error or {}).get("code", "")
        st.error(FAILURES.get(code, f"The answer could not be completed ({code})."))
        if code == "USAGE_LIMITED":
            st.link_button("View ChatGPT usage", "https://chatgpt.com/settings/usage")
        return
    if envelope.execution_status == "stale_context":
        st.warning(
            "A source changed or was revoked while answering, so no answer was published. "
            "Ask again to use the current approved sources."
        )
        return
    labels = {
        "answered": ("success", "Answered from approved sources."),
        "partial": ("warning", "Partly answered — some of the question lacks evidence."),
        "insufficient": ("info", "Insufficient evidence in the approved sources."),
    }
    kind, text = labels[envelope.evidence_status]
    getattr(st, kind)(text)

    numbers = {c["chunk_id"]: c["number"] for c in envelope.citations}
    positions = {claim.claim_id: index for index, claim in enumerate(envelope.claims, start=1)}
    quotes = quotes_by_chunk(envelope.claims)
    for index, claim in enumerate(envelope.claims, start=1):
        cited = dict.fromkeys(numbers[e.chunk_id] for e in claim.evidence if e.chunk_id in numbers)
        marks = "".join(f" [{number}]" for number in cited)
        label = "Fact" if claim.kind == "fact" else "Inference"
        st.markdown(f"**{index} · {label}:** {claim.text}{marks}")
    if envelope.limitations:
        st.markdown("**Limitations**")
        for item in envelope.limitations:
            st.markdown(f"- {item}")
    if envelope.missing_evidence:
        st.markdown("**Missing evidence**")
        for missing in envelope.missing_evidence:
            st.markdown(f"- {missing.subquestion} — needs: {missing.needed_evidence}")
            st.caption("Suggested searches: " + "; ".join(missing.suggested_queries))
    if envelope.citations:
        st.markdown("**Sources**")
    for citation in envelope.citations:
        source = citation["source"]
        with st.expander(f"[{citation['number']}] {source.get('title') or 'Untitled'}"):
            st.caption(_location(citation["locator"]))
            for claim_id, quote in quotes.get(citation["chunk_id"], []) or [
                (None, citation["quote"])
            ]:
                st.markdown(f"> {quote}")
                if claim_id in positions:
                    st.caption(f"Supports statement {positions[claim_id]}")
            st.caption(
                " · ".join(
                    [
                        source.get("publisher") or "Publisher unknown",
                        source.get("published_at") or "Date unknown",
                        source.get("jurisdiction") or "UNKNOWN",
                        source.get("source_type") or "unknown",
                    ]
                )
            )
            status = statuses.get(source.get("version_id"), "not_current")
            if status != "current":
                st.warning(STATUS_LABELS[status])
            if source.get("original_url"):
                st.link_button("Open original", source["original_url"])


STATUS_LABELS = {
    "revoked": "Historical: this source's approval was revoked after the answer.",
    "superseded": "Historical: a newer version of this source has replaced it.",
    "not_current": "Historical: this source version is not currently searchable.",
}


def _statuses(container: Container, envelope: AnswerEnvelope) -> dict[str, str]:
    """Recomputed on every view; the stored quote and location are never rewritten."""
    fingerprint = container.ingestion.fingerprint if container.ingestion else None
    ids = sorted({c["source"].get("version_id") for c in envelope.citations})
    return source_statuses(container.db, ids, fingerprint)


def _ask_tab(container: Container):
    service = container.answer_service
    if service is None:
        st.info("Answers need the local index. In live mode run `gridlens prepare-model` first.")
        return
    provider = _provider(container)
    if provider is None:
        st.info(_missing_provider_hint(container) + " Without it, only scope checks can run.")
    with st.form("ask"):
        question = st.text_area(
            "Question",
            placeholder="Who is involved in a large-load connection in NZ?",
            key="ask_question",
        )
        left, right = st.columns(2)
        region = left.selectbox("Region", list(REGIONS), key="ask_region")
        types = right.multiselect("Source types", list(SOURCE_TYPES), key="ask_types")
        submitted = st.form_submit_button("Ask GridLens")
    if submitted:
        try:
            filters = RetrievalFilters(
                region=REGIONS[region], source_types=[SOURCE_TYPES[t] for t in types]
            )
            # Kept until the answer is saved, so a rerun can never call the model again.
            key = st.session_state.setdefault("ask_operation_key", f"ask-{uuid4()}")
            with st.spinner("Searching approved sources and checking citations…"):
                service.ask(question, filters, key, provider)
            st.session_state["ask_selected_key"] = key
            st.session_state.pop("ask_operation_key", None)
        except AppError as error:
            if error.code == "INVALID_INPUT":
                st.error("Ask a question between 3 and 2000 characters.")
            elif error.code == "EMBEDDING_INPUT_TOO_LONG":
                st.error("The question is too long for the search model. Shorten it.")
            else:
                show_error(error)

    history = container.qa.list_answers()
    if not history:
        empty_state("No questions asked yet.")
        return
    keys = {r["operation_key"]: r for r in history}
    selected = st.session_state.get("ask_selected_key")
    if selected not in keys:
        selected = history[0]["operation_key"]
    chosen = st.selectbox(
        "History",
        list(keys),
        index=list(keys).index(selected),
        format_func=lambda k: (
            f"{keys[k]['question'][:80]} · {keys[k]['execution_status']}"
            + (f"/{keys[k]['evidence_status']}" if keys[k]["evidence_status"] else "")
        ),
        key=f"ask_history_{selected}",
    )
    st.session_state["ask_selected_key"] = chosen
    record = keys[chosen]
    st.markdown(f"#### {record['question']}")
    filters = json.loads(record["filters_json"])
    st.caption(f"Region {filters.get('region')} · asked {record['created_at'][:19]} UTC")
    envelope = service.replay(chosen)  # stored result; never a new model call
    _show_answer(envelope, _statuses(container, envelope))


REASONS = {
    "no_evidence": "No approved source covers this yet",
    "partial_coverage": "Approved sources cover only part of this",
    "jurisdiction_mismatch": "Approved sources are for another region",
    "freshness_unverified": "Approved sources may be out of date",
    "conflicting_evidence": "Approved sources disagree",
    "needs_external_validation": "Needs a source outside the knowledge base",
}


def _gap_detail(container: Container, gap: dict):
    scope = json.loads(gap["scope_json"])
    filters = scope.get("filters", {})
    queries = json.loads(gap["suggested_queries_json"])
    st.markdown(f"#### {gap['question']}")
    types = ", ".join(filters.get("source_types") or []) or "all"
    st.caption(
        f"Status {gap['status']} · region {filters.get('region', 'NZ')} · types {types} · "
        f"updated {gap['updated_at'][:19]}"
    )
    st.markdown(f"**Why:** {REASONS.get(gap['reason_type'], gap['reason_type'])}")
    st.markdown(f"**Sub-question:** {scope.get('subquestion', gap['question'])}")
    st.markdown(f"**Missing evidence:** {gap['missing_evidence']}")
    if gap["resolution_note"]:
        st.markdown(f"**Note:** {gap['resolution_note']}")
    existing = [
        row
        for row in container.qa.list_answers()
        if row["id"] == gap["qa_id"] and row["answer_json"]
    ]
    cited = json.loads(existing[0]["answer_json"]).get("citations", []) if existing else []
    if cited:
        st.markdown("**Evidence already found:**")
        for citation in cited:
            st.caption(f"[{citation['number']}] {citation['source'].get('title') or 'Untitled'}")
    else:
        st.caption("No approved evidence was cited for this question yet.")

    st.markdown("**Suggested searches**")
    for index, query in enumerate(queries):
        left, right = st.columns([3, 1])
        left.write(query)
        if right.button("Use in Discover", key=f"gap-query-{gap['id']}-{index}"):
            st.session_state["discover_prefill"] = query
            st.success("Query ready. Open Discover from the navigation and click Search.")

    gap_id = gap["id"]
    if gap["status"] != "open":
        if st.button("Reopen", key=f"gap-reopen-{gap_id}"):
            _gap_action(lambda: container.gaps.reopen(gap_id), "Gap reopened.")
        return
    with st.form(f"gap-edit-{gap_id}"):
        st.markdown("**Edit**")
        reason = st.selectbox(
            "Reason",
            list(REASONS),
            index=list(REASONS).index(gap["reason_type"]),
            format_func=REASONS.__getitem__,
            key=f"gap-reason-{gap_id}",
        )
        sub = st.text_input(
            "Sub-question", value=scope.get("subquestion", ""), key=f"gap-sub-{gap_id}"
        )
        needed = st.text_input(
            "Missing evidence", value=gap["missing_evidence"], key=f"gap-needed-{gap_id}"
        )
        lines = st.text_area(
            "Suggested searches (one per line)",
            value="\n".join(queries),
            key=f"gap-queries-{gap_id}",
        )
        save = st.form_submit_button("Save changes")
    if save:
        from pydantic import ValidationError

        from gridlens.contracts import MissingEvidence

        try:
            missing = MissingEvidence(
                reason_type=reason,
                subquestion=sub,
                needed_evidence=needed,
                suggested_queries=[q.strip() for q in lines.splitlines() if q.strip()],
            )
        except ValidationError:
            st.error("Fill in the sub-question, missing evidence and at least one search.")
        else:
            _gap_action(lambda: container.gaps.edit(gap_id, missing), "Gap updated.")
    with st.form(f"gap-close-{gap_id}"):
        note = st.text_input("Resolution or dismissal note", key=f"gap-note-{gap_id}")
        left, right = st.columns(2)
        resolve = left.form_submit_button("Mark resolved")
        dismiss = right.form_submit_button("Dismiss")
    if resolve:
        _gap_action(lambda: container.gaps.resolve(gap_id, note), "Gap marked resolved.")
    if dismiss:
        _gap_action(lambda: container.gaps.dismiss(gap_id, note), "Gap dismissed.")


def _gap_action(action, message: str):
    try:
        action()
    except AppError as error:
        messages = {
            "RESOLUTION_NOTE_REQUIRED": "Add a note explaining how the gap was resolved.",
            "GAP_DUPLICATE": "Another open gap already covers this question.",
            "GAP_NOT_OPEN": "This gap is no longer open. Reload the list.",
        }
        st.error(messages.get(error.code, "The gap could not be changed."))
        return
    st.session_state["gap_notice"] = message
    st.rerun()


def _gaps_tab(container: Container):
    if notice := st.session_state.pop("gap_notice", None):
        st.success(notice)
    statuses = {"Open": "open", "Resolved": "resolved", "Dismissed": "dismissed", "All": None}
    label = st.radio("Show", list(statuses), horizontal=True, key="gap_status")
    gaps = container.gaps.list_gaps(statuses[label])
    if not gaps:
        empty_state("No knowledge gaps here. Gaps appear when an answer lacks evidence.")
        return
    st.caption(
        "Gaps describe what this knowledge base cannot yet support, not what research exists."
    )
    names = {g["id"]: f"{g['question'][:70]} · {g['status']}" for g in gaps}
    gap_id = st.selectbox(
        "Gap", list(names), format_func=names.__getitem__, key=f"gap_pick_{label}"
    )
    _gap_detail(container, next(g for g in gaps if g["id"] == gap_id))


def render(container: Container):
    st.title("Ask & Gaps")
    st.write("Ask a research question and check the evidence behind each claim.")
    ask, gaps = st.tabs(["Ask a question", "Knowledge gaps"])
    with ask:
        _ask_tab(container)
    with gaps:
        _gaps_tab(container)
