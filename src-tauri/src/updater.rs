use serde::Serialize;

#[derive(Serialize)]
pub struct UpdateInfo {
    pub current_version: String,
    pub update_available: bool,
    pub latest_version: Option<String>,
    pub description: Option<String>,
}

#[tauri::command]
pub async fn check_update() -> Result<UpdateInfo, String> {
    let current = env!("CARGO_PKG_VERSION").to_string();
    Ok(UpdateInfo {
        current_version: current,
        update_available: false,
        latest_version: None,
        description: None,
    })
}

#[tauri::command]
pub async fn install_update() -> Result<(), String> {
    Ok(())
}

#[tauri::command]
pub fn get_app_version() -> String {
    env!("CARGO_PKG_VERSION").to_string()
}
