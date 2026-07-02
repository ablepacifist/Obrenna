use anyhow::Result;
use chrono::Local;
use serde_json::{json, Value};

pub fn definition() -> Value {
    json!({
        "name": "get_time",
        "description": "Return the current local system date and time, including year, ISO date/datetime, weekday, timezone, and timezone offset.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    })
}

pub async fn execute(_args: &Value) -> Result<Value> {
    let now = Local::now();
    let utc_offset = now.format("%z").to_string();
    let utc_offset_iso = if utc_offset.len() == 5 {
        format!("{}:{}", &utc_offset[..3], &utc_offset[3..])
    } else {
        utc_offset.clone()
    };
    let iso_datetime = now.to_rfc3339();
    let result = json!({
        "time": iso_datetime,
        "timezone_offset": utc_offset,
        "unix_timestamp": now.timestamp(),
        "iso_datetime": iso_datetime,
        "human_readable": now.format("%A, %B %d, %Y at %I:%M %p").to_string(),
        "date": now.format("%Y-%m-%d").to_string(),
        "local_time": now.format("%H:%M:%S").to_string(),
        "weekday": now.format("%A").to_string(),
        "year": now.format("%Y").to_string().parse::<i32>().unwrap_or(0),
        "timezone": "Local",
        "utc_offset": utc_offset_iso,
    });

    Ok(json!({
        "content": [{
            "type": "text",
            "text": result.to_string()
        }],
        "isError": false
    }))
}
