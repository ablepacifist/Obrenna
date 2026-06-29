# Obrenna Full Rebrand Plan

## Goal
Rebrand the application from GrebGlob to Obrenna across visible product surfaces and internal technical identifiers, while preserving existing user data through a safe migration/fallback path.

## Confirmed Decision
- Scope: full rename.
- New brand/product name: `Obrenna`.
- New icon source: `src-tauri/icons/ObrennaAppLogo.png`.
- Existing `GrebGlob` local data must not be stranded after the rename.

## Current Code Context
- Tauri product metadata lives in `src-tauri/tauri.conf.json`.
- Desktop backend launch and data/log path handling lives in `src-tauri/src/main.rs` and `src-tauri/src/backend.rs`.
- Packaged backend binary is currently named `grebglob-server` via `backend/grebglob-server.spec` and `.github/workflows/build.yml`.
- Backend API title and service strings include `GrebGlob` in `backend/main.py`, `backend/desktop_server.py`, `backend/app/services/summarize.py`, tests, and package docs/comments.
- Frontend visible brand references are limited, but `frontend/index.html` still uses generic title `frontend` and favicon `/favicon.svg`.
- Tauri currently expects `src-tauri/icons/icon.png`, `icon.ico`, and `icon.icns`; only new source asset found is `src-tauri/icons/ObrennaAppLogo.png`.

## Implementation Steps
1. Update Tauri app identity and visible metadata.
   - Change `productName` and main window `title` from `GrebGlob` to `Obrenna` in `src-tauri/tauri.conf.json`.
   - Change `identifier` from `com.grebglob.app` to an Obrenna reverse-domain identifier, recommended `com.obrenna.app` unless the repo owner has a real owned domain.
   - Update NSIS `licenseUrl` and updater endpoint URLs from `GrebGlob/grebglob` to the Obrenna repository path if known. If the new repository URL is not known, use a clearly marked placeholder or preserve the old URL only if releases remain hosted there.

2. Wire the new app icon.
   - Generate Tauri icon assets from `src-tauri/icons/ObrennaAppLogo.png` using the Tauri icon command if available, for example `npm --prefix frontend exec tauri icon ../src-tauri/icons/ObrennaAppLogo.png` from repo root, or the equivalent project-supported command.
   - Ensure `src-tauri/icons/icon.png`, `src-tauri/icons/icon.ico`, and `src-tauri/icons/icon.icns` are updated because `tauri.conf.json` references those paths.
   - Preserve or regenerate NSIS `header.bmp` and `sidebar.bmp` only if the current files exist or Tauri requires them for Windows packaging.
   - Update `frontend/public/favicon.svg` or replace frontend favicon usage with a web-compatible Obrenna icon copied/generated from the source logo. Update `frontend/index.html` title to `Obrenna`.

3. Rename backend executable and packaging artifacts.
   - Rename PyInstaller spec file from `backend/grebglob-server.spec` to `backend/obrenna-server.spec` if repository conventions allow file rename.
   - Inside the spec, change `name='grebglob-server'` to `name='obrenna-server'` and update the module docstring.
   - Update `.github/workflows/build.yml` to run `pyinstaller obrenna-server.spec --clean`, upload/download `obrenna-server(.exe)`, chmod the new name, copy it into release assets under the new name, and publish the new asset name.
   - Update `src-tauri/src/backend.rs` to resolve and launch `resources/backend/obrenna-server`.
   - Add fallback resolution for `resources/backend/grebglob-server` only if supporting existing manually assembled bundles is necessary; otherwise remove the old binary name entirely.

4. Rename environment variables with compatibility fallback.
   - Replace `GREBGLOB_DATA_DIR`, `GREBGLOB_PORT`, and `GREBGLOB_DESKTOP` with `OBRENNA_DATA_DIR`, `OBRENNA_PORT`, and `OBRENNA_DESKTOP` in Rust launcher and Python backend startup/config code.
   - In backend config/loading code, read new `OBRENNA_*` variables first and fall back to old `GREBGLOB_*` values to support old launch scripts or user environments.
   - Update `.env.example`, dev scripts, and tests if they reference old env vars.

