# GridLens

A local research assistant for data-centre grid connections. You search for public
sources, read and approve them yourself, and ask questions that are answered only from
the sources you approved, with numbered citations you can check against the saved text.
Missing evidence becomes a tracked knowledge gap, and the work can be exported as a
Markdown research log. GridLens performs no grid calculations.

Repository: [lynnjeans/gridlens](https://github.com/lynnjeans/gridlens) (`master`).

**Status (2026-10-12).** Every feature is implemented and passes the offline test suite,
including a synthetic end-to-end and trust-boundary regression. Not yet done:
a real ChatGPT sign-in, real answers, a real Tavily/SerpApi search, the real-corpus evaluation
with human gold answers and scores (T31), and a human UI check. Passing tests is **not**
research acceptance; see `docs/KNOWN_LIMITATIONS.md`.

## Install

Requires Python **3.12** (not macOS's system Python). From this directory:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install -e . --no-deps
python -m gridlens.cli init-db
```

`requirements.lock` pins core, dev, auth, embeddings (sentence-transformers 6.1.0, torch
2.14.1) and vectors (chromadb 1.5.9) on Python 3.12, resolved on macOS with
`uv pip compile pyproject.toml --extra dev --extra auth --extra embeddings --extra vectors`.
Protected credential storage uses POSIX permissions; Windows is not supported yet.

## Run

```bash
python -m streamlit run app.py --server.address 127.0.0.1   # or ./run.sh
```

Open [http://127.0.0.1:8501](http://127.0.0.1:8501). Pages: **Discover** (search or add a
URL), **Review** (capture, read, correct metadata, approve/reject; approval indexes the
text), **Knowledge Base** (status, retry, revoke, refresh, export) and **Ask & Gaps**
(questions, citations, history, knowledge gaps).

### Modes

- `APP_MODE=fixture` (default): synthetic sources, fake embeddings and fake answers, no
  network, data in `data/fixture/`. Every page is usable; answers are marked synthetic.
- `APP_MODE=live`: real services, data in `data/live/`. Copy `.env.example` to `.env`.

### Live mode setup

1. **Search**: choose a provider in `.env` with `SEARCH_PROVIDER` and add only its key
   (a separate account and quota): `tavily` (default) uses `TAVILY_API_KEY`; `serpapi`
   (Google results via SerpApi) uses `SERPAPI_API_KEY`. Without a key, live Discover still
   accepts pasted URLs.
2. **Local embeddings**: download the pinned model once (about 134 MB into the
   git-ignored `models/`); normal runs never download.

   ```bash
   python -m gridlens.cli prepare-model
   python -m pytest -m local_model -q
   ```

3. **ChatGPT answers**: in the sidebar choose **Continue with ChatGPT** (or run
   `APP_MODE=live python -m gridlens.cli login`). The official OpenAI page opens in your
   browser; you sign in and approve GridLens yourself. This uses your ChatGPT plan's
   usage, not an API key; availability depends on your account, and the sidebar links to
   [ChatGPT usage](https://chatgpt.com/settings/usage). Then pick a model from your
   account's catalog. Tokens stay in the owner-only `AUTH_DIR` (default
   `~/.config/gridlens`), are refreshed automatically, and are cleared by **Sign out**
   (or `python -m gridlens.cli logout --account <prefix>`).

## Checks and tools

```bash
python -m pytest -q                 # offline: network blocked, temporary storage
python -m ruff check . && python -m ruff format --check .
python -m gridlens.cli doctor       # offline configuration and storage checks, no secrets
python -m gridlens.cli recover      # mark runs left by a crashed process as interrupted
python -m pytest -m local_model -q  # real local model (after prepare-model)
```

Live tests are opt-in (`-m live` plus `GRIDLENS_LIVE_*=1`, see `tests/live/`) and use
your own account. Evaluation (`evals/`):

```bash
python -m gridlens.cli evaluate --mode fixture          # or --mode live --model <slug>
python -m gridlens.cli evaluate-score --run artifacts/evals/<run>
```

Gold answers (`evals/gold.json`) and review scores are written by people only; until
they exist every metric reports `awaiting_input`, and fixture runs never count.

## Data and backup

Research data lives in `data/<mode>/` (SQLite `research.sqlite3`, `snapshots/`,
`chroma/`, `locks/`, `logs/`); models in `models/`; credentials in `AUTH_DIR`. All are
git-ignored. To back up, stop the app and copy `data/live/` (the Chroma index can be
rebuilt by re-indexing; snapshots and the database cannot). Never copy `AUTH_DIR`
between people.

## More

- `docs/DEMO.md` — a 6–8 minute demo script.
- `docs/KNOWN_LIMITATIONS.md` — limits, unverified items and next steps.
- `docs/HANDOFF.md`, `AGENTS.md` — for the next developer or AI agent.
- `docs/01_DEVELOPMENT_SPEC.md`, `docs/tasks.json`, `docs/progress.md` — contracts and
  the actual evidence for each task.
