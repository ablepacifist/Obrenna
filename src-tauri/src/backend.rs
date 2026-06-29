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
        .join("grebglob-server");

    let backend_path = if backend_exe.exists() {
        backend_exe
    } else {
        app.path().resolve("resources/backend/grebglob-server").map_err(|e| format!("resolve backend path: {}", e))?
    };

    if !backend_path.exists() {
        eprintln!("Backend executable not found at: {:?}", backend_path);
        return Err(format!("Backend executable not found at: {:?}", backend_path));
    }

    let data_dir_str = data_dir.to_string_lossy().to_string();
    let api_url = format!("http://127.0.0.1:{}", port);

    let mut cmd = Command::new(&backend_path);
    cmd.env("GREBGLOB_DATA_DIR", data_dir_str)
        .env("GREBGLOB_PORT", port.to_string())
        .env("GREBGLOB_DESKTOP", "1")
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

#[tauri::command]
pub fn get_data_dir() -> String {
    dirs::config_dir()
        .unwrap_or_else(|| std::path::PathBuf::from("."))
        .join("GrebGlob")
        .to_string_lossy()
        .to_string()
}

#[tauri::command]
pub fn open_data_dir() -> Result<(), String> {
    let dir = dirs::config_dir()
        .unwrap_or_else(|| std::path::PathBuf::from("."))
        .join("GrebGlob");

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
    let log_dir = dirs::config_dir()
        .unwrap_or_else(|| std::path::PathBuf::from("."))
        .join("GrebGlob")
        .join("logs");

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
    dirs::config_dir()
        .unwrap_or_else(|| std::path::PathBuf::from("."))
        .join("GrebGlob")
        .join("logs")
        .to_string_lossy()
        .to_string()
}
