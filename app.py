"""Run with: python -m streamlit run app.py"""

import streamlit as st
from pydantic import ValidationError

from gridlens.bootstrap import build_container
from gridlens.config import Settings
from gridlens.oplog import install_log_redaction
from gridlens.ui import ask, discover, knowledge_base, review
from gridlens.ui.common import sidebar

st.set_page_config(page_title="GridLens · Grid research", page_icon="🔎", layout="wide")
try:
    settings = Settings.from_env()
except ValidationError:
    st.error("Configuration is invalid. Check mode, data paths and limits in your local .env file.")
    st.stop()


# Do not put secrets in cache keys: keep the container assembly uncached for now.
container = build_container(settings)
install_log_redaction()
if not st.session_state.get("gridlens_recovered"):
    # Once per browser session: mark runs whose owner process has exited as interrupted.
    container.recovery.recover()
    st.session_state["gridlens_recovered"] = True
sidebar(container)
pages = [
    st.Page(
        lambda: discover.render(container), title="Discover", url_path="discover", default=True
    ),
    st.Page(lambda: review.render(container), title="Review", url_path="review"),
    st.Page(
        lambda: knowledge_base.render(container), title="Knowledge Base", url_path="knowledge-base"
    ),
    st.Page(lambda: ask.render(container), title="Ask & Gaps", url_path="ask"),
]
st.navigation(pages).run()
