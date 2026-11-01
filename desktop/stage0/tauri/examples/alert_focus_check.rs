//! Manual macOS regression harness, isolated from the management controller.
//! Run with HYBRID_ALERT_CHECK_DIR pointing to an empty temporary directory.
//! Put another app in front, then create `trigger` there. Check `during.json`
//! and cancel the alert. Repeat with the main window visible/hidden/minimized.
//! HYBRID_ALERT_CHECK_WINDOW=hidden|minimized sets the initial window state.
#[cfg(target_os = "macos")]
#[path = "../src/macos_dialog.rs"]
mod macos_dialog;

#[cfg(target_os = "macos")]
fn main() {
    use objc2_app_kit::NSRunningApplication;
    use std::{path::PathBuf, time::Duration};
    use tauri::Manager;

    let directory =
        PathBuf::from(std::env::var_os("HYBRID_ALERT_CHECK_DIR").expect("check directory"));
    assert!(directory.is_dir());
    tauri::Builder::default()
        .setup(move |app| {
            let window = app.get_webview_window("main").unwrap();
            match std::env::var("HYBRID_ALERT_CHECK_WINDOW").as_deref() {
                Ok("hidden") => window.hide()?,
                Ok("minimized") => window.minimize()?,
                _ => (),
            }
            let app = app.handle().clone();
            std::thread::spawn(move || {
                while !directory.join("trigger").exists() {
                    std::thread::sleep(Duration::from_millis(100));
                }
                std::fs::write(
                    directory.join("before.json"),
                    serde_json::json!({
                        "active": NSRunningApplication::currentApplication().isActive(),
                    })
                    .to_string(),
                )
                .unwrap();
                let output = directory.join("during.json");
                std::thread::spawn(move || {
                    std::thread::sleep(Duration::from_secs(2));
                    // Tauri main-thread tasks wait until runModal returns. This
                    // thread-safe API observes activation during the modal loop.
                    let active = NSRunningApplication::currentApplication().isActive();
                    std::fs::write(output, serde_json::json!({"active": active}).to_string())
                        .unwrap();
                });
                let choice = tauri::async_runtime::block_on(macos_dialog::show(
                    &app,
                    "确认框焦点回归检查".into(),
                    "仅测试窗口激活，不切换路由、不操作 Codex。请点击取消。".into(),
                    vec!["取消".into(), "测试确认".into()],
                ));
                let (sender, receiver) = std::sync::mpsc::channel();
                let handle = app.clone();
                app.run_on_main_thread(move || {
                    let window = handle.get_webview_window("main").unwrap();
                    sender
                        .send(serde_json::json!({
                            "main_visible": window.is_visible().unwrap(),
                            "main_minimized": window.is_minimized().unwrap(),
                        }))
                        .unwrap();
                })
                .unwrap();
                std::fs::write(
                    directory.join("after.json"),
                    receiver.recv().unwrap().to_string(),
                )
                .unwrap();
                std::fs::write(directory.join("choice.txt"), format!("{choice:?}")).unwrap();
                app.exit(0);
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .unwrap();
}

#[cfg(not(target_os = "macos"))]
fn main() {
    eprintln!("This native focus check requires macOS.");
}
