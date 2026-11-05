# Syntra 1.3.0 — scheduled release

Scheduled for **8 November 2026, 9:00 AM IST**. The public download stays on v1.2.0 until then.

The new build adds twelve enabled built-in skills, local skill discovery/import from Codex and Antigravity, local plugin bundles, an MCP manager, REA 6.8.0 with its private Node runtime, local one-shot automation, PDF/DOCX/CSV/JSON readers, and image OCR/metadata. The seven source skills were adapted to Syntra tools and do not depend on source-product runtime APIs.

Imported skill instructions start disabled; external services and credentials are not transferred. Image reading is OCR and metadata rather than full visual understanding. Scanned-PDF OCR is not included. Local schedules need Syntra open, and deep REA analysis may need additional native engines.

The agent must observe tool results before completing a task. Complete MCP evidence is saved locally, and schema discovery includes the full input contract without oversized output schemas.
