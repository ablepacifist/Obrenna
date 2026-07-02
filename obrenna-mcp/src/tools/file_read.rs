use anyhow::{anyhow, Result};
use serde_json::{json, Value};
use std::path::PathBuf;

const MAX_FILE_SIZE: usize = 1024 * 1024; // 1MB limit

pub fn definition() -> Value {
    json!({
        "name": "file_read",
        "description": "Read file contents by path (with allowlist enforcement)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute file path to read"
                }
            },
            "required": ["path"]
        }
    })
}

pub async fn execute(args: &Value) -> Result<Value> {
    let path_str = args
        .get("path")
        .and_then(|v| v.as_str())
        .ok_or_else(|| anyhow!("Missing or invalid 'path' parameter"))?;

    match read_file(path_str).await {
        Ok(content) => Ok(json!({
            "content": [{
                "type": "text",
                "text": json!({
                    "path": path_str,
                    "content": content,
                    "size": content.len()
                }).to_string()
            }],
            "isError": false
        })),
        Err(e) => Ok(json!({
            "content": [{
                "type": "text",
                "text": json!({ "error": e.to_string() }).to_string()
            }],
            "isError": true
        })),
    }
}

async fn read_file(path_str: &str) -> Result<String> {
    let path = PathBuf::from(path_str);

    // Ensure absolute path
    if !path.is_absolute() {
        return Err(anyhow!("Path must be absolute"));
    }

    // Check file exists and is a file BEFORE canonicalizing (canonicalize
    // fails on a nonexistent path), so allowlist enforcement below always
    // runs against a symlink-resolved real path.
    if !path.exists() {
        return Err(anyhow!("File not found"));
    }

    if !path.is_file() {
        return Err(anyhow!("Path is not a file"));
    }

    let canonical = tokio::fs::canonicalize(&path)
        .await
        .map_err(|e| anyhow!("Failed to resolve path: {}", e))?;

    // Default-deny: an unset or empty allowlist means NO paths are readable.
    // ``std::env::split_paths`` uses the platform path-list separator
    // (';' on Windows, ':' on Unix) — a plain ':' split would break on
    // Windows drive letters like "C:\...".
    let allowlist_raw = std::env::var("OBRENNA_FILE_ALLOWLIST").unwrap_or_default();
    let allowed_roots: Vec<PathBuf> = std::env::split_paths(&allowlist_raw)
        .filter(|p| !p.as_os_str().is_empty())
        .collect();

    if allowed_roots.is_empty() {
        return Err(anyhow!("Path not in allowlist"));
    }

    let mut allowed = false;
    for root in &allowed_roots {
        let canonical_root = match tokio::fs::canonicalize(root).await {
            Ok(r) => r,
            Err(_) => continue, // allowlisted root doesn't exist — skip, don't grant
        };
        if canonical.starts_with(&canonical_root) {
            allowed = true;
            break;
        }
    }

    if !allowed {
        return Err(anyhow!("Path not in allowlist"));
    }

    // Check file size
    let metadata = tokio::fs::metadata(&canonical).await?;
    if metadata.len() as usize > MAX_FILE_SIZE {
        return Err(anyhow!(
            "File too large: {} bytes (limit: {})",
            metadata.len(),
            MAX_FILE_SIZE
        ));
    }

    // Read file
    let content = tokio::fs::read_to_string(&canonical).await?;
    Ok(content)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use std::sync::Mutex;

    // std::env::set_var/remove_var mutate global process state; cargo test
    // runs test fns concurrently by default, so every test in this module
    // that touches OBRENNA_FILE_ALLOWLIST must hold this lock for its
    // duration or they race and flake.
    static ENV_LOCK: Mutex<()> = Mutex::new(());

    #[tokio::test]
    async fn denies_when_allowlist_unset() {
        let _guard = ENV_LOCK.lock().unwrap();
        std::env::remove_var("OBRENNA_FILE_ALLOWLIST");
        let dir = std::env::temp_dir();
        let file_path = dir.join("obrenna_test_deny_unset.txt");
        std::fs::File::create(&file_path).unwrap().write_all(b"secret").unwrap();

        let result = read_file(file_path.to_str().unwrap()).await;

        std::fs::remove_file(&file_path).ok();
        assert!(result.is_err(), "must deny when OBRENNA_FILE_ALLOWLIST is unset");
    }

    #[tokio::test]
    async fn denies_when_allowlist_empty() {
        let _guard = ENV_LOCK.lock().unwrap();
        std::env::set_var("OBRENNA_FILE_ALLOWLIST", "");
        let dir = std::env::temp_dir();
        let file_path = dir.join("obrenna_test_deny_empty.txt");
        std::fs::File::create(&file_path).unwrap().write_all(b"secret").unwrap();

        let result = read_file(file_path.to_str().unwrap()).await;

        std::env::remove_var("OBRENNA_FILE_ALLOWLIST");
        std::fs::remove_file(&file_path).ok();
        assert!(result.is_err(), "must deny when OBRENNA_FILE_ALLOWLIST is empty");
    }

    #[tokio::test]
    async fn denies_path_outside_allowlisted_root() {
        let _guard = ENV_LOCK.lock().unwrap();
        let allowed_dir = std::env::temp_dir().join("obrenna_test_allowed_root");
        std::fs::create_dir_all(&allowed_dir).unwrap();
        std::env::set_var("OBRENNA_FILE_ALLOWLIST", allowed_dir.to_str().unwrap());

        let outside_dir = std::env::temp_dir().join("obrenna_test_outside_root");
        std::fs::create_dir_all(&outside_dir).unwrap();
        let file_path = outside_dir.join("secret.txt");
        std::fs::File::create(&file_path).unwrap().write_all(b"secret").unwrap();

        let result = read_file(file_path.to_str().unwrap()).await;

        std::env::remove_var("OBRENNA_FILE_ALLOWLIST");
        std::fs::remove_file(&file_path).ok();
        std::fs::remove_dir_all(&outside_dir).ok();
        std::fs::remove_dir_all(&allowed_dir).ok();
        assert!(result.is_err(), "must deny paths outside every allowlisted root");
    }

    #[tokio::test]
    async fn allows_path_inside_allowlisted_root() {
        let _guard = ENV_LOCK.lock().unwrap();
        let allowed_dir = std::env::temp_dir().join("obrenna_test_allowed_root2");
        std::fs::create_dir_all(&allowed_dir).unwrap();
        std::env::set_var("OBRENNA_FILE_ALLOWLIST", allowed_dir.to_str().unwrap());

        let file_path = allowed_dir.join("ok.txt");
        std::fs::File::create(&file_path).unwrap().write_all(b"hello").unwrap();

        let result = read_file(file_path.to_str().unwrap()).await;

        std::env::remove_var("OBRENNA_FILE_ALLOWLIST");
        std::fs::remove_file(&file_path).ok();
        std::fs::remove_dir_all(&allowed_dir).ok();
        assert_eq!(result.unwrap(), "hello");
    }
}
