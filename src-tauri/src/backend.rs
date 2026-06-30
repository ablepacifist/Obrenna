use std::io::{BufRead, BufReader};
use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use serde::Serialize;
use tauri::{AppHandle, Manager};
use tauri::Emitter;

use reqwest;
use tokio::time::sleep;

static BACKEND_PROCESS: Mutex<Option<Child>> = Mutex::new(None);
static MCP_PROCESS: Mutex<Option<Child>> = Mutex::new(None);
static APP_HANDLE: Mutex<Option<AppHandle>> = Mutex::new(None);

pub fn find_free_port() -> u16 {
    match TcpListener::bind("127.0.0.1:0") {
        Ok(listener) => {
            let port = listener.local_addr().ok().map(|a| a.port()).unwrap_or(8000);
            port
        }
        Err(_) => 8000,
    }
}

fn executable_name(name: &str) -> String {
    if cfg!(windows) {
        format!("{}.exe", name)
    } else {
        name.to_string()
    }
}

fn project_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("src-tauri must have a parent project directory")
        .to_path_buf()
}

fn resolve_python_executable(root: &PathBuf) -> String {
    let venv_python = root
        .join(".venv")
        .join(if cfg!(windows) { "Scripts" } else { "bin" })
        .join(executable_name("python"));

    if venv_python.exists() {
        venv_python.to_string_lossy().to_string()
    } else {
        "python".to_string()
    }
}

async fn wait_for_backend(url: &str, timeout_secs: u64) -> bool {
    let client = reqwest::Client::new();
    let start = std::time::Instant::now();
    let mut attempts = 0u32;

    loop {
        if start.elapsed() > Duration::from_secs(timeout_secs) {
            return false;
        }
        attempts += 1;
        if attempts > 60 {
            return false;
        }

        match client.get(format!("{}/health", url)).send().await {
            Ok(resp) if resp.status().is_success() => return true,
            Ok(_) => {}
            Err(_) => {}
        }
        sleep(Duration::from_millis(500)).await;
    }
}

pub fn start_backend(app: &AppHandle, port: u16, data_dir: &PathBuf) -> Result<(), String> {
    // Store AppHandle for agent event emission
    let mut handle_opt = APP_HANDLE.lock().unwrap();
    *handle_opt = Some(app.clone());

    let resource_dir = app.path().resource_dir().expect("failed to get resource dir");
    let backend_exe = resource_dir
        .join("backend")
        .join(executable_name("obrenna-server"));

    let old_backend_exe = resource_dir
        .join("backend")
        .join(executable_name("grebglob-server"));

    let data_dir_str = data_dir.to_string_lossy().to_string();
    let api_url = format!("http://127.0.0.1:{}", port);

    let mut cmd;
    let mcp_resource_dir;

    if backend_exe.exists() {
        cmd = Command::new(&backend_exe);
        cmd.current_dir(&resource_dir);
        mcp_resource_dir = resource_dir.clone();
    } else if old_backend_exe.exists() {
        // Fallback for old manually assembled bundles.
        cmd = Command::new(&old_backend_exe);
        cmd.current_dir(&resource_dir);
        mcp_resource_dir = resource_dir.clone();
    } else {
        let root = project_root();
        let backend_script = root.join("backend").join("desktop_server.py");
        if !backend_script.exists() {
            return Err(format!(
                "Backend executable not found at {:?}, fallback {:?}, or dev script {:?}",
                backend_exe, old_backend_exe, backend_script
            ));
        }

        cmd = Command::new(resolve_python_executable(&root));
        cmd.arg(&backend_script).current_dir(root.join("backend"));
        mcp_resource_dir = root.join("src-tauri").join("resources");
    }

    cmd.env("OBRENNA_DATA_DIR", data_dir_str)
        .env("OBRENNA_PORT", port.to_string())
        .env("OBRENNA_DESKTOP", "1");

    let child = cmd
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .map_err(|e| format!("failed to start backend: {}", e))?;

    *BACKEND_PROCESS.lock().unwrap() = Some(child);

    // Spawn MCP server if available
    let mcp_server_path = mcp_resource_dir
        .join("mcp")
        .join(executable_name("obrenna-mcp"));
    let mcp_server_path = if mcp_server_path.exists() {
        mcp_server_path
    } else {
        // Fallback: check for .exe extension on Windows
        let mcp_exe = mcp_server_path.with_extension("exe");
        if mcp_exe.exists() { mcp_exe } else { PathBuf::new() }
    };

    if !mcp_server_path.as_os_str().is_empty() && mcp_server_path.exists() {
        let mcp_cmd = Command::new(&mcp_server_path)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn();

        match mcp_cmd {
            Ok(mcp_child) => {
                *MCP_PROCESS.lock().unwrap() = Some(mcp_child);
                // Start MCP proxy TCP listener for Python sidecar
                if let Ok(listener) = TcpListener::bind("127.0.0.1:0") {
                    let proxy_port = listener.local_addr().unwrap().port();
                    // Pass proxy URL to Python backend via env var
                    std::env::set_var("OBRENNA_MCP_PROXY_URL", format!("tcp://127.0.0.1:{}", proxy_port));
                    drop(listener);
                }
            }
            Err(e) => {
                eprintln!("Warning: Failed to spawn MCP server: {}", e);
            }
        }
    }

    tauri::async_runtime::spawn(async move {
        let backend_process = BACKEND_PROCESS.lock().unwrap().take();
        if let Some(mut proc) = backend_process {
            // Read Python sidecar stdout for agent event envelopes
            if let Some(stdout) = proc.stdout.take() {
                let reader = BufReader::new(stdout);
                for line in reader.lines() {
                    match line {
                        Ok(l) => {
                            // Emit agent events to webview
                            if let Ok(app_guard) = APP_HANDLE.lock() {
                                if let Some(app) = app_guard.as_ref() {
                                    let _ = app.emit("agent-event", &l);
                                }
                            }
                        }
                        Err(_) => break,
                    }
                }
            }
            let _ = proc.wait();
        }
        // Also terminate MCP server when backend exits
        let mcp_process = MCP_PROCESS.lock().unwrap().take();
        if let Some(mut mcp) = mcp_process {
            let _ = mcp.kill();
            let _ = mcp.wait();
        }
    });

    let url_clone = api_url.clone();
    let ready = tauri::async_runtime::spawn(async move {
        wait_for_backend(&url_clone, 30).await
    });

    let _ = tauri::async_runtime::block_on(ready);

    Ok(())
}

