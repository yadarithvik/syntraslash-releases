# Desktop application development

## Source and dependencies

The app targets Windows 10/11 x64. The earlier v1.1.0 release build used Python 3.14.6 and PyInstaller 6.22.3. Dependency versions in `desktop-app/requirements.txt` are intentionally unpinned; this is not a fully locked reproducible build.

From the repository root:

```powershell
cd desktop-app
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Microsoft Edge WebView2 must be available. The source uses Windows APIs for desktop control and UI Automation.

## Inference runtime

The application expects external inference runtime files beside `app.py`, or beside the packaged `Syntra.exe`:

```text
engine/vulkan/llama-server.exe
engine/cpu/llama-server.exe
```

Keep each runtime's required DLLs beside its executable and preserve the accompanying licenses. Runtime binaries and model weights are not stored in this Git repository. Use the matching runtime from the existing release installation for local development. Installing Python dependencies alone does not supply these runtimes.

`app.py` opens the model setup screen and downloads or imports the pinned model through `model_install.py`. `bundled_engine.py` tries Vulkan before CPU, binds the engine to loopback, and starts the application API on loopback. The configured working context is 16,384 tokens.

```powershell
.\.venv\Scripts\python.exe app.py
```

## Tests

The model installation unit tests use small synthetic data and mocked network responses. They do not download the large model or control the desktop:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_model_install.py -v
```

Other acceptance and live-model scripts can open applications, execute tasks, or require a running model. Read their setup before running them. Historical generated test reports and personal test data are excluded.

## Package the app

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm syntra-online.spec
```

This produces `dist/Syntra Slash`. The PyInstaller spec collects the application, not the separately staged model/runtime distribution. Before building an installer, assemble a staging directory containing the generated app, `engine/` runtime folders with their DLLs, and third-party `licenses/`.

The NSIS script `packaging/syntra-installer.nsi` expects these compile-time definitions:

| Definition | Meaning |
| --- | --- |
| `STAGE` | Complete runtime staging folder |
| `OUTFILE` | Destination installer path |
| `APPICON` | Path to the application `.ico` |
| `REMOVEFILES` | Generated NSIS include with exact file cleanup entries for that stage |

Create and review the stage-specific uninstall include before invoking NSIS. This repository does not contain a one-command installer reproduction script or bundled runtime binaries. The alternate `syntra-slashes.spec` is retained as part of the source snapshot; `syntra-online.spec` was used for the v1.1.0 release.

## Website

The independent website lives in `../website`. It has no npm dependencies or build step. `website/app.js` contains the published Windows release URL. Keep that URL and the website download link aligned when preparing future releases.
