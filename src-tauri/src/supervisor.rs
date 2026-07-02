/// Supervisor for backend processes (MCP proxy and Python sidecar).
///
/// Rust owns the process lifecycle. On startup, MCP proxy is spawned first,
/// then Python is spawned with `OBRENNA_MCP_PROXY_URL` in its child env.
/// On shutdown, Rust attempts graceful Python shutdown via HTTP, then
/// forced kill+wait on both children.

use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use serde_json::Value;
use tauri::{Emitter, Manager};

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
        mcp_server_path: Option<&Path>,
    ) -> Result<String, String> {
        // Step 1: Create MCP proxy and spawn server only if path exists
        if let Some(server_path) = mcp_server_path {
            if server_path.exists() {
                let mcp_proxy = McpProxy::new()
                    .map_err(|e| format!("Failed to create MCP proxy: {}", e))?;

                let proxy_url = mcp_proxy.proxy_url();

                // file_read is scoped to the app's own data directory (uploads +
                // artifacts) — never the whole filesystem. See CRIT-003 in the
                // audit: an unset allowlist previously meant "read anything".
                let uploads_dir = data_dir.join("uploads");
                let artifacts_dir = data_dir.join("artifacts");
                let file_allowlist = std::env::join_paths([&uploads_dir, &artifacts_dir])
                    .map(|s| s.to_string_lossy().to_string())
                    .unwrap_or_default();

                mcp_proxy.spawn_server(server_path, &file_allowlist)
                    .map_err(|e| format!("Failed to spawn MCP server: {}", e))?;
                mcp_proxy.start_proxy()
                    .map_err(|e| format!("MCP proxy relay failed: {}", e))?;

                self.mcp_proxy = Some(mcp_proxy);
                self.mcp_proxy_url = Some(proxy_url.clone());
            } else {
                eprintln!("Warning: MCP server not found, Python will use in-process transport");
            }
        }

        // Step 2: Spawn Python sidecar
        let child = self.spawn_python_sidecar(app, port, data_dir)?;
        self.python_sidecar = Some(child);

        // Step 3: Store app handle for event emission
        {
            let mut handle_opt = self.app_handle.lock().unwrap();
            *handle_opt = Some(app.clone());
        }

        // Step 4: Start stdout reader thread
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

        Ok(self.mcp_proxy_url.clone().unwrap_or_default())
    }

    fn spawn_python_sidecar(
        &self,
        app: &tauri::AppHandle,
        port: u16,
        data_dir: &std::path::PathBuf,
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

        let mut cmd = cmd.env("OBRENNA_DATA_DIR", data_dir_str)
            .env("OBRENNA_PORT", port.to_string())
            .env("OBRENNA_DESKTOP", "1")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        if let Some(ref url) = self.mcp_proxy_url {
            cmd = cmd.env("OBRENNA_MCP_PROXY_URL", url);
        }

        let mut child = cmd
            .spawn()
            .map_err(|e| format!("failed to start backend: {}", e))?;

        // Drain stderr on a dedicated thread immediately after spawn. If left
        // unread, uvicorn's access logs and any Python tracebacks fill the OS
        // pipe buffer (~64KB) and the child blocks on write() — freezing the
        // whole backend. stdout is drained separately by the caller (it
        // carries typed agent-event JSON and must be parsed there instead).
        if let Some(stderr) = child.stderr.take() {
            std::thread::spawn(move || {
                use std::io::{BufRead, BufReader};
                let reader = BufReader::new(stderr);
                for line in reader.lines() {
                    match line {
                        Ok(l) => eprintln!("[obrenna-backend] {}", l),
                        Err(_) => break,
                    }
                }
            });
        }

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
                if is_valid_agent_event(event_type, &val) {
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

fn payload_str<'a>(val: &'a Value, key: &str) -> Option<&'a str> {
    val.get("payload")?.get(key)?.as_str()
}

fn is_valid_agent_event(event_type: &str, val: &Value) -> bool {
    if val.get("type").and_then(|t| t.as_str()).is_none() {
        return false;
    }

    match event_type {
        "token" | "thinking_delta" => payload_str(val, "text").is_some(),
        "done" => val.get("payload").map(|p| p.is_object()).unwrap_or(false),
        "error" => payload_str(val, "message").is_some() || payload_str(val, "error").is_some(),
        "tool_call" => payload_str(val, "tool_name").is_some(),
        "tool_result" => payload_str(val, "tool_name").is_some(),
        "tool_progress" => payload_str(val, "tool_name").is_some() && payload_str(val, "status").is_some(),
        "phase" => payload_str(val, "phase").is_some() && payload_str(val, "label").is_some(),
        "artifact_plan" => payload_str(val, "artifact_type").is_some(),
        "artifact_skeleton" => payload_str(val, "artifact_type").is_some(),
        "artifact_update" => payload_str(val, "artifact_type").is_some(),
        "telemetry" => val.get("payload").map(|p| p.is_object()).unwrap_or(false),
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::is_valid_agent_event;
    use serde_json::json;

    #[test]
    fn valid_phase_event_passes() {
        let event = json!({"type":"phase","payload":{"phase":"memory","label":"Loading memory"}});
        assert!(is_valid_agent_event("phase", &event));
    }

    #[test]
    fn malformed_token_is_rejected() {
        let event = json!({"type":"token","payload":{}});
        assert!(!is_valid_agent_event("token", &event));
    }

    #[test]
    fn unknown_type_is_rejected() {
        let event = json!({"type":"unknown","payload":{}});
        assert!(!is_valid_agent_event("unknown", &event));
    }

    #[test]
    fn valid_artifact_skeleton_passes() {
        let event = json!({"type":"artifact_skeleton","payload":{"artifact_type":"dashboard"}});
        assert!(is_valid_agent_event("artifact_skeleton", &event));
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
