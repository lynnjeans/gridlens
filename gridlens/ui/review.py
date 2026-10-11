import streamlit as st

from gridlens.bootstrap import Container
from gridlens.ui.common import empty_state


def render(container: Container):
    st.title("Review")
    st.write("Read the original document before approving it for the knowledge base.")
    if source_id := st.session_state.get("selected_source_id"):
        source = container.sources.get_source(source_id)
        if source:
            with st.container(border=True):
                st.subheader("Selected source")
                st.write(source["title"])
                st.link_button("Open original", source["original_url"])
                st.caption("This is a pending lead. Capture and approval are the next step.")
    versions = container.research.list_versions()
    pending = [v for v in versions if v["review_status"] == "pending"]
    if not pending:
        empty_state("No documents are waiting for review.")
    else:
        st.dataframe([{k: v[k] for k in ("title", "review_status")} for v in pending])
    st.caption("Document capture and approval actions are being developed next.")
