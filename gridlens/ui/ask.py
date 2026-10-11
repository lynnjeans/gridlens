import streamlit as st

from gridlens.bootstrap import Container
from gridlens.ui.common import empty_state


def render(container: Container):
    st.title("Ask & Gaps")
    st.write("Ask a research question and check the evidence behind each claim.")
    ask, gaps = st.tabs(["Ask a question", "Knowledge gaps"])
    with ask:
        with st.form("ask"):
            st.text_area(
                "Question", placeholder="Who is involved in a large-load connection in NZ?"
            )
            st.form_submit_button("Ask GridLens", disabled=True)
        empty_state("Question answering will be available after ingestion and ChatGPT sign-in.")
    with gaps:
        if not container.qa.list_gaps():
            empty_state("No knowledge gaps recorded yet.")
