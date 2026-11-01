//! macOS-only native tray. API: https://v2.tauri.app/learn/system-tray/
use serde_json::Value;
use std::sync::atomic::{AtomicBool, Ordering};
use tauri::{
    menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem},
    tray::TrayIconBuilder,
    Emitter, Manager,
};

struct TrayItems {
    routing: CheckMenuItem<tauri::Wry>,
    enabled: AtomicBool,
}

fn labels(status: &Value) -> (String, bool) {
    let mode = status["routing"].as_str().unwrap_or("unavailable");
    let forwarding = match status["forwarding"]["status"].as_str() {
        Some("stopped") => "已停止",
        Some("running") => "运行中",
        Some("starting") => "启动中",
        Some("recovering") => "恢复中",
        Some("fault") => "故障",
        _ => "未知",
    };
    let routing = match mode {
        "project" => "已接入",
        "openai" => "原生",
        _ => "未准备或未知",
    };
    (
        format!("接入：{routing} · 网关：{forwarding}"),
        mode == "project",
    )
}

pub fn update(app: &tauri::AppHandle, response: Option<&Value>) {
    let Some(items) = app.try_state::<TrayItems>() else {
        return;
    };
    let (status, enabled) = match response.filter(|r| r["ok"] == true) {
        Some(r) => labels(&r["result"]),
        None => ("状态不可用，请打开窗口检查".into(), false),
    };
    let _ = items.routing.set_enabled(response.is_some_and(|r| {
        r["ok"] == true && matches!(r["result"]["routing"].as_str(), Some("project" | "openai"))
    }));
    items.enabled.store(enabled, Ordering::Release);
    let _ = items.routing.set_checked(enabled);
    if let Some(tray) = app.tray_by_id("hybrid") {
        let _ = tray.set_tooltip(Some(format!("Codex Hybrid · {status}")));
    }
}

pub fn setup(app: &tauri::AppHandle) -> tauri::Result<()> {
    let open = MenuItem::with_id(app, "open", "管理", true, None::<&str>)?;
    let routing = CheckMenuItem::with_id(app, "routing", "混合路由", false, false, None::<&str>)?;
    let restart = MenuItem::with_id(app, "restart-codex", "重启 Codex…", true, None::<&str>)?;
    let exit = MenuItem::with_id(app, "safe-exit", "退出…", true, None::<&str>)?;
    let separator = PredefinedMenuItem::separator(app)?;
    let exit_separator = PredefinedMenuItem::separator(app)?;
    let menu = Menu::with_items(
        app,
        &[
            &open,
            &separator,
            &routing,
            &restart,
            &exit_separator,
            &exit,
        ],
    )?;
    app.manage(TrayItems {
        routing,
        enabled: AtomicBool::new(false),
    });
    TrayIconBuilder::with_id("hybrid")
        .icon(tauri::include_image!("icons/tray.png"))
        .icon_as_template(true)
        .tooltip("Codex Hybrid")
        .menu(&menu)
        .on_menu_event(|app, event| {
            // Tauri sends application-menu events here too.
            if !matches!(
                event.id.as_ref(),
                "open" | "routing" | "restart-codex" | "safe-exit"
            ) {
                return;
            }
            if event.id.as_ref() == "routing" {
                // Native check items toggle on click. Keep the actual state until
                // the existing preview/confirmation flow completes successfully.
                if let Some(items) = app.try_state::<TrayItems>() {
                    let _ = items
                        .routing
                        .set_checked(items.enabled.load(Ordering::Acquire));
                }
            }
            // Routing and restart use standalone native dialogs, even when hidden.
            if matches!(event.id.as_ref(), "open" | "safe-exit") {
                crate::show_main(app);
            }
            let name = match event.id.as_ref() {
                "routing" => Some("desktop-routing-requested"),
                "restart-codex" => Some("desktop-restart-requested"),
                "safe-exit" => Some("desktop-exit-requested"),
                _ => None,
            };
            if let Some(name) = name {
                let _ = app.emit(name, serde_json::json!({"native_confirmation":true}));
            }
        })
        .build(app)?;
    // Native polling continues while WKWebView is hidden. One sequential reader;
    // it never queues multiple polls behind a long request or starts a new session.
    let app = app.clone();
    std::thread::spawn(move || loop {
        std::thread::sleep(std::time::Duration::from_secs(5));
        tauri::async_runtime::block_on(crate::poll_status(&app));
    });
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn tray_distinguishes_routing_from_gateway() {
        let (status, action) =
            labels(&json!({"routing":"openai","forwarding":{"status":"running"}}));
        assert_eq!(status, "接入：原生 · 网关：运行中");
        assert!(!action);
        let (status, action) =
            labels(&json!({"routing":"project","forwarding":{"status":"fault"}}));
        assert_eq!(status, "接入：已接入 · 网关：故障");
        assert!(action);
    }
    #[test]
    fn missing_status_never_claims_connection() {
        assert_eq!(
            labels(&Value::Null),
            ("接入：未准备或未知 · 网关：未知".into(), false)
        );
    }
}