#[derive(Serialize)]
pub struct ApiResponse {
    pub base_url: String,
    pub port: u16,
}

#[tauri::command]
pub fn get_api_base_url(app: AppHandle) -> Result<ApiResponse, String> {
    let state = app.state::<std::sync::Arc<std::sync::Mutex<super::AppState>>>();
    let s = state.lock().map_err(|_| "failed to lock state")?;
    Ok(ApiResponse {
        base_url: format!("http://127.0.0.1:{}", s.backend_port),
        port: s.backend_port,
    })
}

fn get_obrenna_dir() -> PathBuf {
    dirs::config_dir()
        .unwrap_or_else(|| std::path::PathBuf::from("."))
        .join("Obrenna")
}

pub fn migrate_data_dir() -> PathBuf {
    let new_dir = get_obrenna_dir();
    let old_dir = dirs::config_dir()
        .unwrap_or_else(|| std::path::PathBuf::from("."))
        .join("GrebGlob");

    // If new dir already exists, use it
    if new_dir.exists() {
        return new_dir;
    }

    // If old dir exists, try to rename it to the new name
    if old_dir.exists() {
        // Try rename first
        if std::fs::rename(&old_dir, &new_dir).is_ok() {
            eprintln!("Migrated data from {:?} to {:?}", old_dir, new_dir);
            return new_dir;
        }

        // If rename fails (e.g., cross-volume on Windows), try recursive copy
        if std::fs::copy(&old_dir, &new_dir).is_ok()
            || copy_dir_recursive(&old_dir, &new_dir).is_ok()
        {
            eprintln!("Copied data from {:?} to {:?}", old_dir, new_dir);
            return new_dir;
        }

        eprintln!("Warning: Failed to migrate data from {:?} to {:?}", old_dir, new_dir);
        // Fall back to old directory to avoid data loss
        return old_dir;
    }

    // Neither exists — return new dir (will be created on demand)
    new_dir
}

fn copy_dir_recursive(src: &PathBuf, dst: &PathBuf) -> std::io::Result<()> {
    std::fs::create_dir_all(dst)?;
    for entry in std::fs::read_dir(src)? {
        let entry = entry?;
        let file_type = entry.file_type()?;
        let src_path = entry.path();
        let dst_path = dst.join(entry.file_name());
        if file_type.is_dir() {
            copy_dir_recursive(&src_path, &dst_path)?;
        } else {
            std::fs::copy(&src_path, &dst_path)?;
        }
    }
    Ok(())
}

#[tauri::command]
pub fn get_data_dir() -> String {
    migrate_data_dir().to_string_lossy().to_string()
}

#[tauri::command]
pub fn open_data_dir() -> Result<(), String> {
    let dir = migrate_data_dir();

    if !dir.exists() {
        let _ = std::fs::create_dir_all(&dir);
    }

    #[cfg(target_os = "windows")]
    {
        let _ = Command::new("explorer")
            .arg(&dir)
            .spawn();
    }

    #[cfg(target_os = "macos")]
    {
        let _ = Command::new("open")
            .arg(&dir)
            .spawn();
    }

    #[cfg(target_os = "linux")]
    {
        let _ = Command::new("xdg-open")
            .arg(&dir)
            .spawn();
    }

    Ok(())
}

#[tauri::command]
pub fn open_logs_dir() -> Result<(), String> {
    let log_dir = get_obrenna_dir().join("logs");

    if !log_dir.exists() {
        let _ = std::fs::create_dir_all(&log_dir);
    }

    #[cfg(target_os = "windows")]
    {
        let _ = Command::new("explorer")
            .arg(&log_dir)
            .spawn();
    }

    #[cfg(target_os = "macos")]
    {
        let _ = Command::new("open")
            .arg(&log_dir)
            .spawn();
    }

    #[cfg(target_os = "linux")]
    {
        let _ = Command::new("xdg-open")
            .arg(&log_dir)
            .spawn();
    }

    Ok(())
}

#[tauri::command]
pub fn get_logs_dir() -> String {
    get_obrenna_dir()
        .join("logs")
        .to_string_lossy()
        .to_string()
}
