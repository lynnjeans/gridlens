import streamlit as st

from gridlens.bootstrap import Container
from gridlens.ui.common import empty_state


def render(container: Container):
    st.title("Knowledge Base")
    st.write("Only reviewed and fully processed documents can support an answer.")
    versions = container.research.list_versions()
    if versions:
        st.dataframe(
            [{k: v[k] for k in ("title", "review_status", "ingestion_status")} for v in versions]
        )
    else:
        empty_state("Your knowledge base is empty. Start by discovering and reviewing sources.")
    st.caption("Ingestion, retries and version management will be added in later milestones.")
