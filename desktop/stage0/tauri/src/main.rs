#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::atomic::{AtomicBool, Ordering};
use tauri::{Emitter, Manager};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

#[cfg(target_os = "macos")]
mod macos_tray;

struct Session {
    child: CommandChild,
    events: tauri::async_runtime::Receiver<CommandEvent>,
}

#[derive(Default)]
struct Control {
    session: tauri::async_runtime::Mutex<Option<Session>>,
    protected: AtomicBool,
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
    if control.shutting_down.load(Ordering::Acquire) && request["action"] != "shutdown" {
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
    let response = receive(session).await;
    #[cfg(target_os = "macos")]
    if request["action"] == "status" {
        macos_tray::update(app, response.as_ref());
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

#[cfg(target_os = "macos")]
async fn poll_status(app: &tauri::AppHandle) {
    let control = app.state::<Control>();
    let Ok(mut guard) = control.session.try_lock() else {
        return;
    };
    if control.shutting_down.load(Ordering::Acquire) {
        return;
    }
    let Some(session) = guard.as_mut() else {
        macos_tray::update(app, None);
        return;
    };
    if session.child.write(b"{\"action\":\"status\"}\n").is_err() {
        *guard = None;
        macos_tray::update(app, None);
        return;
    }
    let response = receive(session).await;
    macos_tray::update(app, response.as_ref());
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
    if request.get("action").and_then(|v| v.as_str()) == Some("shutdown") {
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
    if control.shutting_down.swap(true, Ordering::AcqRel) {
        return Err("正在退出应用".into());
    }
    let response = request(&app, serde_json::json!({"action":"shutdown"})).await;
    if !matches!(&response, Ok(value) if value["ok"] == true) {
        control.shutting_down.store(false, Ordering::Release);
    }
    let response = response?;
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
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn notify_exit_blocked(app: &tauri::AppHandle) {
    show_main(app);
    let _ = app.emit("desktop-exit-requested", ());
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
                        notify_exit_blocked(app);
                    }
                });
                macos_tray::setup(app.handle())?;
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            probe_report,
            desktop_snapshot,
            desktop_manage,
            desktop_exit
        ])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                #[cfg(target_os = "macos")]
                {
                    // The tray is created during setup; hiding preserves drafts and the worker.
                    api.prevent_close();
                    let _ = window.hide();
                }
                #[cfg(not(target_os = "macos"))]
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
                    notify_exit_blocked(app);
                }
            }
        });
}
