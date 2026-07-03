/// Ollama engine lifecycle.
///
/// Ollama is bundled with Obrenna as a Tauri resource (see `resources/ollama/`
/// and `tauri.conf.json`). Rust owns the engine process just like it owns the
/// Python sidecar and MCP proxy: on startup the supervisor calls
/// [`ensure_serving`], and on shutdown it kills the child we spawned.
///
/// If port 11434 is already answering (a user's own `ollama serve`, or a
/// previous Obrenna run), we reuse it and never spawn a second copy — Ollama
/// cannot bind the port twice anyway, and we must not kill a process we don't
/// own on shutdown.

use std::net::TcpStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

use serde_json::{json, Value};

pub const OLLAMA_PORT: u16 = 11434;

fn exe(name: &str) -> String {
    if cfg!(windows) {
        format!("{}.exe", name)
    } else {
        name.to_string()
    }
}

/// True when something is listening on the Ollama port.
pub fn is_running() -> bool {
    TcpStream::connect_timeout(
        &format!("127.0.0.1:{}", OLLAMA_PORT).parse().unwrap(),
        Duration::from_millis(500),
    )
    .is_ok()
}

/// Locate the ollama binary. Preference order:
/// 1. Bundled resource shipped inside the installer (`<resource_dir>/ollama/`).
/// 2. Dev-tree copy under `src-tauri/resources/ollama/` (for `cargo`/`tauri dev`).
/// 3. A system-wide install on PATH or a known location (graceful fallback so a
///    developer machine without the bundled binary still works).
pub fn resolve_binary(resource_dir: &Path) -> Option<PathBuf> {
    // 1. Bundled resource.
    let bundled = resource_dir.join("ollama").join(exe("ollama"));
    if bundled.exists() {
        return Some(bundled);
    }

    // 2. Dev tree (CARGO_MANIFEST_DIR is src-tauri).
    let dev = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("resources")
        .join("ollama")
        .join(exe("ollama"));
    if dev.exists() {
        return Some(dev);
    }

    // 3. System install.
    resolve_system_binary()
}

fn resolve_system_binary() -> Option<PathBuf> {
    // PATH first.
    if let Ok(paths) = std::env::var("PATH") {
        for dir in std::env::split_paths(&paths) {
            let candidate = dir.join(exe("ollama"));
            if candidate.exists() {
                return Some(candidate);
            }
        }
    }

    // Common install locations.
    if let Some(local) = dirs::data_local_dir() {
        let p1 = local.join("Programs").join("Ollama").join(exe("ollama"));
        if p1.exists() {
            return Some(p1);
        }
        let p2 = local.join("Ollama").join(exe("ollama"));
        if p2.exists() {
            return Some(p2);
        }
    }
    if let Some(home) = dirs::home_dir() {
        let p = home.join(exe("ollama"));
        if p.exists() {
            return Some(p);
        }
    }

    None
}

/// Poll the Ollama port until it answers or the timeout elapses.
pub fn wait_until_healthy(timeout: Duration) -> bool {
    let start = Instant::now();
    while start.elapsed() < timeout {
        if is_running() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(300));
    }
    is_running()
}

pub enum EnsureOutcome {
    /// Something was already serving on the port; we did not spawn anything.
    AlreadyRunning,
    /// We spawned `ollama serve`. The `Child` must be retained by the caller so
    /// it can be killed on shutdown.
    Started(Child),
    /// No ollama binary could be located (bundled resource missing).
    NotFound,
    /// The binary was found but spawning it failed.
    Failed(String),
}

/// Ensure Ollama is serving. Reuses an existing instance if present; otherwise
/// spawns the bundled `ollama serve` with its model store pointed at Obrenna's
/// data directory so pulled models are self-contained and removed on uninstall.
pub fn ensure_serving(resource_dir: &Path, data_dir: &Path) -> EnsureOutcome {
    if is_running() {
        return EnsureOutcome::AlreadyRunning;
    }

    let bin = match resolve_binary(resource_dir) {
        Some(b) => b,
        None => return EnsureOutcome::NotFound,
    };

    // Keep the model store beside the rest of Obrenna's data so it is
    // self-contained and uninstall-clean.
    let models_dir = data_dir.join("ollama-models");
    let _ = std::fs::create_dir_all(&models_dir);

    let spawn = Command::new(&bin)
        .arg("serve")
        .env("OLLAMA_MODELS", &models_dir)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn();

    match spawn {
        Ok(child) => {
            // Port binds within ~1s; models load lazily on first request.
            wait_until_healthy(Duration::from_secs(20));
            EnsureOutcome::Started(child)
        }
        Err(e) => EnsureOutcome::Failed(e.to_string()),
    }
}

/// Tauri command backing the Ollama panel in Settings. Ensures the engine is
/// serving and reports status. The spawned child (if any) is intentionally
/// dropped — on all platforms dropping `std::process::Child` does not kill the
/// process, so a manually-started engine keeps running. The supervised
/// lifecycle child is tracked separately by `BackendProcesses`.
#[tauri::command]
pub fn start_ollama(app: tauri::AppHandle) -> Value {
    use tauri::Manager;

    let resource_dir = match app.path().resource_dir() {
        Ok(d) => d,
        Err(e) => {
            return json!({
                "status": "error",
                "message": format!("Failed to resolve resource dir: {}", e)
            })
        }
    };
    let data_dir = crate::backend::migrate_data_dir();

    match ensure_serving(&resource_dir, &data_dir) {
        EnsureOutcome::AlreadyRunning => json!({
            "status": "running",
            "message": "Ollama is already running on port 11434"
        }),
        EnsureOutcome::Started(_child) => {
            if is_running() {
                json!({ "status": "started", "message": "Ollama started successfully." })
            } else {
                json!({
                    "status": "started",
                    "message": "Ollama process started but not yet listening."
                })
            }
        }
        EnsureOutcome::NotFound => json!({
            "status": "not_found",
            "message": "The bundled Ollama engine could not be found. Reinstalling Obrenna should restore it."
        }),
        EnsureOutcome::Failed(e) => json!({
            "status": "error",
            "message": format!("Failed to start Ollama: {}", e)
        }),
    }
}
