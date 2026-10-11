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
        st.subheader("ChatGPT connection")
        st.caption("Sign-in will be available after the authorization tasks are complete.")
        st.button("Continue with ChatGPT", disabled=True, use_container_width=True)
        st.link_button("View ChatGPT usage", "https://chatgpt.com/settings/usage")
        st.divider()
        st.caption("Discovery milestone · search runs only when you submit the form")


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
    }
    st.error(messages.get(error.code, "The operation could not be completed."))
