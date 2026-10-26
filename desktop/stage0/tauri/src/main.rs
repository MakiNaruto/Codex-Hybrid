#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri_plugin_shell::ShellExt;

// Probe-only command: fixed arguments, no arbitrary program/path supplied by the frontend.
#[tauri::command]
async fn probe_report(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    let output = app
        .shell()
        .sidecar("hybrid-stage0-probe")
        .map_err(|error| error.to_string())?
        .args(["report"])
        .output()
        .await
        .map_err(|error| error.to_string())?;
    if !output.status.success() {
        return Err("Stage0 sidecar exited unsuccessfully".into());
    }
    serde_json::from_slice(&output.stdout).map_err(|error| error.to_string())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![probe_report])
        .run(tauri::generate_context!())
        .expect("Stage0 desktop shell failed");
}
