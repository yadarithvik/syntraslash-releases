# Syntra 1.2.0 verification

Verified on 5 November 2026.

| Check | Result |
|---|---|
| Layered memory | 15/15 |
| Full rendered prompt envelope | 4/4 |
| Desktop execution regressions, without desktop input | 7/7 |
| Model download/import unit checks | 13/13 |
| Existing component acceptance checks | 15/15 |
| Browser UI lifecycle/layout checks with sample activity | 10/10 |
| Compiled backend serves exact updated frontend assets | 3/3 |
| Repeated offline packaged memory diagnostics | 6/6 |

The original 54-check rebuild was also exercised with the actual local 14B model. A source fixture stored 456,614 historical characters and returned the correct older HELIOTROPE filename. A compiled-app fixture recalled the correct ORCHID filename from before 80 unrelated messages, called `recall_memory` and `complete_task`, and created its dossier. The source-labelled retrieval selection was corrected before those final passing checks.

The native Windows first-run window opened using an isolated profile, without starting another model download. The installer PE header and source ZIP integrity were validated. The finished installer was not installed over a personal installation during verification.

The UI-only follow-up replaced external HTML/CSS/JS assets in the compiled runtime. Python logic was unchanged, and the packaged backend served the exact updated assets. Model benchmarks were not repeated for the visual changes. The website walkthrough uses illustrative actions and does not execute desktop tools.

Current recall is keyword-based FTS5 and consolidation is extractive. Original history is retained. These checks do not establish perfect recall, unlimited active context, a fixed total-memory footprint, or universal response-time/OOM guarantees.
