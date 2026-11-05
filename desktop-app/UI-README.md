# Syntra Slash interface

See [README.md](README.md) for current setup and source information.

- `model-setup.html` provides download, pause/resume, model import, and verification controls.
- `index.html`, `assets/app.css`, and `assets/app.js` provide the native application's workspace interface.
- `website/` contains the separate public Cloudflare landing page and illustrative UI preview.
- The packaged app uses WebView2 and a local inference process; it does not need a separately installed Ollama app.
- Packaged session data is stored under `%LOCALAPPDATA%/SyntraSlashes`; source-run session data defaults to `memory/` unless `SYNTRA_BASE_DIR` is set.
- Local context is bounded; Markdown export is not a semantic summarizer.

[Official website and download](https://syntraslash.pages.dev/#get-syntra)
