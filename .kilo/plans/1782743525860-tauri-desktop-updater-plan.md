# Tauri Desktop Installer and Auto-Update Plan

## Goal
Package GrebGlob as a downloadable desktop app with a polished installer/first-run flow and secure auto-updates.

## Decisions
- Desktop shell: Tauri.
- Release hosting: GitHub Releases.
- Backend packaging: PyInstaller executable spawned by Tauri.
- PDF browser dependency: bundle Playwright Chromium so PDF export works offline after install.
- Platform scope: all Tauri desktop platforms: Windows, macOS, Linux.
- Update mechanism: Tauri-native updater only; frontend calls Tauri commands. Do not add a FastAPI update endpoint for app installation.
- Existing setup flow: reuse and extend `frontend/src/setup/SetupFlow.tsx`; do not create a duplicate installer wizard.

## Current Repo Context
- Frontend is React + Vite + TypeScript in `frontend/`.
- Backend is FastAPI in `backend/`, entrypoint `backend/main.py`.
- App setup already exists in `frontend/src/setup/*` and is gated by `AppSettings.setup_complete` in `frontend/src/App.tsx`.
- Backend data defaults to `backend/data` via `GREBGLOB_DATA_DIR`; desktop build must override this to an OS app-data directory.
- Vite dev proxy sends `/api` and `/health` to `http://localhost:8000`.
- Backend dependencies include `fastapi`, `uvicorn`, `pandas`, `sqlalchemy`, `httpx`, `playwright`, `psutil`.

## Target Architecture
- Tauri app owns native window, menus, updater, app paths, and process lifecycle.
- On startup, Tauri chooses an available localhost port and starts the packaged PyInstaller backend executable.
- Tauri passes environment variables to the backend:
  - `GREBGLOB_DATA_DIR=<platform app data dir>/data`
  - `GREBGLOB_PORT=<chosen port>` if the backend wrapper uses it
  - optional `GREBGLOB_DESKTOP=1`
- Frontend talks to the backend through a dynamic base URL exposed by Tauri, not a hardcoded production port.
- Existing React setup flow remains the user-facing first-run installer experience.
- Tauri updater checks GitHub Release metadata/manifests, verifies signatures, downloads, and installs updates.

## Implementation Tasks

### 1. Add Tauri Workspace
1. Add Tauri dependencies to `frontend/package.json`:
   - `@tauri-apps/api`
   - `@tauri-apps/cli` as dev dependency
2. Initialize `src-tauri/` at repo root or under `frontend/` consistently with Tauri CLI expectations.
3. Configure Tauri to use:
   - dev URL: `http://localhost:5173`
   - beforeDevCommand: start or expect Vite dev server
   - beforeBuildCommand: `npm --prefix frontend run build`
   - frontendDist: `../frontend/dist` or correct relative path
4. Add app metadata:
   - product name: `GrebGlob`
   - identifier: choose a stable reverse-domain identifier, for example `com.grebglob.app`
   - version: sync with root/frontend package versions.

### 2. Backend Desktop Entrypoint and PyInstaller Bundle
1. Add a backend desktop launcher script, for example `backend/desktop_server.py`, that imports `main:app` and runs uvicorn.
2. The launcher should read:
   - host default `127.0.0.1`
   - port from `GREBGLOB_PORT`
   - data directory from `GREBGLOB_DATA_DIR`
3. Ensure `GREBGLOB_DATA_DIR` is set before importing modules that initialize `app.config`/`app.db`.
4. Add PyInstaller configuration/spec for backend packaging.
5. Include required data files:
   - `backend/app/services/hardware_catalog.json`
   - any templates/static files used by PDF export
   - Playwright browser binaries
6. Include hidden imports as needed for FastAPI, uvicorn, SQLAlchemy, pandas, Playwright, and app routers/services.
7. Build a backend executable per target platform.
8. Ensure Tauri resources include the packaged backend executable and Playwright payload.

### 3. Tauri Backend Process Lifecycle
1. Implement Rust startup logic that:
   - finds a free localhost port
   - resolves app data directory using Tauri path APIs
   - creates required app directories
   - starts the backend executable as a child process
   - passes required env vars
   - polls `/health` until ready or timeout
2. Expose a Tauri command to frontend for retrieving API base URL, for example `get_api_base_url`.
3. Kill the child backend process cleanly on app exit.
4. Handle startup failure with a user-friendly error screen/log path.
5. Avoid exposing backend on external interfaces; bind to `127.0.0.1` only.

### 4. Frontend API Base URL Integration
1. Update `frontend/src/lib/api.ts` so production desktop builds can use a runtime API base URL from Tauri.
2. Preserve browser dev behavior:
   - `VITE_API_BASE_URL` if set
   - otherwise same-origin/proxy behavior for existing dev flow
