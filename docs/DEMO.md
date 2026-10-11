# GridLens demo script (6–8 minutes)

Prepared 2026-10-12 against commit `master` at T32. Real results come from T31; until
T31 is completed this script can only be rehearsed in **fixture mode**, and the presenter
must say so. Do not present fixture answers as research findings.

## Before the demo

- [ ] `python -m gridlens.cli doctor` shows the expected mode, `local_model.prepared:
      true` (live) and `schema_current: true`.
- [ ] Live only: sidebar shows the signed-in account, plan usage granted and a model
      selected; `python -m pytest -m local_model -q` passed today.
- [ ] Live only: at least one approved, indexed source (Knowledge Base shows
      "Searchable"), prepared during T31 — never approved during the demo just to fill
      the screen.
- [ ] Note the commit, mode, model slug and date on the first slide or recording.

## Script

| Time | Step | What to show and say |
| --- | --- | --- |
| 0:00–0:40 | Problem and boundary | Local tool; answers only from sources a person approved; no grid calculations; fixture vs live. |
| 0:40–1:40 | Discover | Search a topic (live: Tavily; fixture: synthetic). Point out publisher/date unknown labels and that nothing is fetched yet. Select a candidate. |
| 1:40–3:00 | Review | Capture → read the text with section/page locations and extraction limits; correct region/type; Approve. Mention the approval is tied to the hash you read; indexing starts and reports chunks. |
| 3:00–3:30 | Knowledge Base | Review/ingestion/version shown separately; "Searchable" only after a verified index; Retry/Revoke/Refresh. |
| 3:30–5:00 | Ask | Ask R01 or R02 (live) or the synthetic question (fixture). Show answered/partly answered status, Fact vs Inference, open citation [1]: verbatim quote, page or section › paragraph, original link. |
| 5:00–5:40 | Insufficient evidence | Ask R09 or R10: the answer says what is missing instead of inventing numbers or dates. |
| 5:40–6:20 | Gaps | Open the gap; show scope and suggested searches; "Use in Discover" fills the search box without searching. |
| 6:20–7:00 | Revocation | Revoke the cited source in Knowledge Base; reopen the old answer — its citation is marked historical; asking again no longer uses it. |
| 7:00–7:40 | Export and results | Prepare and download the Markdown research log; show the T31 metrics with numerators and denominators, including failures. |

## Notes for the presenter

- Say whether scores were self-assessed (PRD §15.3).
- If the ChatGPT plan limit is reached, show the usage link; it is not a knowledge gap.
- Recordings must be labelled with date, commit and mode.
