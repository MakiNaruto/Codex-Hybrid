//! Serialized private sidecar session, bounded messages and command adapters.
use std::sync::atomic::{AtomicBool, Ordering};
use tauri::Manager;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

#[cfg(any(target_os = "macos", target_os = "windows"))]
use crate::desktop_tray;

pub(crate) struct Session {
    child: CommandChild,
    events: tauri::async_runtime::Receiver<CommandEvent>,
}

#[derive(Default)]
pub(crate) struct Control {
    pub(crate) session: tauri::async_runtime::Mutex<Option<Session>>,
    pub(crate) protected: AtomicBool,
    pub(crate) exit_pending: AtomicBool,
    pub(crate) shutting_down: AtomicBool,
}

// One serialized request/response stream. Secrets travel only over private stdin.
pub(crate) async fn request(
    app: &tauri::AppHandle,
    request: serde_json::Value,
) -> Result<serde_json::Value, String> {
    if !matches!(
        request.get("action").and_then(|v| v.as_str()),
        Some(
            "web_api"
                | "initialize"
                | "save_provider"
                | "test_connection"
                | "snapshot"
                | "status"
                | "preview_routing"
                | "set_routing"
                | "cancel_preview"
                | "recover_forwarding"
                | "shutdown"
                | "shutdown_confirmed"
                | "save_desktop_preferences"
                | "preview_restart"
                | "cancel_restart"
                | "restart_codex"
        )
    ) {
        return Err("无效操作".into());
    }
    let mut input = serde_json::to_vec(&request).map_err(|_| "无效请求")?;
    input.push(b'\n');
    if input.len() > 65536 {
        return Err("配置内容过大".into());
    }
    let control = app.state::<Control>();
    let mut guard = control.session.lock().await;
    if control.shutting_down.load(Ordering::Acquire)
        && !matches!(
            request["action"].as_str(),
            Some("shutdown" | "shutdown_confirmed")
        )
    {
        return Err("正在退出应用".into());
    }
    if guard.is_none() {
        let (events, child) = app
            .shell()
            .sidecar("hybrid-stage0-probe")
            .map_err(|_| "无法启动控制程序")?
            .args(["desktop-controller"])
            .spawn()
            .map_err(|_| "无法启动控制程序")?;
        *guard = Some(Session { child, events });
        control.protected.store(true, Ordering::Release);
    }
    let session = guard.as_mut().unwrap();
    if session.child.write(&input).is_err() {
        *guard = None;
        return Err("控制程序已断开，请刷新检查恢复状态；操作未自动重试".into());
    }
    #[cfg(any(target_os = "macos", target_os = "windows"))]
    let response = receive_bounded(session, request_timeout(&request)).await;
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    let response = receive(session).await;
    #[cfg(any(target_os = "macos", target_os = "windows"))]
    if request["action"] == "status" {
        desktop_tray::update(app, response.as_ref());
    }
    if let Some(response) = response {
        return Ok(response);
    }
    *guard = None; // Closing stdin causes cooperative owner-loss cleanup.
    Err("控制程序异常断开，请刷新检查恢复状态；操作未自动重试".into())
}

async fn receive(session: &mut Session) -> Option<serde_json::Value> {
    while let Some(event) = session.events.recv().await {
        match event {
            CommandEvent::Stdout(bytes) => {
                if bytes.len() > 1048576 {
                    break;
                }
                match serde_json::from_slice::<serde_json::Value>(&bytes) {
                    Ok(response) => return Some(response),
                    Err(_) => break,
                }
            }
            CommandEvent::Terminated(_) | CommandEvent::Error(_) => break,
            _ => {} // Never forward stderr or upstream messages to the frontend.
        }
    }
    None
}

#[cfg(any(target_os = "macos", target_os = "windows"))]
fn request_timeout(request: &serde_json::Value) -> u64 {
    if request["action"] == "web_api" && request["method"] == "POST" {
        return if request["path"] == "test" { 75 } else { 120 };
    }
    match request["action"].as_str() {
        Some("status" | "snapshot" | "web_api" | "shutdown" | "shutdown_confirmed") => 20,
        _ => 120,
    }
}

#[cfg(any(target_os = "macos", target_os = "windows"))]
async fn receive_bounded(session: &mut Session, seconds: u64) -> Option<serde_json::Value> {
    tokio::time::timeout(std::time::Duration::from_secs(seconds), receive(session))
        .await
        .ok()
        .flatten()
}

#[cfg(any(target_os = "macos", target_os = "windows"))]
pub(crate) async fn poll_status(app: &tauri::AppHandle) {
    let control = app.state::<Control>();
    let Ok(mut guard) = control.session.try_lock() else {
        return;
    };
    if control.shutting_down.load(Ordering::Acquire) {
        return;
    }
    let Some(session) = guard.as_mut() else {
        desktop_tray::update(app, None);
        return;
    };
    if session.child.write(b"{\"action\":\"status\"}\n").is_err() {
        *guard = None;
        desktop_tray::update(app, None);
        return;
    }
    let response = receive_bounded(session, 20).await;
    desktop_tray::update(app, response.as_ref());
    if response.is_none() {
        *guard = None;
    }
}

#[tauri::command]
pub(crate) async fn desktop_manage(
    app: tauri::AppHandle,
    request: serde_json::Value,
) -> Result<serde_json::Value, String> {
    // Only the safe-exit command may release the controller and terminate the app.
    if matches!(
        request["action"].as_str(),
        Some("shutdown" | "shutdown_confirmed")
    ) {
        return Err("请使用退出应用操作".into());
    }
    self::request(&app, request).await
}

#[tauri::command]
pub(crate) async fn desktop_snapshot(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    let response = request(&app, serde_json::json!({"action":"snapshot"})).await?;
    if response.get("ok").and_then(|v| v.as_bool()) != Some(true) {
        return Err("无法取得配置，可能已有管理实例；请检查后重试".into());
    }
    Ok(response["result"].clone())
}

#[tauri::command]
pub(crate) async fn probe_report(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    let output = app
        .shell()
        .sidecar("hybrid-stage0-probe")
        .map_err(|_| "无法启动检查程序")?
        .args(["report"])
        .output()
        .await
        .map_err(|_| "检查程序异常")?;
    if !output.status.success() {
        return Err("检查程序异常退出".into());
    }
    serde_json::from_slice(&output.stdout).map_err(|_| "检查结果无效".into())
}

#[cfg(all(test, any(target_os = "macos", target_os = "windows")))]
mod startup_tests {
    use super::*;

    #[test]
    fn initial_reads_and_shutdown_are_bounded_without_shortening_writes() {
        use serde_json::json;
        assert_eq!(
            request_timeout(&json!({"action":"web_api","method":"GET","path":"state"})),
            20
        );
        assert_eq!(request_timeout(&json!({"action":"shutdown"})), 20);
        assert_eq!(
            request_timeout(&json!({"action":"web_api","method":"POST","path":"test"})),
            75
        );
        assert_eq!(request_timeout(&json!({"action":"set_routing"})), 120);
    }
}
