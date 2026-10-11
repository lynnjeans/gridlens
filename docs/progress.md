# GridLens implementation progress

Date: 2026-10-11, Pacific/Auckland. Application: `gridlens/` in the Seen Ventures
project workspace. Synced `sources/` files were not changed.

## T06 — Tavily search adapter

Status: **implemented and verified offline**. The adapter uses the documented Tavily
Search endpoint with basic/general search, explicit result limits and generated answer,
raw content, images and automatic parameters disabled. It maps only candidate metadata
and safe snippets, skips malformed individual records, and maps authorization, quota,
HTTP and timeout failures to stable application errors without implicit retries.

`tests/unit/test_tavily.py`: **9 passed**. Ruff check and format check passed for the
adapter and its offline/live tests. The explicit live smoke test exists but was not run
because `TAVILY_API_KEY` is not configured. No real search calls or research records
were created. Next task: T07 search orchestration and persistence.

## T07 — Search orchestration and persistence

Status: **implemented and verified offline**. One user operation creates up to three
meaning-preserving queries, spends no more than three provider calls, canonicalizes
public URLs while preserving functional query parameters, removes common tracking
parameters, merges duplicates and stores at most ten candidates. SearchRun, SearchHit
and Source records are committed together after provider work. Completed operation keys
are persistent and replay without another provider call. Partial and failed runs retain
safe error codes, and unknown publication dates remain null.

Discovery unit and database integration suites: **11 passed**. They cover URL boundaries,
query generation, duplicates, stable ranking, limits, partial/all-failed behavior,
manual pending leads and idempotence after constructing a new service instance. No live
provider was used. Next task: T08 Discover UI.

## T08 — Discover UI and source selection

Status: **implemented and verified offline**. Discover now submits a validated topic,
region and source-type selection to the discovery service. It shows candidate metadata,
search snippets as non-evidence, relevance reasons and original links; empty, partial,
failed and missing-key states are distinct. A normal Streamlit rerun reads session/SQLite
state without repeating the provider operation. Search candidates and manually entered
public URLs can be selected for Review. Manual URLs are saved only as pending leads: no
content fetch, document version, approval or knowledge-base ingestion occurs.

Discover/navigation UI suites: **10 passed**. Full offline regression after T06–T08:

```text
.venv/bin/python -m pytest -q
67 passed, 1 deselected in 0.77s
.venv/bin/ruff check .
All checks passed!
.venv/bin/ruff format --check .
47 files already formatted
.venv/bin/python -m pip check
No broken requirements found.
```

The deselected test is the explicit Tavily live smoke. No `TAVILY_API_KEY` was configured,
so no real search relevance or provider account behavior was validated. Human research
acceptance was not run. The application is still local and uncommitted/unpushed. Next
milestone: T09–T14 for bounded capture, HTML/PDF extraction, immutable snapshots and
human review.

## T09 — Bounded public document capture

Status: **implemented and verified offline**. `DocumentFetcher` validates HTTP(S),
userinfo, standard ports and every DNS address before each request and redirect. It
allows at most three manually checked redirects, disables automatic following, limits
declared, streamed and decompressed bytes, enforces elapsed time, accepts only HTML or
PDF (with PDF magic validation), and returns final URL, normalized type, timestamp and
SHA-256. Safe application errors cover DNS, access, missing documents, rate limits,
timeouts, unsupported types and upstream failures.

`tests/unit/test_fetch.py`: **24 passed**. Full offline regression: **91 passed, 1 live
deselected**; Ruff and format checks passed. All fetch tests use HTTP and DNS mocks; no
arbitrary website was contacted. This is a local-app SSRF boundary, not a claim of
production-grade DNS rebinding isolation. Next tasks: T10/T11 parsing.

## T10 — HTML body and paragraph extraction

Status: **implemented and verified offline**. The deterministic parser prefers
`main`/`article`, removes scripts, styles, navigation and other non-content nodes,
and falls back to body paragraphs with an explicit warning. Each paragraph retains
its heading path and one-based locator. Numbers, conditions and Unicode are preserved.
Tables carry a warning that relationships were not reconstructed. Text that resembles
instructions remains inert document text, and empty pages return `HTML_EMPTY` rather
than substituting a search snippet.

`tests/unit/test_html_parser.py`: **5 passed**. Full regression: **96 passed, 1 live
deselected**; Ruff and format checks passed. Next task: T11 PDF parsing.

## T11 — PDF text and page extraction

Status: **implemented and verified offline**. PDF parsing runs in a terminable spawned
subprocess with a page limit and caller timeout. Text is emitted as deterministic
segments with one-based physical `file_page` locators; it does not invent printed page
numbers. Every segment warns that complex tables and multi-column reading order need
checking against the original. Scanned/empty, corrupt, encrypted, over-limit and timed-out
documents return stable errors; OCR remains outside scope.

