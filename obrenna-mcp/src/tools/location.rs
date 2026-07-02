use anyhow::Result;
use serde_json::{json, Value};

pub fn definition() -> Value {
    json!({
        "name": "get_location",
        "description": "Get user location (requires permission approval)",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    })
}

pub async fn execute(_args: &Value) -> Result<Value> {
    // Stub: permission broker integration deferred
    // This will be wired through the Tauri permission broker in Phase 5
    Ok(json!({
        "content": [{
            "type": "text",
            "text": json!({
                "status": "permission_required",
                "message": "Location access requires user permission"
            }).to_string()
        }],
        "isError": false
    }))
}
