# Syntra 1.3.0 — skills, plugins and MCP

Prepared for release on **8 November 2026, 9:00 AM IST**. Do not replace the public v1.2.0 download before that time.

## Included by default

Five local reader skills: PDF embedded text with page references, image OCR and metadata, DOCX text, text/code, and CSV/JSON. The seven Syntra-adapted guides are syntra-customizations, automation, generative-ui, migrate-workflows, plugin, run-workflow and reverse-engineer-anything. All twelve are enabled on a fresh installation.

The adaptations use real Syntra tools and remove source-product branding/runtime instructions. Generative UI produces local HTML artifacts; staged workflows run through the local agent loop rather than another application's parallel-agent API. The local automation tools create persistent one-shot tasks, which need Syntra open; pending missed tasks run on the next launch. Original source skills are not edited.

The Skills, plugins & MCP panel can discover locally installed Codex, Antigravity and workspace skill folders, import individually or all found, enable/disable instructions, import local plugin bundles, and configure/connect local stdio MCP servers. Imported instructions start disabled. Their external tools, logins and credentials do not transfer.

## REA MCP

The installer includes **rea-agents 6.8.0** and a **private Node 24.22.1 runtime**. It does not modify other clients' MCP registration. REA advertises 229 tools; the model discovers the selected input schema before calling a tool. Some target types need separate native engines such as Ghidra or Hopper; these are not silently installed. REA and its dependencies retain their upstream licenses and identity.

MCP gateway outputs are bounded for the model, with full readable JSON responses retained under extensions/mcp-evidence. Input-schema discovery omits large output schemas. Timed-out/cancelled requests stop the owned transport and are not repeated silently.

## Reader boundaries

Images use local Windows OCR and require a Windows OCR language. This does not add full visual reasoning to the text model. Scanned PDF OCR is not included; PDF text extraction reports when pages have no embedded text. Reader inputs are capped at 16 MB and model-facing excerpts are bounded. Uploaded attachments are extracted locally using temporary files.

## Data and packaging

Installed profiles store managed imports, MCP server choices and one-shot schedules under `%LOCALAPPDATA%/SyntraSlashes/extensions`. Personal models/chats are preserved on update. Source runs may override SYNTRA_BASE_DIR for isolated testing.

The Python app is rebuilt with PyInstaller; pypdf is included. The release folder also contains the existing inference engine/Python runtime and the private mcp directory. A source ZIP excludes these generated third-party runtime trees and personal data; recreate the REA runtime using the pinned package-lock and build notes.

## Verification changes

The integration tests found and fixed two issues: oversized MCP output schemas crowding the working buffer, and a model batching completion before it had observed other tools' results. Completion is now deferred to a later model response when mixed with other tools. A Windows SQLite retrieval cleanup race on early budget errors was also corrected. No perfect-recall, unlimited-context or universal model-accuracy claim is made.
