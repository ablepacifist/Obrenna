#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod backend;
mod mcp;
mod ollama;
mod supervisor;
mod updater;

use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use supervisor::BackendProcesses;
use tauri::Manager;

struct AppState {
    backend_port: u16,
}

fn main() {
    let port = backend::find_free_port();

    let state = Arc::new(Mutex::new(AppState { backend_port: port }));
    let setup_state = state.clone();
    let window_state = state.clone();

    tauri::Builder::default()
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .manage(state.clone())
        .manage(Mutex::new(BackendProcesses::new()))
        .setup(move |app| {
            let data_dir = get_data_dir();

            // Resolve MCP server path
            let resource_dir = app.path().resource_dir().expect("failed to get resource dir");
            let mcp_server_path = resolve_mcp_server_path(&resource_dir);

            // Start supervisor
            let processes = app.state::<Mutex<BackendProcesses>>();
            let mut proc_guard = processes.lock().unwrap();
            let _ = proc_guard.start(
                app.handle(),
                port,
                &data_dir,
                mcp_server_path.as_deref(),
            );

            let mut state = setup_state.lock().unwrap();
            state.backend_port = port;

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            backend::get_api_base_url,
            backend::get_data_dir,
            backend::open_data_dir,
            backend::open_logs_dir,
            backend::get_logs_dir,
            ollama::start_ollama,
            updater::check_update,
            updater::install_update,
            updater::get_app_version,
        ])
        .on_window_event(move |app, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                let state = window_state.lock().unwrap();
                let port = state.backend_port;
                drop(state);

                // Acquire supervisor and call shutdown
                let processes = app.state::<Mutex<BackendProcesses>>();
                let mut proc_guard = processes.lock().unwrap();
                proc_guard.shutdown(port);

                let app_handle = app.app_handle().clone();
                tauri::async_runtime::spawn(async move {
                    let _ = app_handle.exit(0);
                });
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Obrenna");
}

fn resolve_mcp_server_path(resource_dir: &PathBuf) -> Option<PathBuf> {
    // Packaged resources: resource_dir/mcp/obrenna-mcp.exe
    let packed = resource_dir.join("mcp").join(backend::executable_name("obrenna-mcp"));
    if packed.exists() {
        return Some(packed);
    }

    // Dev mode: CARGO_MANIFEST_DIR/../resources/mcp/obrenna-mcp.exe
    let dev_path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .map(|p| p.to_path_buf())
        .and_then(|parent| {
            let dev = parent.join("src-tauri").join("resources").join("mcp").join("obrenna-mcp.exe");
            if dev.exists() {
                Some(dev)
            } else {
                None
            }
        });

    dev_path
}

fn get_data_dir() -> PathBuf {
    let data_dir = backend::migrate_data_dir();

    let data_dir_str = data_dir.to_string_lossy();
    std::env::set_var("OBRENNA_DATA_DIR", data_dir_str.as_ref());

    if !data_dir.exists() {
        let _ = std::fs::create_dir_all(&data_dir);
    }

    data_dir
}
