# Source provenance

Prepared on 5 November 2026 from the earlier Syntra work chat, **Create Syntra app graphics and UI**.

- `website/` is an exact extraction of the final `syntraslash-setup-renamed.zip` deployment archive. All six files matched the saved deployable website folder byte for byte. Their SHA-256 values are recorded in `SOURCE-MANIFEST.json`.
- The earlier release notes identify the app source folder and `syntra-online.spec` used for v1.1.0. The Python modules and packaging source here come from that identified source folder. No source has been reconstructed from the executable.
- Application HTML, frontend assets, guardrails, and third-party license texts were copied from the final release staging folder. Checked HTML/CSS/JS/guardrail files matched the identified source folder.
- The new README, development guide, dependency list, and ignore rules document this source snapshot. They do not change the existing public installer.
- This archive was verified against the saved final deployment; a live HTTP byte comparison was unavailable because the public host returned HTTP 403 to the command-line fetch.

The repository does not contain model weights, inference executables, local conversation data, historical test-output files, or deployment credentials. Existing GitHub Releases and the Cloudflare production site are retained.
