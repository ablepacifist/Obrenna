// MCP server process supervisor and stdio proxy.
//
// Rust owns the MCP server process and its pipes. Python sends MCP JSON-RPC
// frames to Rust over a loopback TCP proxy channel. Rust relays them to the
// server stdio and relays responses back.

use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::io::{Read, Write};

use serde::{Deserialize, Serialize};

/// MCP JSON-RPC request/response types.
#[derive(Debug, Deserialize, Serialize)]
pub struct McpRequest {
    pub id: Option<u64>,
    #[serde(rename = "method")]
    pub method: String,
    #[serde(default)]
    pub params: serde_json::Value,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct McpResponse {
    pub id: Option<u64>,
    #[serde(default)]
    pub result: Option<serde_json::Value>,
    #[serde(default)]
    pub error: Option<McpError>,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct McpError {
    pub code: i32,
    pub message: String,
}

/// State for the MCP server process and its proxy.
pub struct McpProxy {
    server_process: Arc<Mutex<Option<Child>>>,
    tcp_listener: Arc<Mutex<Option<std::net::TcpListener>>>,
    tcp_port: u16,
}

impl McpProxy {
    /// Create a new MCP proxy and bind to a free TCP port.
    pub fn new() -> Result<Self, String> {
        let listener = std::net::TcpListener::bind("127.0.0.1:0")
            .map_err(|e| format!("Failed to bind MCP proxy TCP port: {}", e))?;
        let port = listener.local_addr()
            .map_err(|e| format!("Failed to get TCP port: {}", e))?
            .port();

        Ok(McpProxy {
            server_process: Arc::new(Mutex::new(None)),
            tcp_listener: Arc::new(Mutex::new(Some(listener))),
            tcp_port: port,
        })
    }

    /// Get the loopback URL for Python to connect to.
    pub fn proxy_url(&self) -> String {
        format!("tcp://127.0.0.1:{}", self.tcp_port)
    }

    /// Spawn the MCP server process.
    /// Returns the URL that Python should use to connect.
    pub fn spawn_server(&self, server_path: &std::path::PathBuf) -> Result<String, String> {
        let mut cmd = Command::new(server_path);
        cmd.stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        let child = cmd.spawn().map_err(|e| format!("Failed to spawn MCP server: {}", e))?;

        {
            let mut proc_opt = self.server_process.lock().unwrap();
            *proc_opt = Some(child);
        }

        Ok(self.proxy_url())
    }

    /// Start the async TCP relay between Python client and MCP server stdio.
    pub fn start_proxy(&self) -> Result<(), String> {
        let listener = self.tcp_listener.lock().unwrap().take()
            .ok_or_else(|| "TCP listener already taken".to_string())?;

        let server_process = Arc::clone(&self.server_process);

        std::thread::spawn(move || {
            if let Ok((tcp_stream, _)) = listener.accept() {
                tcp_stream.set_nonblocking(false).ok();

                let mut proc_opt = server_process.lock().unwrap();
                if let Some(ref mut child) = *proc_opt {
                    if let (Some(mut child_stdin), Some(mut child_stdout)) = (
                        child.stdin.take(),
                        child.stdout.take(),
                    ) {
                        drop(proc_opt);

                        let mut tcp_w = tcp_stream.try_clone().ok();
                        let mut tcp_r = tcp_stream;

                        let mut buf = [0; 4096];
                        loop {
                            match tcp_r.read(&mut buf) {
                                Ok(0) => break,
                                Ok(n) => {
                                    if child_stdin.write_all(&buf[..n]).is_err() {
                                        break;
                                    }
                                    let _ = child_stdin.flush();
                                }
                                Err(_) => break,
                            }

                            match child_stdout.read(&mut buf) {
                                Ok(0) => break,
                                Ok(n) => {
                                    if let Some(ref mut w) = tcp_w {
                                        if w.write_all(&buf[..n]).is_err() {
                                            break;
                                        }
                                        let _ = w.flush();
                                    }
                                }
                                Err(_) => break,
                            }
                        }
                    }
                }
            }
        });

        Ok(())
    }

    /// Terminate the MCP server process.
    pub fn stop(&self) -> Result<(), String> {
        let mut proc_opt = self.server_process.lock().unwrap();
        if let Some(mut child) = proc_opt.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
        Ok(())
    }
}

/// Permission broker state for sensitive MCP tools.
/// Location permission is the first capability.
#[derive(Debug, Clone)]
pub struct PermissionBroker {
    decisions: Arc<Mutex<std::collections::HashMap<String, PermissionDecision>>>,
}

#[derive(Debug, Clone, PartialEq)]
pub enum PermissionDecision {
    Granted,
    Denied,
    PromptShown,
}

impl PermissionBroker {
    pub fn new() -> Self {
        PermissionBroker {
            decisions: Arc::new(Mutex::new(std::collections::HashMap::new())),
        }
    }

    /// Check permission for a capability.
    /// Returns the cached decision or "PromptShown" if no decision exists.
    pub fn check(&self, capability: &str) -> PermissionDecision {
        let decisions = self.decisions.lock().unwrap();
        decisions.get(capability).cloned().unwrap_or(PermissionDecision::PromptShown)
    }

    /// Record a permission decision.
    pub fn record(&self, capability: &str, decision: PermissionDecision) {
        let mut decisions = self.decisions.lock().unwrap();
        decisions.insert(capability.to_string(), decision);
    }
}
