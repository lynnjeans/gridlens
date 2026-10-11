# GridLens

Project repository: [lynnjeans/gridlens](https://github.com/lynnjeans/gridlens).
The local `origin` points to this repository; the initial local branch follows
its `master` default. The current source is published on `master`.

A local research assistant for data-centre grid connections. The source-discovery
milestone is implemented: the local web UI can search through Tavily when configured,
store deduplicated candidate sources, select a source for review, and manually add a
public URL as a pending lead. Bounded capture, HTML/PDF extraction, immutable snapshots
and review-state rules are connected to the Review page (capture, preview, metadata
correction, approve/reject/revoke/reopen). Indexing, ChatGPT OAuth
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
milestone implements storage but does not request or create a real session.
Source discovery uses a separate Tavily search key. Embeddings will use a pinned
local BGE model, downloaded explicitly in a later task. Neither model weights nor
heavy model libraries are installed during this foundation milestone.

`requirements.lock` pins the installed foundation/dev/auth dependencies on Python
3.12. `requirements.lock` is generated from `pyproject.toml` with uv pip compile;
commands and resolved environment details are in `docs/progress.md`. Model dependencies
are declared in the optional `models` extra and will be locked/verified when implemented.

For an AI handoff, read root `AGENTS.md` and `docs/HANDOFF.md` first.
Next development milestone: T16 (local embeddings). The current
source can be obtained from the configured GitHub repository.

Read `docs/01_DEVELOPMENT_SPEC.md`, `docs/tasks.json` and `docs/progress.md` for
contracts and actual completion evidence. The documents describe future behavior;
they do not mean the full application or research acceptance has been completed.

