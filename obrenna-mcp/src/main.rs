mod server;
mod tools;

use anyhow::Result;
use serde_json::{json, Value};
use std::io::{self, BufRead, Write};

#[tokio::main]
async fn main() -> Result<()> {
    let stdin = io::stdin();
    let mut stdout = io::stdout();
    let reader = stdin.lock();

    for line in reader.lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }

        let request: Value = serde_json::from_str(&line)?;
        let response = handle_request(&request).await?;
        writeln!(stdout, "{}", serde_json::to_string(&response)?)?;
    }

    Ok(())
}

async fn handle_request(request: &Value) -> Result<Value> {
    let method = request
        .get("method")
        .and_then(|v| v.as_str())
        .unwrap_or("unknown");

    let id = request.get("id").cloned().unwrap_or(Value::Null);

    let result = match method {
        "initialize" => {
            json!({
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {
                        "listChanged": false
                    }
                },
                "serverInfo": {
                    "name": "obrenna-mcp",
                    "version": "0.1.0"
                }
            })
        }
        "tools/list" => {
            json!({
                "tools": [
                    tools::time::definition(),
                    tools::calculator::definition(),
                    tools::web_search::definition(),
                    tools::file_read::definition(),
                    tools::location::definition(),
                ]
            })
        }
        "tools/call" => {
            let name = request
                .get("params")
                .and_then(|p| p.get("name"))
                .and_then(|v| v.as_str())
                .unwrap_or("");

            let arguments = request
                .get("params")
                .and_then(|p| p.get("arguments"))
                .cloned()
                .unwrap_or(Value::Object(serde_json::Map::new()));

            match name {
                "get_time" => tools::time::execute(&arguments).await?,
                "calculator" => tools::calculator::execute(&arguments).await?,
                "web_search" => tools::web_search::execute(&arguments).await?,
                "file_read" => tools::file_read::execute(&arguments).await?,
                "get_location" => tools::location::execute(&arguments).await?,
                _ => json!({
                    "content": [{
                        "type": "text",
                        "text": json!({"error": format!("Unknown tool: {}", name)}).to_string()
                    }],
                    "isError": true
                }),
            }
        }
        _ => json!({
            "error": {
                "code": -32601,
                "message": format!("Method not found: {}", method)
            }
        }),
    };

    Ok(json!({
        "jsonrpc": "2.0",
        "id": id,
        "result": result
    }))
}
