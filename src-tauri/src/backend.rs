use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Arc;
use std::time::Duration;

use serde::Serialize;
use tauri::AppHandle;

use reqwest;
use tauri::async_runtime::sleep;

static mut BACKEND_PROCESS: Option<Child> = None;

pub fn find_free_port() -> u16 {
    match TcpListener::bind("127.0.0.1:0") {
        Ok(listener) => {
            let port = listener.local_addr().ok().map(|a| a.port()).unwrap_or(8000);
            port
        }
        Err(_) => 8000,
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
    let resource_dir = app.path().resource_dir().expect("failed to get resource dir");
    let backend_exe = resource_dir
        .join("..")
        .join("resources")
        .join("backend")
        .join("obrenna-server");

    let backend_path = if backend_exe.exists() {
        backend_exe
    } else {
        // Fallback: check for old grebglob-server name for manual bundle compatibility
        let old_path = app.path().resolve("resources/backend/grebglob-server").map_err(|e| format!("resolve backend path: {}", e))?;
        if old_path.exists() {
            old_path
        } else {
            return Err(format!("Backend executable not found at: {:?} or fallback {:?}", backend_exe, old_path));
        }
    };

    if !backend_path.exists() {
        eprintln!("Backend executable not found at: {:?}", backend_path);
        return Err(format!("Backend executable not found at: {:?}", backend_path));
    }

    let data_dir_str = data_dir.to_string_lossy().to_string();
    let api_url = format!("http://127.0.0.1:{}", port);

    let mut cmd = Command::new(&backend_path);
    cmd.env("OBRENNA_DATA_DIR", data_dir_str)
        .env("OBRENNA_PORT", port.to_string())
        .env("OBRENNA_DESKTOP", "1")
        .current_dir(resource_dir);

    let child = cmd
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .map_err(|e| format!("failed to start backend: {}", e))?;

    unsafe {
        BACKEND_PROCESS = Some(child);
    }

    tauri::async_runtime::spawn(async move {
        if let Some(proc) = unsafe { &mut BACKEND_PROCESS } {
            let _ = proc.wait().await;
        }
    });

    let url_clone = api_url.clone();
    let ready = tauri::async_runtime::spawn(async move {
        wait_for_backend(&url_clone, 30).await
    });

    tauri::async_runtime::block_on(ready);

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

fn migrate_data_dir() -> PathBuf {
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
