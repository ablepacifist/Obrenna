// MCP server process supervisor and stdio proxy.
//
// Rust owns the MCP server process and its pipes. Python sends MCP JSON-RPC
// frames to Rust over a loopback TCP proxy channel. Rust relays them to the
// server stdio and relays responses back.

use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex, mpsc};
use std::net::TcpListener;

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
    server_process: Mutex<Option<Child>>,
    tcp_port: u16,
    shutdown_tx: Mutex<Option<mpsc::Sender<()>>>,
}

impl McpProxy {
    /// Start the MCP server process and begin proxying.
    pub fn new() -> Self {
        let listener = TcpListener::bind("127.0.0.1:0")
            .expect("Failed to bind MCP proxy TCP port");
        let port = listener.local_addr().unwrap().port();
        drop(listener);

        McpProxy {
            server_process: Mutex::new(None),
            tcp_port: port,
            shutdown_tx: Mutex::new(None),
        }
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
            .stderr(Stdio::piped())
            .env("OBRENNA_MCP_PROXY_PORT", self.tcp_port.to_string());

        let child = cmd.spawn().map_err(|e| format!("Failed to spawn MCP server: {}", e))?;

        {
            let mut proc_opt = self.server_process.lock().unwrap();
            *proc_opt = Some(child);
        }

        Ok(self.proxy_url())
    }

    /// Start the TCP listener and relay loop. Runs asynchronously.
    /// Phase 1: Returns Ok but the relay is a stub. Full relay implementation
    /// will be added in a follow-up pass when the MCP server binary exists.
    pub fn start_proxy(&self) -> Result<(), String> {
        let _listener = TcpListener::bind(format!("127.0.0.1:{}", self.tcp_port))
            .map_err(|e| format!("Failed to bind MCP proxy listener: {}", e))?;

        // Phase 1 stub: TCP port is bound and available.
        // The full async relay between TCP and MCP server stdio will be implemented
        // when the MCP server binary is ready.
        let _ = _listener;

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
