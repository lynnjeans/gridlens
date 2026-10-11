"""Local setup commands; never print credentials."""

import argparse
import json

from gridlens.config import Settings
from gridlens.db import Database


def main():
    parser = argparse.ArgumentParser(description="GridLens local development tools")
    parser.add_argument("command", choices=["init-db", "doctor"])
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command == "init-db":
        Database(settings.data_dir / "research.sqlite3").initialize()
        print(f"Database initialized ({settings.mode}).")
    else:
        print(
            json.dumps(
                {
                    "mode": settings.mode,
                    "python_required": "3.12",
                    "search_key_configured": bool(settings.tavily_api_key.get_secret_value()),
                    "oauth_login": "not_implemented",
                    "model_download": "not_performed",
                    "milestone": "source_discovery",
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
