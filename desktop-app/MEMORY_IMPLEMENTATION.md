# Syntra Slash layered memory — implementation status

Local verification build: **1.2.0-memory-preview**, 5 November 2026.

## Implemented

- `memory_engine.py` persists conversation segments and tool observations to SQLite WAL under the existing application data directory.
- FTS5 indexes layer digests and source text. Retrieval runs on a separate CPU worker and returns exact, source-labelled excerpts for the current session.
- The agent loop imports older saved messages incrementally, keeps a bounded recent conversation, and recalls relevant older facts before inference.
- Recent conversation is bounded to 2,048 tokens; recalled excerpts are separately bounded to 2,048 tokens. Instructions, tool definitions, chat framing, and output are included in the 16,384-token total model budget using the running model's tokenizer and rendered chat template.
- `recall_memory` is available as a native tool when more specific searches are needed.
- Tool call/result groups remain together while active. Oversized groups are archived and replaced with bounded observations; original contents remain searchable.
- Completed tasks automatically create a local dossier. `/compact` also generates a dossier for an idle session.
- Dossiers select and deduplicate factual source lines into decisions, artifact references, reported outcomes, and follow-up sections. They are written atomically and capped at 10 MB.
- Memory preparation and dossier creation are shown in the activity feed, with token counts and source layer references.
- Cross-session memory searches are isolated. Deleting a session clears its memory index and associated dossier.

## Deliberate limits

Retrieval is keyword-based FTS5, not an embedding model or a second 14B model running in parallel. It can miss paraphrases. Dossiers use extractive consolidation, not a model-generated semantic summary. Original layers and chat history are retained for exact recall; this build does not permanently purge raw history after summarization.

The 16k model context remains finite. Long conversation storage is separate from active inference context. No fixed 1.5 GB total-memory footprint, zero-OOM guarantee, unlimited context, lossless summarization, or constant response-time guarantee is claimed.

For a single request that cannot fit the recent-conversation budget, the app returns a clear error and preserves the original locally. It does not silently execute an incomplete oversized request.

## Verification

The verification report distributed with this build records automated checks, a real 14B recall task against an archive larger than the active context, and checks executed through the compiled Windows runtime.

Developer diagnostics:

```powershell
Syntra.exe --verify-memory "C:\path\to\packaged-memory.json"
```

This runs isolated local memory checks and writes a JSON report. `--diagnostic-api PORT` starts the existing loopback-only application backend for integration testing; it requires a configured local inference endpoint through `SYNTRA_MODEL_URL`.

The official website remains https://syntraslash.pages.dev/#get-syntra. This local build does not replace the public v1.1.0 release automatically.
