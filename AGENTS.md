# GridLens agent instructions

This is an existing application, not a new project. Before changing code, read
`docs/HANDOFF.md`, `docs/tasks.json`, and the relevant parts of
`docs/01_DEVELOPMENT_SPEC.md` and `docs/02_AI_TASKS.md`.

- T01–T08 and T33 are implemented. Verify the existing code and evidence; do not
  repeat initialization or replace this directory with an empty clone.
- The next recommended milestone is T14. Respect the task dependency
  graph, particularly T16 before T15 and T35/T36 before T21. A handoff document
  is context; it does not itself authorize starting work or contacting another agent.
- Use the existing Python 3.12 environment and modular Streamlit application.
  Keep fixture and live data separate. UI reruns must not trigger external calls.
- The agreed architecture is a local web app, ChatGPT OAuth plan-usage generation,
  local BGE embeddings, SQLite metadata and planned Chroma/Tavily adapters.
  Actual provider/OAuth availability is not yet verified. When implementing those
  adapters, verify current primary documentation and run the defined contract tests.
- Do not use cookies, private ChatGPT endpoints, a shared token, or a hidden API-key
  fallback. Keep credentials outside Git, research SQLite, browser state and logs.
- Do not automatically approve real sources or fabricate human gold answers,
  scores, live-call results, quota data or task evidence.
- Preserve the review/hash/eligibility and citation checks in the specification.
  A provider failure is not a research knowledge gap. Never publish an incomplete
  stream or use fixture output as a live answer.
- Tests default to blocked IP networking and temporary storage. Unix sockets are
  permitted for Streamlit's local event loop. Do not weaken these defaults to pass
  tests. Real service and cached-model checks require their explicit test groups.
- `sources/` in the parent Seen Ventures workspace is synced reference material;
  never edit, rename, move or delete it. Work in this application directory.
- After each completed feature/task, automatically update `docs/tasks.json`, the
  matching card in `docs/02_AI_TASKS.md`, `docs/progress.md`, and `docs/HANDOFF.md`
  before reporting completion or moving to the next feature. This is a standing
  user instruction; do not wait for another documentation-sync request. Record
  changed files, actual checks/results, not-run checks, limits and the next task.
  If work is incomplete or a check fails, record its actual status and reason;
  never mark it done simply because code was written. Update the specification
  and README when interfaces, behavior or setup change. Keep the output document
  mirror and existing handoff archives in sync when they remain available in
  this workspace, excluding environments, runtime data and real credentials.
- The current implementation is committed and published to `origin/master` in the
  existing user-specified repository. No remote reset, new repository creation or
  deployment is part of a documentation handoff.
  Check actual Git state before any future Git operation; preserve user changes.

Default checks from this directory:

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m pip check
```

Run checks appropriate to the change. Record not-run live/human checks explicitly;
passing offline tests does not mean the product has passed research acceptance.

