"""Local setup commands; never print credentials."""

import argparse
import json
import sys

from gridlens.config import Settings
from gridlens.db import Database
from gridlens.errors import AppError
from gridlens.providers.local_embeddings import prepare_model, read_manifest


def main():
    parser = argparse.ArgumentParser(description="GridLens local development tools")
    parser.add_argument(
        "command", choices=["init-db", "doctor", "prepare-model", "login", "logout"]
    )
    parser.add_argument("--account", help="registration ID for login (sign in again) or logout")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command == "init-db":
        Database(settings.data_dir / "research.sqlite3").initialize()
        print(f"Database initialized ({settings.mode}).")
    elif args.command == "login":
        _login(settings, args.account)
    elif args.command == "logout":
        _logout(settings, args.account)
    elif args.command == "prepare-model":
        # The only command that downloads model files; it runs only when invoked.
        print(f"Downloading {settings.embedding_model} into {settings.local_model_dir} ...")
        try:
            manifest = prepare_model(settings)
        except AppError as error:
            print(f"{error.code}: {error.message}", file=sys.stderr)
            raise SystemExit(1) from None
        print(
            f"Prepared {manifest.model_id} at revision {manifest.revision} "
            f"({manifest.dimensions} dimensions, {manifest.max_seq_length} tokens).\n"
            f"Optionally pin it in .env: EMBEDDING_REVISION={manifest.revision}"
        )
    else:
        try:
            revision = read_manifest(settings).revision
            model = {"model_download": "prepared", "model_revision": revision}
        except AppError:
            model = {"model_download": "not_performed"}
        print(
            json.dumps(
                {
                    "mode": settings.mode,
                    "python_required": "3.12",
                    "search_key_configured": bool(settings.tavily_api_key.get_secret_value()),
                    "oauth_login": "live_cli_only_not_verified",
                    **model,
                    "milestone": "review_and_local_embeddings",
                },
                indent=2,
            )
        )


def _login(settings: Settings, account: str | None) -> None:
    from gridlens.auth.credentials import FileCredentialStore
    from gridlens.auth.oauth import OAuthLogin, run_browser_login

    if settings.mode != "live":
        print("Sign-in uses your real ChatGPT account; set APP_MODE=live.", file=sys.stderr)
        raise SystemExit(1)
    print("Opening the official ChatGPT sign-in page in your browser ...")
    try:
        result = run_browser_login(
            OAuthLogin(FileCredentialStore(settings.auth_dir)), registration_id=account
        )
    except AppError as error:
        print(f"{error.code}: {error.message}", file=sys.stderr)
        raise SystemExit(1) from None
    # Never print tokens; the registration ID is an opaque local hash.
    print(f"Signed in: {result.label} (registration {result.registration_id[:12]}…)")
    if result.plan_usage_enabled:
        print("ChatGPT plan usage is authorized for this account.")
    else:
        print("Signed in, but ChatGPT plan usage was not granted; answers stay disabled.")


def _logout(settings: Settings, account: str | None) -> None:
    from gridlens.auth.credentials import FileCredentialStore
    from gridlens.auth.sessions import SessionManager

    store = FileCredentialStore(settings.auth_dir)
    matches = [s for s in store.summaries() if account and s.registration_id.startswith(account)]
    if len(matches) != 1:
        print("Pass --account with a registration ID prefix shown by login.", file=sys.stderr)
        raise SystemExit(1)
    result = SessionManager(store).sign_out(matches[0].registration_id)
    print(f"Signed out {matches[0].label}; local tokens cleared.")
    if not result.remote_revocation_confirmed:
        print(
            "Remote revocation was not confirmed. You can also disconnect GridLens in "
            "ChatGPT Settings."
        )


if __name__ == "__main__":
    main()