3. Add a small initialization path in `App.tsx` or a frontend runtime config module to load the Tauri API base URL before calling `getAppSettings()`.
4. Ensure all fetch helpers use the same resolved base URL.

### 5. Extend Existing Setup Flow for Desktop
1. Reuse `frontend/src/setup/SetupFlow.tsx` as the custom installer/first-run flow.
2. Add desktop-only setup affordances behind Tauri detection:
   - display selected app data directory
   - optional button to open data folder
   - Ollama/local endpoint auto-detection status
   - clearer managed-vs-BYO language for installed desktop users
3. Do not create a second NSIS-style wizard.
4. Persist setup through existing `/api/settings/app` endpoint.
5. Confirm setup completion survives app restart using the platform app-data SQLite DB.

### 6. Tauri Updater
1. Add and configure `tauri-plugin-updater`.
2. Generate and store the updater signing key securely; never commit the private key.
3. Configure updater endpoints to GitHub Releases hosted manifest/artifacts.
4. Add Tauri commands exposed to React:
   - check for update
   - download and install update
   - return current app version
5. Add frontend update UI in settings, likely under `frontend/src/components/settings/*`:
   - current version
   - check for updates button
   - available version and release notes
   - download/install/restart flow
   - graceful offline/no-update states
6. Optionally check automatically on app start, but avoid blocking app launch.

### 7. Release Automation
1. Add GitHub Actions workflows for all target platforms:
   - Windows
   - macOS
   - Linux
2. Build frontend, PyInstaller backend, then Tauri bundle in each platform job.
3. Upload installers and updater artifacts to GitHub Releases.
4. Configure release signing/secrets:
   - Tauri updater private key
   - platform code signing certificates where available
   - macOS signing and notarization credentials
5. Tag releases with semantic versions, for example `v0.1.0`.
6. Keep app versions synchronized across:
   - root `package.json`
   - `frontend/package.json`
   - `src-tauri/tauri.conf.json`
   - backend app version if added for display.

### 8. Platform Packaging Notes
1. Windows:
   - Configure Tauri bundler for MSI/NSIS as appropriate.
   - Use the React first-run flow for polished onboarding instead of relying on default installer dialogs.
   - Add app icon, Start Menu entry, install directory metadata.
2. macOS:
   - Configure `.dmg`/`.app` bundle.
   - Auto-update requires signing; distribution outside local testing should be signed and notarized.
3. Linux:
   - Configure AppImage/deb/rpm as needed.
   - Validate updater support for chosen Linux artifact format and document any limitations.

### 9. Logging and Diagnostics
1. Add log files under platform app-data/logs for:
   - Tauri startup/backend spawning
   - backend stdout/stderr
   - updater check/install failures
2. Provide a settings action to open logs folder if feasible.
3. Include clear frontend error messages for backend startup failure and update failure.

### 10. Validation Plan
1. Existing checks:
   - `npm --prefix frontend run build`
   - `pytest` from `backend/`
2. Backend packaging:
   - run PyInstaller output directly
   - verify `/health`
   - verify `/api/settings/app`
   - verify upload/dashboard/PDF export paths
3. Tauri dev:
   - launch Tauri dev app
   - confirm backend starts automatically
   - complete setup flow
   - restart app and confirm setup remains complete
4. Desktop bundle:
   - install on clean Windows/macOS/Linux VM or test account
   - verify app launches without dev Python/Node installed
   - verify SQLite data lives in OS app-data directory
   - verify PDF export works without downloading Chromium
5. Updater:
   - publish a test GitHub prerelease or local update manifest
   - install older version
   - check for update
   - download/install
   - restart and confirm new version
6. Security checks:
   - backend binds only to `127.0.0.1`
   - updater signature verification is enabled
   - private signing keys are not committed

## Risks and Mitigations
- PyInstaller may miss dynamic imports or data files. Mitigate with a spec file, explicit hidden imports, and packaged smoke tests.
- Bundled Playwright Chromium will make installers much larger. Accept this for offline PDF reliability.
- macOS auto-update requires signing/notarization for real distribution. Keep local unsigned builds for development only.
- Dynamic API base URL must be initialized before first frontend API call. Centralize runtime config loading.
- Multiple app instances could attempt to start multiple backend processes. Add single-instance behavior or port/process guard if needed.

## Out of Scope for First Implementation
- Rewriting the backend in Rust.
- Adding a FastAPI `/api/update/check` endpoint for app installer updates.
- Cloud telemetry or user accounts.
- App stores/Microsoft Store/Mac App Store submission.

## Handoff Notes
- This is a source-changing implementation plan; switch to an implementation-capable agent before editing code.
- Keep source changes minimal and preserve the existing web dev workflow.
- Prefer adding desktop-specific behavior behind Tauri/runtime detection rather than forking the frontend app.
