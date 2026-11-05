# Syntra Slash

**Local AI for building, exploring, and getting things done on Windows.**

Created by **Rithvikyada**.

## Download Syntra

**[Visit the official website and download Syntra Slash](https://syntraslash.pages.dev/#get-syntra)**

- [Official website](https://syntraslash.pages.dev/)
- [Windows installer — Syntra-Slash-Setup.exe](https://github.com/yadarithvik/syntraslash-releases/releases/download/v1.2.0/Syntra-Slash-Setup.exe)
- [Release notes and checksums](https://github.com/yadarithvik/syntraslash-releases/releases/tag/v1.2.0)

This repository contains the website deployed to Cloudflare Pages, the Windows app source, and developer documentation. The existing Windows download remains available through GitHub Releases.

## What Syntra does

Syntra Slash provides a Windows desktop workspace around the Syntra Max Aperion local model configuration. The app includes a native WebView2 window, a local Python service, session storage, a model setup screen, and desktop/workspace tools.

- **Local inference:** the app starts its own inference process on your machine.
- **Two working modes:** Background tools work with commands and workspace files; Transparent tools interact with Windows applications.
- **Persistent sessions:** return to conversations, search and rename sessions, and export Markdown.
- **Text and code attachments:** include bounded file excerpts in a conversation.
- **Local strings:** persistent conversation layers with session-scoped keyword recall and source references.
- **Markdown dossiers:** completed tasks save bounded, extractive records while keeping original history.
- **Task activity:** compact, collapsible work summaries with expandable command output, file changes, and live/failure/interruption states.
- **Strings indicator:** see which stored strings the latest automatic recall used.
- **Stop controls:** interrupt work with Stop or Escape.
- **Model setup:** download with pause/resume and checksum verification, or import a matching existing model.

The website contains an illustrative interactive preview. AI inference and desktop actions run in the Windows app.

## Install on Windows

1. Open [the official download page](https://syntraslash.pages.dev/#get-syntra).
2. Download and run **Syntra-Slash-Setup.exe** (about 80 MB).
3. Launch Syntra Slash and choose **Download & install model**. The model download is approximately **8.99 GB**.
4. Wait for checksum verification, then choose **Open Syntra**.

Downloads can be paused and resumed. Existing users can import the matching `syntra-max-aperion.gguf` file. Initial model loading can take a few minutes.

### System requirements

| Component | Requirement |
| --- | --- |
| Operating system | Windows 10 or 11, x64 |
| Desktop renderer | Microsoft Edge WebView2 |
| Model storage | At least 10 GB free; additional space for the application and your work |
| Memory | 24 GB RAM recommended |
| GPU | A modern GPU recommended; the included engine tries Vulkan, then CPU |
| Internet | Required for initial download and network tasks |

After setup, local model tasks can run offline. Browsing and other network tasks need an internet connection.

## Repository layout

```text
README.md                 Project overview and official download links
website/                  Cloudflare website files
  index.html              Landing page and installation details
  style.css               Layout, colors, animation, and responsive styles
  app.js                  Interactive preview, motion, and download button
  assets/                 Syntra branding and favicon
desktop-app/              Windows application source
  app.py                  Native window and first-run model setup
  model_install.py        Resumable download, model import, and verification
  bundled_engine.py       Private local inference process and backend fallback
  engine.py               Local application HTTP API
  model_bridge.py         Model protocol and conversation integration
  session_manager.py      Task execution and session lifecycle
  session_store.py        SQLite session persistence
  desktop_agent.py        Windows desktop interaction
  perception.py           Windows accessibility inspection
  tools_registry.py       Workspace and desktop tools
  assets/                 Application frontend and branding
  tests/                  Existing automated checks
  packaging/              Windows installer source
  licenses/               Bundled third-party license texts
docs/                     Source provenance and development notes
```

## Preview the website locally

From the repository root, run:

```sh
python -m http.server 8000 --directory website --bind 127.0.0.1
```

Open `http://127.0.0.1:8000`. No frontend build step is required. The download button continues to use the current v1.2.0 installer URL.

For a manual Cloudflare Pages upload, use the **contents of `website/`** as the upload root so `index.html` is at the root. The published address remains [syntraslash.pages.dev](https://syntraslash.pages.dev/).

## Run or build the desktop source

See [desktop application development](docs/DEVELOPMENT.md) for dependencies, external inference runtime requirements, tests, and packaging steps.

The source repository excludes model weights, engine executables, generated installers, personal conversations, runtime databases, and build caches. Use the official installer for the complete packaged runtime.

## Data and execution

Packaged builds store model and conversation data under `%LOCALAPPDATA%/SyntraSlashes`. Source runs store conversation data under `desktop-app/memory` unless `SYNTRA_BASE_DIR` is set. Model installation uses the LocalAppData model directory by default.

Background commands and desktop tools act with the Windows user's permissions. Direct workspace file checks are not an operating-system sandbox. Review the selected workspace and task activity before running automation.

## Credits and third-party components

Syntra Slash branding and application work are by **Rithvikyada**. Third-party model weights, the inference runtime, Python, and frontend libraries retain their own licenses and notices. Bundled license texts are kept in [desktop-app/licenses](desktop-app/licenses), and frontend vendor notices remain in their original files.

See [source provenance](docs/SOURCE-PROVENANCE.md) for the relationship between these files and the earlier release/deployment.


## Syntra 1.2.0

See [release notes](docs/RELEASE-v1.2.0.md), [verification](docs/VERIFICATION-v1.2.0.md), and [implemented memory behavior](desktop-app/MEMORY_IMPLEMENTATION.md). Recall currently uses FTS5 keyword search, and dossiers select source facts. Model input remains bounded; stored history and active context are separate.
