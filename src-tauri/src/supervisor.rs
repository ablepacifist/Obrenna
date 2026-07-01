/// Supervisor for backend processes (MCP proxy and Python sidecar).
///
/// Rust owns the process lifecycle. On startup, MCP proxy is spawned first,
/// then Python is spawned with `OBRENNA_MCP_PROXY_URL` in its child env.
/// On shutdown, Rust attempts graceful Python shutdown via HTTP, then
/// forced kill+wait on both children.

use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use serde_json::json;
use tauri::Emitter;

use crate::backend::wait_for_backend;
use crate::mcp::McpProxy;

pub struct BackendProcesses {
    pub mcp_proxy: Option<McpProxy>,
    pub python_sidecar: Option<Child>,
    pub mcp_proxy_url: Option<String>,
    pub app_handle: Mutex<Option<tauri::AppHandle>>,
}

impl BackendProcesses {
    pub fn new() -> Self {
        BackendProcesses {
            mcp_proxy: None,
            python_sidecar: None,
            mcp_proxy_url: None,
            app_handle: Mutex::new(None),
        }
    }

    /// Start both MCP proxy and Python sidecar in the correct order.
    ///
    /// 1. Spawn MCP proxy server process first.
    /// 2. Bind TCP listener, get proxy_url.
    /// 3. Store MCP handle before spawning Python.
    /// 4. Spawn Python with `OBRENNA_MCP_PROXY_URL` in child env.
    /// 5. Start stdout reader thread.
    pub fn start(
        &mut self,
        app: &tauri::AppHandle,
        port: u16,
        data_dir: &std::path::PathBuf,
        mcp_server_path: &std::path::PathBuf,
    ) -> Result<String, String> {
        // Step 1: Spawn MCP proxy
        let mcp_proxy = McpProxy::new()
            .map_err(|e| format!("Failed to create MCP proxy: {}", e))?;

        let proxy_url = mcp_proxy.proxy_url();

        // Step 2: Spawn MCP server if available
        if !mcp_server_path.as_os_str().is_empty() && mcp_server_path.exists() {
            mcp_proxy.spawn_server(mcp_server_path)
                .map_err(|e| format!("Failed to spawn MCP server: {}", e))?;
            mcp_proxy.start_proxy()
                .map_err(|e| format!("MCP proxy relay failed: {}", e))?;
        } else {
            eprintln!("Warning: MCP server not found at {:?}", mcp_server_path);
        }

        // Step 3: Store MCP handle
        self.mcp_proxy = Some(mcp_proxy);
        self.mcp_proxy_url = Some(proxy_url.clone());

        // Step 4: Spawn Python with OBRENNA_MCP_PROXY_URL in child env
        let child = self.spawn_python_sidecar(app, port, data_dir, &proxy_url)?;
        self.python_sidecar = Some(child);

        // Store app handle for event emission
        {
            let mut handle_opt = self.app_handle.lock().unwrap();
            *handle_opt = Some(app.clone());
        }

        // Step 5: Start stdout reader thread
        let app_clone = app.clone();
        let python_child = self.python_sidecar.as_mut().unwrap().stdout.take();
        if let Some(stdout) = python_child {
            std::thread::spawn(move || {
                use std::io::{BufRead, BufReader};
                let reader = BufReader::new(stdout);
                for line in reader.lines() {
                    match line {
                        Ok(l) => {
                            handle_python_stdout_line(&app_clone, &l);
                        }
                        Err(_) => break,
                    }
                }
            });
        }

        Ok(proxy_url)
    }

    fn spawn_python_sidecar(
        &self,
        app: &tauri::AppHandle,
        port: u16,
        data_dir: &std::path::PathBuf,
        proxy_url: &str,
    ) -> Result<Child, String> {
        let resource_dir = app.path().resource_dir().map_err(|e| format!("failed to get resource dir: {}", e))?;
        let backend_exe = resource_dir.join("backend").join(executable_name("obrenna-server"));
        let old_backend_exe = resource_dir.join("backend").join(executable_name("grebglob-server"));

        let data_dir_str = data_dir.to_string_lossy().to_string();

        let mut cmd;

        if backend_exe.exists() {
            cmd = Command::new(&backend_exe);
            cmd.current_dir(&resource_dir);
        } else if old_backend_exe.exists() {
            cmd = Command::new(&old_backend_exe);
            cmd.current_dir(&resource_dir);
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
        }

        cmd.env("OBRENNA_DATA_DIR", data_dir_str)
            .env("OBRENNA_PORT", port.to_string())
            .env("OBRENNA_DESKTOP", "1")
            .env("OBRENNA_MCP_PROXY_URL", proxy_url)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        let child = cmd
            .spawn()
            .map_err(|e| format!("failed to start backend: {}", e))?;

        // Wait for backend to be ready
        let api_url = format!("http://127.0.0.1:{}", port);
        let url_clone = api_url.clone();
        let ready = tauri::async_runtime::spawn(async move {
            wait_for_backend(&url_clone, 30).await
        });
        let _ = tauri::async_runtime::block_on(ready);

        Ok(child)
    }

    /// Shutdown both MCP proxy and Python sidecar.
    ///
    /// 1. Try POST to /api/shutdown with 3s timeout.
    /// 2. kill() + wait() on Python child.
    /// 3. Stop MCP proxy.
    pub fn shutdown(&mut self, port: u16) {
        let api_url = format!("http://127.0.0.1:{}", port);

        // Step 1: Try graceful Python shutdown via HTTP
        let shutdown_client = reqwest::Client::new();
        let shutdown_url = api_url.clone();
        tauri::async_runtime::spawn(async move {
            let result = shutdown_client
                .post(format!("{}/api/shutdown", shutdown_url))
                .timeout(Duration::from_secs(3))
                .send()
                .await;
            if result.is_err() {
                eprintln!("Graceful Python shutdown failed (will force kill)");
            }
        });

        // Step 2: Kill Python child
        if let Some(mut proc) = self.python_sidecar.take() {
            let _ = proc.kill();
            let _ = proc.wait();
        }

        // Step 3: Stop MCP proxy
        if let Some(mcp) = self.mcp_proxy.take() {
            let _ = mcp.stop();
        }

        self.mcp_proxy_url = None;
    }
}

fn handle_python_stdout_line(app: &tauri::AppHandle, line: &str) {
    match serde_json::from_str::<serde_json::Value>(line) {
        Ok(val) => {
            if let Some(event_type) = val.get("type").and_then(|t| t.as_str()) {
                let valid = matches!(
                    event_type,
                    "token"
                        | "done"
                        | "error"
                        | "thinking_delta"
                        | "tool_call"
                        | "tool_result"
                        | "tool_progress"
                );
                if valid {
                    let _ = app.emit("agent-event", &val);
                } else {
                    let _ = app.emit(
                        "backend-log",
                        &serde_json::json!({"source":"python","line":line}),
                    );
                }
            } else {
                // Not a valid event (no "type" field)
                let _ = app.emit(
                    "backend-log",
                    &serde_json::json!({"source":"python","line":line}),
                );
            }
        }
        Err(_) => {
            // Invalid JSON — log only
            let _ = app.emit(
                "backend-log",
                &serde_json::json!({"source":"python","line":line}),
            );
        }
    }
}

fn executable_name(name: &str) -> String {
    if cfg!(windows) {
        format!("{}.exe", name)
    } else {
        name.to_string()
    }
}

fn project_root() -> std::path::PathBuf {
    std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("src-tauri must have a parent project directory")
        .to_path_buf()
}

fn resolve_python_executable(root: &std::path::PathBuf) -> String {
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
