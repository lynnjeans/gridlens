# Known limitations and open items (2026-10-12)

## Not verified yet (needs the user)

| Item | Status | How to verify |
| --- | --- | --- |
| Real ChatGPT sign-in (T34) | awaiting_input | `APP_MODE=live python -m gridlens.cli login`; record whether plan usage was granted. |
| Session refresh and sign-out (T35) | awaiting_input | After sign-in: `APP_MODE=live GRIDLENS_LIVE_SESSION=1 python -m pytest -m live -k live_sessions -s`. |
| Real model catalog and selection (T36) | awaiting_input | Live sidebar: load models and choose one. |
| Real answer and output mode (T21) | awaiting_input | `APP_MODE=live GRIDLENS_LIVE_ANSWER=1 python -m pytest -m live -k live_answer -s` (uses plan usage). Records whether strict JSON schema or prompt-JSON mode was used. |
| Real Tavily search (T06) | not run | Set `TAVILY_API_KEY`; `python -m pytest -m live -k tavily -s`. |
| Real SerpApi search (T37) | not run | Set `SEARCH_PROVIDER=serpapi` and `SERPAPI_API_KEY`; `python -m pytest -m live -k serpapi -s` (one search). |
| Real corpus, gold and human evaluation (T31) | awaiting_input | See `docs/HANDOFF.md` §5 runbook. |
| Human UI checks (T14, T19, T23, T25, T27, T30) | not run | One person walks the main flow; an AI browser walkthrough of fixture mode is recorded in `artifacts/test-results/`. |

MVP acceptance cannot be claimed until T31 passes the PRD thresholds with human scores.

## Product limits

- English-first retrieval with `BAAI/bge-small-en-v1.5`; Chinese text is stored, chunked
  and cited correctly, but Chinese retrieval quality is not an acceptance target.
- No OCR: scanned PDFs are rejected. Tables in HTML are not reconstructed (flagged).
- No reranker or hybrid search; retrieval is vector Top-10 within approved versions.
- Citation checks prove the quote is verbatim text of an approved chunk; they do not prove
  the source supports the claim. That needs human review.
- ChatGPT plan usage depends on account eligibility and limits; remaining quota is never
  estimated. OpenAI's 2026-10-12 docs do not document `text.format` or usage fields for
  this route, so structured output is probed on the real model.
- Single local operator; no hosting, multi-user access or Windows support. Credential
  storage relies on POSIX permissions and `fcntl` locks.
- Refresh is manual; there is no change monitoring or visual diff.
- The Streamlit sign-in waits up to 5 minutes inside the page while you approve in the
  browser.

## Engineering notes

- Fixture mode keeps a persistent Chroma index in `data/fixture/chroma`; deleting
  `data/fixture/` resets fixture state.
- Runs left by versions before T28 have no lock file and are treated as interrupted by
  `recover`.
- Chunks indexed before migration 002 lack segment provenance and are skipped by retrieval
  until that version is indexed again (reopen and re-approve it, or approve a new version);
  re-indexing a Ready version is a no-op.
- `requirements.lock` is resolved for macOS/Python 3.12; other platforms need a new lock.

## Suggested next steps

1. Complete T34 → T36 → T21 live checks with the owner's account.
2. Build the real corpus (≥10 approved sources over ≥3 types) and fill `evals/gold.json`.
3. Run `evaluate --mode live`, have a teammate score `reviews.json`, run
   `evaluate-score`, and record results (including failures) in `docs/progress.md`.
4. Only then update the delivery status (T32) and demo with real results.
