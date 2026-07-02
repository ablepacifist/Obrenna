use std::net::TcpListener;
use std::io::Write;
use std::path::PathBuf;
use std::process::Command;
use std::time::Duration;

use serde::Serialize;
use tauri::{AppHandle, Manager};

use tokio::time::sleep;

// Supervisor is now managed by main.rs via BackendProcesses.
// Old globals removed: BACKEND_PROCESS, MCP_PROCESS, APP_HANDLE

pub fn find_free_port() -> u16 {
    match TcpListener::bind("127.0.0.1:0") {
        Ok(listener) => {
            let port = listener.local_addr().ok().map(|a| a.port()).unwrap_or(8000);
            port
        }
        Err(_) => 8000,
    }
}

pub fn executable_name(name: &str) -> String {
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

pub async fn wait_for_backend(url: &str, timeout_secs: u64) -> bool {
    let port = match url.split(':').last() {
        Some(p) => p.parse::<u16>().unwrap_or(8000),
        None => 8000,
    };

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

        match std::net::TcpStream::connect(format!("127.0.0.1:{}", port)) {
            Ok(mut stream) => {
                let req = b"HEAD /health HTTP/1.0\r\nHost: localhost\r\n\r\n";
                if stream.write_all(req).is_ok() {
                    return true;
                }
            }
            Err(_) => {}
        }
        sleep(Duration::from_millis(500)).await;
    }
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

    if new_dir.exists() {
        return new_dir;
    }

    if old_dir.exists() {
        if std::fs::rename(&old_dir, &new_dir).is_ok() {
            eprintln!("Migrated data from {:?} to {:?}", old_dir, new_dir);
            return new_dir;
        }

        if std::fs::copy(&old_dir, &new_dir).is_ok()
            || copy_dir_recursive(&old_dir, &new_dir).is_ok()
        {
            eprintln!("Copied data from {:?} to {:?}", old_dir, new_dir);
            return new_dir;
        }

        eprintln!("Warning: Failed to migrate data from {:?} to {:?}", old_dir, new_dir);
        return old_dir;
    }

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
        let _ = Command::new("explorer").arg(&dir).spawn();
    }

    #[cfg(target_os = "macos")]
    {
        let _ = Command::new("open").arg(&dir).spawn();
    }

    #[cfg(target_os = "linux")]
    {
        let _ = Command::new("xdg-open").arg(&dir).spawn();
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
        let _ = Command::new("explorer").arg(&log_dir).spawn();
    }

    #[cfg(target_os = "macos")]
    {
        let _ = Command::new("open").arg(&log_dir).spawn();
    }

    #[cfg(target_os = "linux")]
    {
        let _ = Command::new("xdg-open").arg(&log_dir).spawn();
    }

    Ok(())
}

#[tauri::command]
pub fn get_logs_dir() -> String {
    get_obrenna_dir().join("logs").to_string_lossy().to_string()
}
