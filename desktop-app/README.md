# Syntra Slash

Created by **Rithvikyada**.

**[Official website and Windows download](https://syntraslash.pages.dev/#get-syntra)**

[Detailed GitHub overview](https://github.com/yadarithvik/syntraslash-releases) · [Windows v1.1.0 release](https://github.com/yadarithvik/syntraslash-releases/releases/tag/v1.1.0)

## This folder

The root contains the Windows app source associated with the v1.1.0 release. `website/` contains the six files extracted from the final Cloudflare deployment archive from the earlier Syntra work chat. The web download link remains unchanged.

| Path | Purpose |
| --- | --- |
| `app.py` | Native Windows window and first-run setup |
| `model_install.py` | Resumable model download, import, and checksum verification |
| `bundled_engine.py` | Local inference engine process |
| `engine.py` | Local application API |
| `model_bridge.py` | Model integration and conversation protocol |
| `session_manager.py`, `session_store.py` | Task lifecycle and persistent SQLite sessions |
| `desktop_agent.py`, `perception.py`, `tools_registry.py` | Windows interaction and workspace tools |
| `index.html`, `model-setup.html`, `assets/` | Application UI and branding |
| `website/` | Cloudflare landing page HTML, CSS, JavaScript, and images |
| `packaging/`, `syntra-online.spec` | Windows build sources |
| `requirements.txt` | Python development dependencies |
| `tests/` | Existing automated checks |
| `licenses/` | Third-party notices from the release stage |
| `docs/` | Release-source provenance, manifest, and repository development guide |

## Install the packaged app

1. Open [syntraslash.pages.dev](https://syntraslash.pages.dev/#get-syntra).
2. Download and run `Syntra-Slash-Setup.exe` (about 80 MB).
3. Open Syntra Slash and download the 8.99 GB model inside the app, or import a matching existing model.
4. Wait for verification, then choose **Open Syntra**.

Windows 10/11 x64 and Microsoft Edge WebView2 are required. Keep at least 10 GB free for the model. 24 GB RAM and a modern GPU are recommended.

## Preview the website

Run from this folder:

```powershell
python -m http.server 8000 --directory website --bind 127.0.0.1
```

Open `http://127.0.0.1:8000`. Upload the contents of `website/` for a manual Cloudflare Pages deployment.

## Develop the app

Install the dependencies from `requirements.txt` in a virtual environment. `app.py` also needs the matching inference runtime at `engine/vulkan/llama-server.exe` and/or `engine/cpu/llama-server.exe`, including required DLLs. These external binaries are available in the packaged app; they are not included in the GitHub source snapshot. Use the installer for a complete runtime.

The [repository development guide](https://github.com/yadarithvik/syntraslash-releases/blob/main/docs/DEVELOPMENT.md) includes build details. Its `desktop-app` directory corresponds to this folder's root.

Run the self-contained model installation tests from this folder:

```powershell
python -m unittest discover -s tests -p test_model_install.py -v
```

Personal models, conversation files, databases, and existing build output were preserved during this source sync. The 16,384-token model configuration, app behavior, and public installer were not changed.


## Layered local memory build

This folder now includes the integrated disk-backed memory implementation. See [MEMORY_IMPLEMENTATION.md](MEMORY_IMPLEMENTATION.md) for behavior, verification, and limits.
