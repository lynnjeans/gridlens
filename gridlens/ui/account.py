"""Sidebar account and model selection. Tokens never enter Streamlit state or the page."""

import streamlit as st

from gridlens.auth.oauth import run_browser_login
from gridlens.auth.sessions import SessionHandle
from gridlens.bootstrap import Container
from gridlens.errors import AppError
from gridlens.ui.common import show_error

USAGE_URL = "https://chatgpt.com/settings/usage"
AUTH_MESSAGES = {
    "AUTH_EXPIRED": "The ChatGPT session ended. Sign in again.",
    "AUTH_REQUIRED": "Sign in to this ChatGPT account again.",
    "AUTH_REFRESH_UNAVAILABLE": "ChatGPT could not be reached. Try again later.",
    "PLAN_PERMISSION_MISSING": "This account has not granted ChatGPT plan usage to GridLens.",
    "USAGE_LIMITED": "The ChatGPT plan usage limit was reached. Check your usage.",
    "MODEL_CATALOG_UNAVAILABLE": "The model list could not be loaded. Refresh later.",
    "ACCOUNT_CHANGED": "The selected account changed. Load its models again.",
}


def _key(handle: SessionHandle) -> str:
    return f"{handle.registration_id}:{handle.epoch}"


def selected_model(container: Container) -> tuple[SessionHandle, str] | None:
    """The current account and a model from that same account's catalog, or None."""
    handle = container.sessions.current() if container.settings.mode == "live" else None
    if handle is None or not container.sessions.plan_usage_enabled(handle):
        return None
    catalog = st.session_state.get("account_catalog") or {}
    slug = st.session_state.get("account_model")
    slugs = {m["slug"] for m in catalog.get("models", [])}
    if catalog.get("key") != _key(handle) or slug not in slugs:
        return None
    return handle, slug


def _sign_in(container: Container, registration_id: str | None = None):
    with st.spinner("Complete sign-in in your browser…"):
        try:
            result = run_browser_login(container.oauth, registration_id=registration_id)
            handle = container.sessions.select(result.registration_id)
        except AppError as error:
            st.session_state["account_notice"] = ("warning", _message(error))
        else:
            _reset_catalog()
            message = f"Signed in as {result.label}."
            if not result.plan_usage_enabled:
                message += " ChatGPT plan usage was not granted, so answers stay disabled."
            st.session_state["account_notice"] = ("success", message)
            st.session_state["account_selected"] = handle.registration_id
    st.rerun()


def _message(error: AppError) -> str:
    return AUTH_MESSAGES.get(error.code, f"Sign-in did not complete ({error.code}).")


def _reset_catalog():
    st.session_state.pop("account_catalog", None)
    st.session_state.pop("account_model", None)


def _load_catalog(container: Container, handle: SessionHandle):
    try:
        models = [m.model_dump() for m in container.catalog.fetch(handle)]
        error = None
    except AppError as failure:
        models, error = [], failure.code
    # Cached per account selection so reruns never repeat the request.
    st.session_state["account_catalog"] = {"key": _key(handle), "models": models, "error": error}


def render_account(container: Container):
    st.caption("CHATGPT ACCOUNT")
    if container.settings.mode != "live":
        st.caption("Development mode uses synthetic answers. Sign-in is available in live mode.")
        st.button("Continue with ChatGPT", disabled=True, use_container_width=True)
        st.link_button("View ChatGPT usage", USAGE_URL)
        return
    if notice := st.session_state.pop("account_notice", None):
        kind, message = notice
        (st.warning if kind == "warning" else st.success)(message)

    try:
        accounts = [a for a in container.credentials.summaries() if a.connected]
    except AppError as error:
        show_error(error)
        return
    if not accounts:
        st.caption("Sign in with your own ChatGPT account to generate answers.")
        if st.button("Continue with ChatGPT", type="primary", use_container_width=True):
            _sign_in(container)
        st.link_button("View ChatGPT usage", USAGE_URL)
        return

    handle = container.sessions.current()
    labels = {a.registration_id: a.label for a in accounts}
    current = handle.registration_id if handle and handle.registration_id in labels else None
    chosen = st.selectbox(
        "Account",
        list(labels),
        index=list(labels).index(current) if current else None,
        format_func=labels.__getitem__,
        placeholder="Choose an account",
        key=f"account_picker_{current}",
    )
    if chosen and chosen != current:
        try:
            handle = container.sessions.select(chosen)
        except AppError as error:
            st.warning(_message(error))
            return
        _reset_catalog()
        st.rerun()
    if handle is None or handle.registration_id not in labels:
        st.caption("Choose an account to load its models.")
        return

    if not container.sessions.plan_usage_enabled(handle):
        st.warning(AUTH_MESSAGES["PLAN_PERMISSION_MISSING"] + " Reauthorize to grant it.")
    else:
        catalog = st.session_state.get("account_catalog")
        if not catalog or catalog.get("key") != _key(handle):
            _load_catalog(container, handle)
            catalog = st.session_state["account_catalog"]
        if catalog["error"]:
            st.warning(AUTH_MESSAGES.get(catalog["error"], "The model list is unavailable."))
        elif not catalog["models"]:
            st.info("No models are listed for this account. Refresh later.")
        else:
            names = {m["slug"]: m["display_name"] for m in catalog["models"]}
            current_model = st.session_state.get("account_model")
            st.session_state["account_model"] = st.selectbox(
                "Model",
                list(names),
                index=list(names).index(current_model) if current_model in names else None,
                format_func=names.__getitem__,
                placeholder="Choose a model",
                key=f"account_model_picker_{_key(handle)}",
            )

    # Rarely used actions stay folded so the account and model pickers stand out.
    manage = st.expander("Manage account")
    if container.sessions.plan_usage_enabled(handle) and manage.button(
        "Refresh models", use_container_width=True
    ):
        _reset_catalog()
        st.rerun()
    left, right = manage.columns(2)
    if left.button("Reauthorize", key="account_reauth", use_container_width=True):
        _sign_in(container, handle.registration_id)
    if right.button("Sign out", use_container_width=True):
        result = container.sessions.sign_out(handle.registration_id)
        _reset_catalog()
        message = "Signed out; local tokens were cleared."
        if not result.remote_revocation_confirmed:
            message += (
                " Remote revocation was not confirmed; you can also disconnect GridLens"
                " in ChatGPT Settings."
            )
        st.session_state["account_notice"] = ("success", message)
        st.rerun()
    if manage.button("Add another account", use_container_width=True):
        _sign_in(container)
    st.link_button("View ChatGPT usage", USAGE_URL)
