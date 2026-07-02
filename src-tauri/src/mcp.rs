// MCP server process supervisor and stdio proxy.
//
// Rust owns the MCP server process and its pipes. Python sends MCP JSON-RPC
// frames to Rust over a loopback TCP proxy channel. Rust relays them to the
// server stdio and relays responses back.

use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::io::{BufRead, BufReader, Write};

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
///
/// The MCP child's stdin/stdout are shared (behind mutexes) across every TCP
/// connection: Python opens a fresh ``MCPClient``/socket per chat turn
/// (see ``mcp/client.py::create_mcp_client`` called from
/// ``orchestrate_turn``), so the listener must ``accept()`` in a loop rather
/// than serve exactly one connection.
pub struct McpProxy {
    server_process: Arc<Mutex<Option<Child>>>,
    child_stdin: Arc<Mutex<Option<std::process::ChildStdin>>>,
    child_stdout: Arc<Mutex<Option<BufReader<std::process::ChildStdout>>>>,
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
            child_stdin: Arc::new(Mutex::new(None)),
            child_stdout: Arc::new(Mutex::new(None)),
            tcp_listener: Arc::new(Mutex::new(Some(listener))),
            tcp_port: port,
        })
    }

    /// Get the loopback URL for Python to connect to.
    pub fn proxy_url(&self) -> String {
        format!("tcp://127.0.0.1:{}", self.tcp_port)
    }

    /// Spawn the MCP server process.
    ///
    /// ``file_allowlist`` is passed as ``OBRENNA_FILE_ALLOWLIST`` (platform
    /// path-list syntax, e.g. ``;``-joined on Windows) so the server's
    /// ``file_read`` tool has a scoped set of readable roots. An empty or
    /// absent allowlist makes the tool deny every read (default-deny).
    /// Returns the URL that Python should use to connect.
    pub fn spawn_server(
        &self,
        server_path: &std::path::PathBuf,
        file_allowlist: &str,
    ) -> Result<String, String> {
        let mut cmd = Command::new(server_path);
        cmd.stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .env("OBRENNA_FILE_ALLOWLIST", file_allowlist);

        let mut child = cmd.spawn().map_err(|e| format!("Failed to spawn MCP server: {}", e))?;

        let stdin = child.stdin.take();
        let stdout = child.stdout.take();
        let stderr = child.stderr.take();

        // Drain stderr on a dedicated thread so the pipe never fills and
        // blocks the child's write() — a filled pipe buffer (~64KB) would
        // otherwise freeze the MCP server process indefinitely.
        if let Some(err) = stderr {
            std::thread::spawn(move || {
                let reader = BufReader::new(err);
                for line in reader.lines() {
                    match line {
                        Ok(l) => eprintln!("[obrenna-mcp] {}", l),
                        Err(_) => break,
                    }
                }
            });
        }

        *self.child_stdin.lock().unwrap() = stdin;
        *self.child_stdout.lock().unwrap() = stdout.map(BufReader::new);

        {
            let mut proc_opt = self.server_process.lock().unwrap();
            *proc_opt = Some(child);
        }

        Ok(self.proxy_url())
    }

    /// Start the TCP relay between Python clients and the MCP server stdio.
    ///
    /// Accepts connections in a loop (one at a time — the MCP child's stdio
    /// is a single shared pipe pair) and pumps each connection with two
    /// independent line-buffered threads instead of a fixed-size ping-pong
    /// read/write, so responses larger than one buffer are never truncated
    /// or desynced.
    pub fn start_proxy(&self) -> Result<(), String> {
        let listener = self.tcp_listener.lock().unwrap().take()
            .ok_or_else(|| "TCP listener already taken".to_string())?;

        let child_stdin = Arc::clone(&self.child_stdin);
        let child_stdout = Arc::clone(&self.child_stdout);

        std::thread::spawn(move || {
            for conn in listener.incoming() {
                let tcp_stream = match conn {
                    Ok(s) => s,
                    Err(_) => continue,
                };
                tcp_stream.set_nonblocking(false).ok();

                let tcp_r = match tcp_stream.try_clone() {
                    Ok(s) => s,
                    Err(_) => continue,
                };
                let tcp_w = tcp_stream;

                // TCP -> child stdin (client requests)
                let stdin_handle = Arc::clone(&child_stdin);
                let reader_thread = std::thread::spawn(move || {
                    let mut buf_reader = BufReader::new(tcp_r);
                    loop {
                        let mut line = String::new();
                        match buf_reader.read_line(&mut line) {
                            Ok(0) => break,
                            Ok(_) => {
                                let mut stdin_opt = stdin_handle.lock().unwrap();
                                if let Some(ref mut stdin) = *stdin_opt {
                                    if stdin.write_all(line.as_bytes()).is_err() {
                                        break;
                                    }
                                    let _ = stdin.flush();
                                } else {
                                    break;
                                }
                            }
                            Err(_) => break,
                        }
                    }
                });

                // child stdout -> TCP (server responses)
                let stdout_handle = Arc::clone(&child_stdout);
                let mut tcp_w2 = match tcp_w.try_clone() {
                    Ok(w) => w,
                    Err(_) => continue,
                };
                let writer_thread = std::thread::spawn(move || {
                    loop {
                        let mut line = String::new();
                        let read_result = {
                            let mut stdout_opt = stdout_handle.lock().unwrap();
                            match *stdout_opt {
                                Some(ref mut stdout) => stdout.read_line(&mut line),
                                None => break,
                            }
                        };
                        match read_result {
                            Ok(0) => break,
                            Ok(_) => {
                                if tcp_w2.write_all(line.as_bytes()).is_err() {
                                    break;
                                }
                                let _ = tcp_w2.flush();
                            }
                            Err(_) => break,
                        }
                    }
                });

                // Serve one connection fully before accepting the next —
                // the child's stdio is a single shared pipe pair, so
                // concurrent connections would interleave JSON-RPC frames.
                let _ = reader_thread.join();
                let _ = writer_thread.join();
            }
        });

        Ok(())
    }

    /// Terminate the MCP server process.
    pub fn stop(&self) -> Result<(), String> {
        *self.child_stdin.lock().unwrap() = None;
        *self.child_stdout.lock().unwrap() = None;
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