`tests/unit/test_pdf_parser.py`: **6 passed**. Full offline regression: **102 passed,
1 live deselected**; Ruff, format and dependency checks passed. Next task: T12 immutable
capture snapshots.

## T12 — Immutable review snapshots

Status: **implemented and verified offline**. Capture dispatches bounded HTML/PDF results
to the matching parser and computes snapshot identity from semantic segments, reviewed
metadata and the parser version. Fetch timestamps, raw hashes and temporary segment IDs
do not affect identity. Raw bytes and canonical segment JSON are written with same-directory
temporary files and atomic replacement under controlled hash paths before the Pending/
Candidate database version is committed. Duplicate identities reuse the first immutable
files; changed content or reviewed metadata creates a new version. Failures mark the lead
failed and do not create an approvable partial version.

`tests/integration/test_snapshots.py`: **6 passed**. Full offline regression: **108 passed,
1 live deselected**; Ruff, format and dependency checks passed. The service is not yet
connected to Review; that occurs in T14 after the T13 review state machine.

## T13 — Human review state machine

Status: **implemented and verified offline**. Approve validates the expected preview hash,
stored raw hash, parsed body and recomputed semantic snapshot identity before binding the
approved hash. Reject requires a reason. Revoke immediately changes the authoritative
SQLite review state, so an otherwise Ready/Active version is excluded from retrieval.
Reopen is limited to Rejected/Revoked non-superseded versions and clears approval/index
state back to Pending/Candidate/Not started. Actual transitions append one review event
in the same transaction; exact repeats are idempotent and event-write failure rolls back
the state update.

`tests/integration/test_review.py`: **6 passed**. Full offline regression: **114 passed,
1 live deselected**; Ruff, format and dependency checks passed. Next task: T14 Review UI.

## T14 — Review page

Status: **implemented and verified offline**. Review lists captured versions (pending
first), captures the selected source only on an explicit button click, shows the verified
segment text with locators, extraction limits, original/redirect links, snapshot hash,
status and review history. Pending versions accept metadata corrections (title,
publisher, date, jurisdiction, source type); the service recomputes the snapshot hash
and the page binds actions to the hash the reviewer opened. If the stored hash changes,
the page shows a stale warning, disables approval and requires "Reload preview". An
unreadable or tampered snapshot shows an error and cannot be approved. Reject requires a
reason; approved versions can be revoked and rejected/revoked ones reopened. Reruns
do not repeat actions or events. Fixture mode uses a synthetic `FakeDocumentFetcher`;
live mode uses the bounded `DocumentFetcher`. Ingestion after approval is not wired yet
(T18); the page says indexing becomes available later.

`tests/ui/test_review_page.py`: **8 passed** (named to avoid a pytest basename clash with
`tests/integration/test_review.py`, which now has **7 passed**). Full offline
regression: **123 passed, 1 live deselected**; Ruff, format and pip check passed. One
early run of the new UI file failed once in 10.7s on the first test and did not repeat in
six later runs (likely a cold-start AppTest timeout). No manual browser check, live
capture or real source review was run. At the user's request T13 and T14 were committed
and pushed to `origin/master`. Next task: T16 local embeddings (T16 → T15, T17 → T18).

## T16 — Local embeddings and model preparation

Status: **implemented and verified offline and with the real local model**.
`LocalEmbeddingProvider` loads a prepared SentenceTransformers snapshot by local path
with `local_files_only=True`, `trust_remote_code=False` and CPU inference, only on first
use (importing the app does not import torch). It rejects empty input, counts tokens with
the model's own tokenizer including special tokens and rejects inputs over the model limit
before encoding (no truncation), encodes in batches of at most 16 with normalization, and
validates vector count, dimension, finite values and unit norm. Queries use the BGE v1.5
model-card instruction prefix; documents use none. The fingerprint covers model,
revision, tokenizer revision, dimensions, limit, prefixes, normalization and device.
Missing manifest/files or a revision differing from `EMBEDDING_REVISION` raises
`LOCAL_MODEL_MISSING`. Fixture mode still uses the fake provider; the local provider is
not yet wired into bootstrap or ingestion (T18).

`gridlens prepare-model` is the only download path. It fetches only the files needed by
SentenceTransformers into `LOCAL_MODEL_DIR` (default git-ignored `models/`), requires a
40-hex commit, checks the dimension, and writes `models/gridlens-model.json`.

