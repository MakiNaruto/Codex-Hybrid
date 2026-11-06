//! Window visibility, native exit confirmation and controller ownership release.
use std::sync::atomic::Ordering;
use tauri::{Emitter, Manager};

use crate::ipc::{request, Control};
#[cfg(target_os = "macos")]
use crate::macos_dialog;
#[cfg(target_os = "windows")]
use crate::windows_dialog;

#[tauri::command]
pub(crate) async fn desktop_exit(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
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

pub(crate) fn show_main(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        #[cfg(target_os = "windows")]
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

#[cfg(not(target_os = "windows"))]
fn notify_exit_blocked(app: &tauri::AppHandle) {
    show_main(app);
    let _ = app.emit("desktop-exit-requested", ());
}

#[cfg(target_os = "windows")]
pub(crate) fn request_windows_exit(app: &tauri::AppHandle) {
    let _ = app.emit(
        "desktop-exit-requested",
        serde_json::json!({"native_confirmation": true}),
    );
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
pub(crate) async fn desktop_alert(
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

#[cfg(target_os = "macos")]
pub(crate) fn setup_menu(app: &mut tauri::App) -> tauri::Result<()> {
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
    Ok(())
}

pub(crate) fn on_window_event(window: &tauri::Window, event: &tauri::WindowEvent) {
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
}

pub(crate) fn on_run_event(app: &tauri::AppHandle, event: tauri::RunEvent) {
    #[cfg(target_os = "macos")]
    if let tauri::RunEvent::Reopen { .. } = &event {
        show_main(app);
    }
    if let tauri::RunEvent::ExitRequested { api, .. } = event {
        if app.state::<Control>().protected.load(Ordering::Acquire) {
            api.prevent_exit();
            #[cfg(target_os = "macos")]
            request_native_exit(app);
            #[cfg(target_os = "windows")]
            request_windows_exit(app);
            #[cfg(not(any(target_os = "macos", target_os = "windows")))]
            notify_exit_blocked(app);
        }
    }
}
