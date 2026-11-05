# Syntra Slash 1.3.0 — skills, plugins and MCP

Scheduled release: **8 November 2026, 9:00 AM IST**.

## Included

- Twelve enabled built-in skills: five readers and seven Syntra-adapted workflow guides.
- PDF embedded-text extraction, Windows image OCR and metadata, DOCX text, text/code, and CSV/JSON reading. PDF/image attachments are extracted locally.
- Local skill discovery from Codex, Antigravity and the selected workspace, individual/import-all controls, and explicit enablement for imported instructions.
- Local plugin skill bundles and a stdio MCP manager.
- Bundled **REA 6.8.0**, a private **Node 24.22.1 runtime**, and discovery of **229 MCP tools**.
- Persistent one-shot local task scheduling, cancellation and listing.
- Completion is deferred when mixed with tools whose results the model has not observed. Oversized MCP responses are retained in full locally while the model receives a bounded view.

The seven adapted skills are Syntra customizations, automation, generative UI, migrate workflows, plugin, run workflow and Reverse Engineer Anything. They use real Syntra tools; the original source skills and other apps' configurations are not edited.

## Scope

Image reading is OCR/metadata, not full visual reasoning; Windows needs an OCR language. Scanned PDF OCR is not included. Imported instructions do not transfer external services, credentials or model capabilities. Local scheduled tasks require Syntra open; pending missed tasks run at the next launch. REA tools requiring native analysis engines need those engines separately.

The installer includes the local inference engine, Python, built-in skills and REA/Node. The 8.99 GB model remains a separate in-app download or import. Original local conversations and model files are preserved on update.

## Verification

81 automated checks passed, plus source and compiled-runtime integration with the real local 14B model. The agent loads skill guidance, extracts the correct PDF/image values, discovers a REA input schema, and invokes REA. The source and packaged evidence accompany the build handoff. Third-party components retain their original licenses.

Created by **Rithvikyada**. Website: https://syntraslash.pages.dev/
