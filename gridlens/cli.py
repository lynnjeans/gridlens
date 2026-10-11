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
    parser.add_argument("command", choices=["init-db", "doctor", "prepare-model"])
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command == "init-db":
        Database(settings.data_dir / "research.sqlite3").initialize()
        print(f"Database initialized ({settings.mode}).")
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
                    "oauth_login": "not_implemented",
                    **model,
                    "milestone": "review_and_local_embeddings",
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
