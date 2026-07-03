# Bundled Ollama engine

Obrenna ships the Ollama inference engine inside the installer so a fresh
machine needs zero manual setup. The Rust supervisor auto-starts it on launch
(`src-tauri/src/ollama.rs`) and the setup wizard's model download runs against
it.

## What goes here

Drop the contents of the official Ollama **standalone** archive for the target
platform into this directory, so that `ollama.exe` (Windows) / `ollama`
(macOS/Linux) sits at:

```
src-tauri/resources/ollama/ollama.exe      <- Windows
src-tauri/resources/ollama/ollama          <- macOS / Linux
src-tauri/resources/ollama/lib/...          <- accompanying runners / libs
```

Get the archive from https://github.com/ollama/ollama/releases (e.g.
`ollama-windows-amd64.zip`). Use the **zip/tgz**, not `OllamaSetup.exe`.

The binaries are intentionally **git-ignored** (they are large and are fetched
at packaging time) — only this README is tracked. In dev, once you extract a
copy here, `tauri dev` will resolve and launch it automatically.

## Updating the engine

Because Obrenna curates every model it pulls, engine bumps are deliberate:
replace the extracted binaries here with a newer release, re-test the curated
models, and cut a new Obrenna installer. There is no runtime auto-update of the
engine.

## Bundling

`tauri.conf.json` bundles `resources/ollama/**/*` into the installer. The app
resolves it at `<resource_dir>/ollama/ollama[.exe]` at runtime, mirroring how
the MCP server binary under `resources/mcp/` is handled.
