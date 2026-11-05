#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::atomic::{AtomicBool, Ordering};
use tauri::{Emitter, Manager};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

#[cfg(any(target_os = "macos", target_os = "windows"))]
mod desktop_tray;
#[cfg(target_os = "macos")]
mod macos_dialog;
#[cfg(target_os = "windows")]
mod windows_dialog;

struct Session {
    child: CommandChild,
    events: tauri::async_runtime::Receiver<CommandEvent>,
}

#[derive(Default)]
struct Control {
    session: tauri::async_runtime::Mutex<Option<Session>>,
    protected: AtomicBool,
    exit_pending: AtomicBool,
    shutting_down: AtomicBool,
}

// One serialized request/response stream. Secrets travel only over private stdin.
async fn request(
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
async fn poll_status(app: &tauri::AppHandle) {
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
async fn desktop_manage(
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
    crate::request(&app, request).await
}

#[tauri::command]
async fn desktop_snapshot(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    let response = request(&app, serde_json::json!({"action":"snapshot"})).await?;
    if response.get("ok").and_then(|v| v.as_bool()) != Some(true) {
        return Err("无法取得配置，可能已有管理实例；请检查后重试".into());
    }
    Ok(response["result"].clone())
}

#[tauri::command]
async fn desktop_exit(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    let control = app.state::<Control>();
    #[cfg(any(target_os = "macos", target_os = "windows"))]
    if control.session.lock().await.is_none() {
        // No owner exists: startup failed or no request has started. Never spawn
        // a new controller merely to quit a window that could not load.
        control.protected.store(false, Ordering::Release);
        app.exit(0);
        return Ok(serde_json::json!({"ok":true}));
    }
    if control.exit_pending.swap(true, Ordering::AcqRel) {
        return Err("正在退出应用".into());
    }
    control.shutting_down.store(true, Ordering::Release);
    let response = request(&app, serde_json::json!({"action":"shutdown"})).await;
    #[cfg(target_os = "windows")]
    let response = if matches!(&response, Ok(value) if value["error"] == "EXIT_BLOCKED") {
        // Shutdown was declined and the owner is still live. Keep management
        // requests available while the user decides in the native dialog.
        control.shutting_down.store(false, Ordering::Release);
        match windows_dialog::show(
            &app,
            "退出 Codex Hybrid？".into(),
            "混合路由仍开启，网关仍有请求，或无法确认相关状态。退出会停止本应用的网关，正在使用它的请求可能中断。".into(),
            vec!["取消".into(), "仍然退出".into()],
        )
        .await
        {
            Ok(1) => {
                control.shutting_down.store(true, Ordering::Release);
                request(&app, serde_json::json!({"action":"shutdown_confirmed"})).await
            }
            Ok(_) => Ok(serde_json::json!({"ok":false,"cancelled":true})),
            Err(error) => Err(error),
        }
    } else {
        response
    };
    if !matches!(&response, Ok(value) if value["ok"] == true) {
        control.shutting_down.store(false, Ordering::Release);
        control.exit_pending.store(false, Ordering::Release);
    }
    let response = match response {
        Ok(response) => response,
        Err(error) => {
            #[cfg(any(target_os = "macos", target_os = "windows"))]
            if control.session.lock().await.is_none() {
                control.protected.store(false, Ordering::Release);
                app.exit(0);
                return Ok(serde_json::json!({"ok":true}));
            }
            return Err(error);
        }
    };
    if response.get("ok").and_then(|v| v.as_bool()) == Some(true) {
        let control = app.state::<Control>();
        *control.session.lock().await = None;
        control.protected.store(false, Ordering::Release);
        app.exit(0);
    }
    #[cfg(target_os = "macos")]
    if response.get("error").and_then(|v| v.as_str()) == Some("EXIT_BLOCKED") {
        let mut response = response;
        response["restore_preview"] = serde_json::json!(true);
        return Ok(response);
    }
    Ok(response)
}

#[tauri::command]
async fn probe_report(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
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

fn show_main(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        #[cfg(target_os = "windows")]
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn notify_exit_blocked(app: &tauri::AppHandle) {
    show_main(app);
    let _ = app.emit("desktop-exit-requested", ());
}

#[cfg(target_os = "macos")]
fn request_native_exit(app: &tauri::AppHandle) {
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        // Cmd+Q must work before the WebView has registered event listeners.
        // A live routing dependency still uses the shared restoration preview.
        if !matches!(desktop_exit(app.clone()).await, Ok(r) if r["ok"] == true) {
            notify_exit_blocked(&app);
        }
    });
}

#[tauri::command]
async fn desktop_alert(
    app: tauri::AppHandle,
    title: String,
    detail: String,
    buttons: Vec<String>,
) -> Result<usize, String> {
    #[cfg(target_os = "macos")]
    {
        macos_dialog::show(&app, title, detail, buttons).await
    }
    #[cfg(target_os = "windows")]
    {
        windows_dialog::show(&app, title, detail, buttons).await
    }
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    {
        let _ = (app, title, detail, buttons);
        Err("此弹窗仅适用于 macOS".into())
    }
}

fn main() {
    tauri::Builder::default()
        .manage(Control::default())
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            #[cfg(target_os = "macos")]
            {
                use tauri::menu::{Menu, MenuItem};
                // muda's predefined macOS Quit calls NSApplication terminate: directly.
                // Replace that native action so Cmd+Q follows the same guarded flow.
                let app_menu = Menu::default(app.handle())?;
                let application_menu = app_menu.items()?.into_iter().next().unwrap();
                let application_menu = application_menu.as_submenu().unwrap();
                let quit_position = application_menu.items()?.len() - 1;
                application_menu.remove_at(quit_position)?;
                application_menu.append(&MenuItem::with_id(
                    app,
                    "guarded-quit",
                    "退出 Codex Hybrid…",
                    true,
                    Some("CmdOrCtrl+Q"),
                )?)?;
                app.set_menu(app_menu)?;
                app.on_menu_event(|app, event| {
                    if event.id.as_ref() == "guarded-quit" {
                        request_native_exit(app);
                    }
                });
            }
            #[cfg(any(target_os = "macos", target_os = "windows"))]
            desktop_tray::setup(app.handle())?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            probe_report,
            desktop_snapshot,
            desktop_manage,
            desktop_exit,
            desktop_alert
        ])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                #[cfg(any(target_os = "macos", target_os = "windows"))]
                {
                    // The tray is created during setup; hiding preserves drafts and the worker.
                    api.prevent_close();
                    let _ = window.hide();
                }
                #[cfg(not(any(target_os = "macos", target_os = "windows")))]
                if window.state::<Control>().protected.load(Ordering::Acquire) {
                    api.prevent_close();
                    notify_exit_blocked(window.app_handle());
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("Desktop preview failed")
        .run(|app, event| {
            #[cfg(target_os = "macos")]
            if let tauri::RunEvent::Reopen { .. } = &event {
                show_main(app);
            }
            if let tauri::RunEvent::ExitRequested { api, .. } = event {
                if app.state::<Control>().protected.load(Ordering::Acquire) {
                    api.prevent_exit();
                    #[cfg(target_os = "macos")]
                    request_native_exit(app);
                    #[cfg(not(target_os = "macos"))]
                    notify_exit_blocked(app);
                }
            }
        });
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