With the user's approval: the `models` extra was split into `embeddings`
(`sentence-transformers>=6.1,<7`) and `vectors` (chromadb, still for T17).
`.venv/bin/uv pip compile pyproject.toml --extra dev --extra auth --extra embeddings
--python .venv/bin/python --output-file requirements.lock` added sentence-transformers
6.1.0, torch 2.14.1, transformers 5.19.0, huggingface-hub 1.33.0 and their dependencies
(existing pins unchanged), installed with `uv pip install -r requirements.lock`. The lock
is resolved for this macOS/Python 3.12 environment. A dry run listed 10 files (134.4 MB);
`prepare-model` then recorded revision `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`, 384 dimensions, 512 tokens.

Checks: `tests/unit/test_embeddings.py` **17 passed** (injected fake model).
`pytest -m local_model` with IP sockets still blocked: **2 passed** — 384-dim normalized
vectors, reproducible output, over-long input rejected; a grid query scored 0.656 against
a grid passage and 0.258 against an unrelated one. Full offline regression **140 passed,
3 deselected**; Ruff, format and pip check passed. Before asking, one `pip download` probe
resolved sentence-transformers 6.1.0 metadata and failed before saving a file. No ChatGPT
login, Chroma or ingestion was run. At the user's request T16 was committed and pushed
to `origin/master`. Next task: T15 chunking.

## T15 — Deterministic token chunking

Status: **implemented and verified offline and with the real local tokenizer**.
`gridlens/documents/chunking.py` (`segment-pack-v1`) groups consecutive segments by PDF
file page or HTML heading path, packs whole segments (blank-line joined) while the
embedding input — heading context + text, counted with special tokens by the model
tokenizer — fits `CHUNK_TOKENS`, and splits only a single over-budget segment into token
windows with `CHUNK_OVERLAP`. Windows are cut at tokenizer character offsets, so each
chunk `text` is an exact source substring (citation target); `embedding_text` adds only
the heading context. Over-long headings are left out of the embedding input but kept in
`heading_path`. Chunks never cross a page, section, document or version.
`index_fingerprint` hashes the embedding identity (model, revision, tokenizer revision,
dimensions, limit, prefixes, normalization, device), chunker version, size and overlap;
`chunk_id` hashes version, fingerprint, ordinal and text SHA-256 as canonical JSON.

Interface changes: `ChunkDTO` gained `ordinal`, `text_sha256`, `embedding_text`,
`heading_path` (whitespace preserved); new `Tokenizer` protocol; `LocalEmbeddingProvider`
gained `identity()` and `token_offsets()`; fixture `FakeTokenizer` and fake identity.

Checks: `tests/unit/test_chunking.py` **14 passed**. `pytest -m local_model` (IP sockets
blocked) **3 passed**, including the real BGE tokenizer at 350/50 on English and Chinese
long pages: 15 chunks, max 350 tokens, counts matching the real tokenizer, all embedded.
Full offline regression **154 passed, 4 deselected**; Ruff, format and pip check passed.
Not yet wired into ingestion (T18). At the user's request T15 was committed and pushed. Next task: T17 Chroma.

## Repository publication — 2026-10-11

The user explicitly requested publication. Before committing, `origin` was verified as
`https://github.com/lynnjeans/gridlens.git`, `master` had no remote heads, ignored runtime
paths were checked, and a credential-pattern scan found only labelled synthetic test
values. The current implementation and synchronized documentation were committed and
pushed to `origin/master`. No pull request or deployment was created.

## Foundation milestone — T01–T05 and T33

Status: **implemented and verified offline**. All remaining application tasks
are still todo. This milestone provides the foundation, not a working research
assistant: search, review actions, ingestion, RAG, gaps and ChatGPT login remain
unconnected. The UI disables unavailable actions and says what is pending.

| Task | Result | Evidence |
| --- | --- | --- |
| T01 | Independent local Git repository, Python 3.12 package, locked dependencies, launcher and safe configuration | Editable install, clean wheel install, `pip check`, Git ignore verification |
| T02 | Validated configuration, DTOs, safe errors and provider protocols | Contract tests; storage isolation and malformed answer/vector rejection |
| T03 | All initial SQLite tables, constraints, forward-only atomic initialization, basic repositories | Persistence, FK, unique active version/open gap, transaction rollback and eligible-source tests |
| T04 | Synthetic HTML/PDF/scenario fixtures and deterministic fake providers | Fixture manifest, real synthetic JWKS signature verification, rotating-token samples, fault modes and network-block test |
| T05 | Four-page Streamlit navigation and dependency assembly | AppTest for all pages and rerun behavior; actual browser navigation across all four pages and gaps tab |
| T33 | Stable host ID and protected, atomic per-registration credential store | File permissions, concurrent creation/read, write failure, path/identity checks, isolation and token clearing tests |

### Verification actually run

Environment: Python **3.12.14**, Streamlit **1.65.0**, Pydantic **2.14.0**, SQLite
standard library. Full installed versions are in `requirements.lock`.

