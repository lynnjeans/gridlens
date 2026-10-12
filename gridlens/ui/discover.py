import streamlit as st
from pydantic import ValidationError

from gridlens.bootstrap import Container
from gridlens.contracts import DiscoveryRequest, SearchRunDetail
from gridlens.errors import AppError
from gridlens.ui.common import empty_state, show_error

REGIONS = {"New Zealand": "NZ", "United States": "US", "All regions": "ALL"}
SOURCE_TYPES = {
    "Policy": "policy",
    "Technical": "technical",
    "Paper": "paper",
    "Industry report": "industry_report",
}


def _show_results(result: SearchRunDetail):
    if result.status == "partial":
        st.warning("Some searches failed. Successful candidates are shown below.")
    elif result.status == "failed":
        st.error("Search failed. No candidate sources were added from this operation.")
    elif not result.candidates:
        empty_state("No candidates were found. Try a more specific research topic.")
    st.caption(f"{result.calls_used} search call(s) · {len(result.candidates)} unique candidate(s)")
    for candidate in result.candidates:
        with st.container(border=True):
            st.subheader(candidate.title)
            details = [
                candidate.publisher or "Publisher unknown",
                candidate.published_at or "Date unknown",
            ]
            st.caption(" · ".join(details))
            st.write(candidate.snippet or "No search snippet was returned.")
            st.caption(candidate.relevance_reason)
            left, right = st.columns([1, 1])
            left.link_button("Open original", candidate.url)
            if right.button(
                "Select for review", key=f"review-{result.run_id}-{candidate.source_id}"
            ):
                st.session_state["selected_source_id"] = candidate.source_id
                st.success("Source selected. Open Review from the navigation.")


def render(container: Container):
    st.title("Discover")
    st.write("Find public policies, technical documents and research about grid connections.")
    if prefill := st.session_state.pop("discover_prefill", None):
        # Filled from a knowledge gap; nothing is searched until the user clicks Search.
        st.session_state["discover_topic"] = prefill
        st.info("A suggested query from a knowledge gap was filled in. Review it, then search.")
    with st.form("discover"):
        topic = st.text_input(
            "Research topic",
            placeholder="New Zealand large-load grid connection process",
            key="discover_topic",
        )
        left, right = st.columns(2)
        region_label = left.selectbox("Region", list(REGIONS), key="discover_region")
        type_labels = right.multiselect("Source types", list(SOURCE_TYPES), key="discover_types")
        submitted = st.form_submit_button(
            "Search sources", disabled=container.discovery.provider is None
        )
    if container.discovery.provider is None:
        st.info(
            "Live search needs the key of the selected search provider (SEARCH_PROVIDER) "
            "in the local .env file."
        )
    if submitted:
        try:
            request = DiscoveryRequest(
                topic=topic,
                region=REGIONS[region_label],
                source_types=[SOURCE_TYPES[label] for label in type_labels],
            )
            operation_key = st.session_state.get("discover_operation_key")
            if not operation_key:
                from uuid import uuid4

                operation_key = str(uuid4())
                st.session_state["discover_operation_key"] = operation_key
            result = container.discovery.discover(request, operation_key)
            st.session_state["discover_last_result"] = result.model_dump(mode="json")
            st.session_state.pop("discover_operation_key", None)
        except ValidationError:
            st.error("Enter a research topic between 3 and 500 characters.")
        except AppError as error:
            show_error(error)
    if data := st.session_state.get("discover_last_result"):
        _show_results(SearchRunDetail.model_validate(data))

    st.divider()
    st.subheader("Add a public URL")
    with st.form("manual-source"):
        manual_url = st.text_input("Source URL", placeholder="https://example.org/public-guide")
        add_submitted = st.form_submit_button("Add for review")
    if add_submitted:
        try:
            candidate = container.discovery.add_source(manual_url)
            st.session_state["selected_source_id"] = candidate.source_id
            st.success("Source saved as a pending lead. It has not been fetched or approved.")
        except AppError as error:
            show_error(error)
