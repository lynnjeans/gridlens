# GridLens

Project repository: [lynnjeans/gridlens](https://github.com/lynnjeans/gridlens).
The local `origin` points to this repository; the initial local branch follows
its `master` default. The current source is published on `master`.

A local research assistant for data-centre grid connections. The source-discovery
milestone is implemented: the local web UI can search through Tavily when configured,
store deduplicated candidate sources, select a source for review, and manually add a
public URL as a pending lead. Bounded capture, HTML/PDF extraction, immutable snapshots
and review-state rules are connected to the Review page (capture, preview, metadata
correction, approve/reject/revoke/reopen). Approving a version on the Review page indexes it
(deterministic chunking, pinned local BGE embeddings, local Chroma) and publishes it as
Ready/Active only after a complete, verified index; live indexing needs `prepare-model`.
Approved-only retrieval (SQLite eligibility whitelist, reviewed-metadata region rules) is
implemented, and the Knowledge Base page shows review/ingestion/version status with
Retry and Revoke. ChatGPT generation
and real Q&A are **not connected yet**. No grid calculation or pandapower/OpenDSS is included.

## Run locally

Requires Python **3.12**. Use the project environment, rather than macOS's system Python.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install -e . --no-deps
python -m gridlens.cli init-db
python -m streamlit run app.py --server.address 127.0.0.1
```

Open [GridLens](http://127.0.0.1:8501). Default mode is `fixture`: synthetic, offline
development only. Copy `.env.example` to `.env` when configuration is needed.
For `APP_MODE=live`, storage uses a separate `data/live/` directory. Add
`TAVILY_API_KEY` to the local `.env` to enable source search. Without it the app still
starts and shows that search is unavailable. Fixture mode uses synthetic candidates.

With the environment already installed, `./run.sh` starts the local app directly.
This first implementation is verified on macOS; protected storage uses POSIX
file permissions and locking. Windows support is not yet implemented.

## Checks

```bash
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m gridlens.cli doctor
```

Tests block network connections and use temporary databases/auth directories. AppTest
covers all four pages. SQLite constraints and eligibility are tested separately;
synthetic tests cannot prove research accuracy or real subscription access.

## Credentials and models

Future generation uses the official **Sign in with ChatGPT** plan-usage flow, with
the user's consent. It does not need an OpenAI platform API key. Tokens must live
outside this repository in an owner-only user configuration directory; the first
milestone implemented storage. Sign-in is now implemented (loopback PKCE, verified ID token,
issued client ID) and can be run explicitly in live mode:

```bash
APP_MODE=live .venv/bin/python -m gridlens.cli login
```

It opens the official page in your browser; you sign in and approve GridLens yourself.
Tokens are stored only in the owner-only `AUTH_DIR` (default `~/.config/gridlens`).
Sign out with `python -m gridlens.cli logout --account <registration prefix>` (revokes the
refresh token when confirmed, always clears local tokens). A real sign-in, refresh and
sign-out have not been verified by the developers yet.
Source discovery uses a separate Tavily search key. Embeddings use a pinned local
`BAAI/bge-small-en-v1.5` model on CPU. Download it once, explicitly (about 134 MB, into
the git-ignored `models/` or `LOCAL_MODEL_DIR`):

```bash
python -m gridlens.cli prepare-model
python -m pytest -m local_model -q
```

Normal runs only load local files; nothing is downloaded automatically. The command
prints the resolved commit, which can be pinned as `EMBEDDING_REVISION` in `.env`.

`requirements.lock` pins the installed core/dev/auth/embeddings/vectors dependencies on Python
3.12 (resolved on macOS; includes torch). `requirements.lock` is generated from `pyproject.toml` with uv pip compile;
commands and resolved environment details are in `docs/progress.md`. Chroma (`vectors` extra,
chromadb 1.5.9) is locked too; it runs locally with telemetry off and never uses its default
embedding model.

For an AI handoff, read root `AGENTS.md` and `docs/HANDOFF.md` first.
The Ask page answers from approved sources with verified, numbered citations (fixture
mode end to end; live mode needs sign-in and a selected model). Next development
milestone: T26 (refresh and historical citation status). Knowledge gaps are recorded,
deduplicated, reviewable in the Gaps tab, and can prefill Discover. In live mode the sidebar
offers Continue with ChatGPT, account and model pickers (from your account's own catalog),
Reauthorize, Sign out and the usage link. The current
source can be obtained from the configured GitHub repository.

Read `docs/01_DEVELOPMENT_SPEC.md`, `docs/tasks.json` and `docs/progress.md` for
contracts and actual completion evidence. The documents describe future behavior;
they do not mean the full application or research acceptance has been completed.