```text
.venv/bin/python -m pytest -q
42 passed in 0.45s
.venv/bin/ruff check .
All checks passed!
.venv/bin/ruff format --check .
37 files already formatted
.venv/bin/python -m pip check
No broken requirements found.
.venv/bin/python -m gridlens.cli init-db
Database initialized (fixture).
```

`doctor` reported fixture mode, no search key, OAuth not implemented and no model
download. Tests use temporary storage and block IP sockets; Unix-domain sockets
are allowed only so Streamlit's local asyncio event loop can run. The explicit
network-block test still rejects an IP socket. No network-dependent app tests ran.

Dependency resolution used uv **0.13.0** in the project environment:

```text
uv pip compile pyproject.toml --extra dev --extra auth --output-file requirements.lock
uv pip sync --python .venv/bin/python requirements.lock
python -m pip install -e . --no-deps
python -m pip wheel --no-deps --wheel-dir artifacts/wheels .
```

A second clean virtual environment at ignored `artifacts/clean-env/` installed the
lock and built wheel; import, packaged migration loading and bootstrap were tested
outside the source package directory. Core/dev/auth dependencies are locked now;
the optional model extra will be locked when T16/T17 are implemented, avoiding an
unused torch/model installation in this milestone. Build-tool versions are not
application runtime dependencies.

Browser check: `http://127.0.0.1:8501`, bound to loopback. Discover, Review,
Knowledge Base, Ask & Gaps and the gaps tab visibly loaded without exceptions.
No real credentials or research sources were created. `git check-ignore` confirmed
runtime data, `.env` and `.venv` are excluded, while the auth source code is included.

### Corrections made during verification

- Allowed local Unix sockets for AppTest while continuing to block IP network access.
- Corrected `.gitignore` so runtime `/auth/` is excluded without hiding auth source code.
- Corrected an AppTest assertion to inspect the main page title separately from the sidebar.
- Added fixture auth-directory confinement and finite/dimensionally consistent vector checks.

### Limits and next tasks

- Real ChatGPT OAuth, plan permissions, model catalog, subscription inference and quota
  behavior: **not run; T34–T36/T21 remain todo**.
- Local BGE model installation and inference: **not run; T16 remains todo**.
- At this foundation checkpoint, search/capture/review were not implemented. T06–T08
  were completed in the later source-discovery milestone above; T09–T14 remain todo.
- Research acceptance T31: not run. No approved corpus, gold answers or human scores exist.
- Current Git state: origin is configured for lynnjeans/gridlens; no local commit, push, deployment or external messages.
- Protected storage currently targets macOS/Linux. Broader platform support needs a separate change.

The next milestone at this earlier checkpoint was T06–T08. It is now complete; current
next work is **T09–T14** for document capture and review. **T34** can still proceed independently.
No credential needs to be pasted into a conversation to implement offline adapters.

## Project repository linked — 2026-10-11

The user identified `https://github.com/lynnjeans/gridlens.git` as the project
repository. GitHub metadata and `git ls-remote` confirmed it is empty, with
`master` as its configured default branch. The local repository now uses that
URL for `origin` and the unborn local branch is named `master`. No files were
uploaded, no remote branches were changed and no GitHub pull request was created.

## AI handoff synchronized — 2026-10-11

Current-state audit confirms T01–T05 and T33 done, 30 tasks todo. Actual local Git
state: origin configured, master branch unborn, all application files untracked,
no commit or push. Repository linkage supersedes the earlier pre-link status.

Re-ran the existing baseline for handoff: 42 tests passed in 0.49s, Ruff check
passed, format check reported 37 files formatted, pip check passed. Doctor still
reports fixture mode, no search key, OAuth not implemented and no model download.
No live tests, model download, new browser check or research evaluation ran in
this documentation turn.

Added root AGENTS.md and docs/HANDOFF.md; updated README, execution guide and the
machine manifest so a successor starts at T06–T08 instead of repeating T01.
The application docs are authoritative. The output documentation mirror and ZIP
are refreshed snapshots; don't overwrite newer application docs with them.
A separate source handoff ZIP contains the current application and docs, excluding
Git metadata, virtual environments, runtime data/results and credentials.
No code behavior, task completion status or remote state was changed by this handoff.

## Standing documentation-sync instruction — 2026-10-11

The user requested automatic documentation updates after each feature. Root
AGENTS.md, the execution guide and HANDOFF now require updating task JSON/cards,
progress and handoff before reporting completion or starting the next feature.
Incomplete work and failed checks must also be recorded honestly. Interface/setup
changes additionally update the specification/README. Available output mirrors and
handoff archives are refreshed without runtime data or real credentials.
This records a development workflow preference, not a scheduled automation or a
GitHub push request. At the time of this documentation-only change, feature states were
6 done and 30 todo; the later discovery milestone supersedes that count.
