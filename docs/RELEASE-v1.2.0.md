# Syntra Slash 1.2.0 — local strings and clearer task activity

Syntra now stores older conversation and task results as persistent, session-specific strings on your PC. It retrieves relevant source passages when needed and saves a compact Markdown dossier after completed tasks, keeping original history available.

## New in this release

- SQLite WAL strings storage and FTS5 keyword recall, including a native `recall_memory` tool.
- Source-referenced extractive Markdown dossiers after completed tasks.
- Compact, collapsible work summaries with action icons, file changes, expandable output, and live/error/interruption states.
- A local strings indicator showing IDs from the latest automatic recall.
- Restyled Stop all control, removal of Quick guide, and fixes for duplicate completed-answer replay.
- Real tokenizer/template validation of the complete model input, with bounded recent/recalled evidence and room for output.

## Install

Download and run **Syntra-Slash-Setup.exe** (about 80 MB). Open Syntra Slash, then download the **8.99 GB** model or import the matching existing GGUF. Model downloads support pause/resume and checksum verification. Windows 10/11 x64, Edge WebView2, at least 10 GB free model storage, and 24 GB RAM recommended.

The installer includes the local inference engine and Python; model weights are separate. Local inference can run offline after setup. Browsing and network tasks still need internet.

## Recall behavior

Recall matches keywords, so it can miss paraphrases. Dossiers select facts from sources; they are not a complete semantic summary. Original conversation history is retained. The model's active context remains bounded even as locally stored history grows.

## Validation

54 automated rebuild checks passed, plus source-level and compiled-app recall tests using the actual local 14B model. The UI update passed 10 browser lifecycle/layout checks, 3 packaged asset checks, and 6 repeated offline packaged memory diagnostics. The native model-setup window opened successfully. The complete installer was not installed over an existing personal installation during testing.

Creator: **Rithvikyada**. Official website: https://syntraslash.pages.dev/