5. Migrate local app data and logs safely.
   - Change the canonical config/data directory from `dirs::config_dir()/GrebGlob` to `dirs::config_dir()/Obrenna` in Rust path helpers.
   - Implement startup migration in `get_data_dir` or a small helper called by it:
     - If `Obrenna` directory exists, use it.
     - Else if `GrebGlob` exists, attempt to rename/move it to `Obrenna`.
     - If rename fails, attempt recursive copy to `Obrenna` and continue with `Obrenna` if copy succeeds.
     - If migration fails, fall back to using `GrebGlob` only if this is safer than starting with empty data; log/return a clear error if neither path is usable.
   - Update `get_data_dir`, `open_data_dir`, `get_logs_dir`, and `open_logs_dir` to use a shared canonical path helper so behavior stays consistent.
   - Avoid deleting the old `GrebGlob` directory during migration.

6. Update source-visible brand strings.
   - Replace user-facing and descriptive `GrebGlob` occurrences with `Obrenna` in:
     - `backend/main.py`
     - `backend/desktop_server.py`
     - `backend/app/__init__.py`
     - `backend/app/services/summarize.py`
     - tests expecting generated `prepared_by`
     - `src-tauri/capabilities/default.json`
     - `src-tauri/Cargo.toml` description/authors and crate names only if changing crate names is acceptable.
   - For Rust crate/package names, prefer changing Cargo package/library names to `obrenna` / `obrenna_lib` for full rename, then update any generated lockfile references produced by normal build tooling.
   - Update root `package.json` and lockfile package names from `grebglob-workspace` to `obrenna-workspace`.
   - Update `shared/artifact-schema.json` `$id` from `https://grebglob.local/...` to `https://obrenna.local/...` unless external consumers rely on the old schema ID.

7. Update docs and scripts.
   - Update README heading and architecture docs from GrebGlob to Obrenna.
   - Update `dev.ps1` and `dev.bat` visible messages/comments.
   - Update stale `.kilo/plans` only if the implementation owner wants historical planning files rebranded; default recommendation is to leave historical plans untouched because they are archival.

8. Clean generated/build outputs deliberately.
   - Do not edit `node_modules`, `frontend/dist`, `__pycache__`, database files, or uploaded sample data manually.
   - Rebuild generated outputs only through normal build commands if the project expects committed generated files. Otherwise leave them untracked/ignored.

## Validation
1. Run targeted text checks excluding generated/dependency folders:
   - Search for `GrebGlob`, `grebglob`, `greb-glob`, and `GREBGLOB` outside `.git`, `node_modules`, `frontend/dist`, `__pycache__`, and archival `.kilo/plans`.
   - Verify remaining occurrences are intentional compatibility fallbacks or archival references.
2. Run backend tests from `backend`, expected command: `pytest`.
3. Run frontend build, expected command: `npm --prefix frontend run build`.
4. Run a Tauri config/build check if dependencies are installed, for example `npm --prefix frontend exec tauri build -- --help` or a real dev/build command appropriate for the repo.
5. Verify icon outputs exist and match Tauri config references: `src-tauri/icons/icon.png`, `icon.ico`, `icon.icns`.
6. Verify the workflow references `obrenna-server` consistently.
7. Manually inspect the migration helper logic for these scenarios:
   - Fresh install with no old data.
   - Existing `GrebGlob` data and no `Obrenna` directory.
   - Both old and new directories exist.
   - Old directory exists but move/copy fails.

## Risks And Notes
- Changing `identifier` creates a new app identity on some platforms. This is intended for full rebrand but may affect update continuity, install location, and OS app preferences.
- Renaming data directories without migration would look like data loss. The migration/fallback is required.
- Release/updater URLs cannot be fully correct unless the new GitHub organization/repository path is known.
- Renaming Rust crate/package names and Node package names may update lockfiles; implementation should include only intentional lockfile changes.
- Historical `.kilo/plans` references to GrebGlob should normally remain unchanged unless explicitly requested.

## Out Of Scope Unless Requested
- Redesigning UI layout or theme beyond branding/icon/title changes.
- Deleting old local `GrebGlob` data directories.
- Changing sample uploaded data or local database contents.
- Publishing releases, pushing commits, or creating pull requests.
