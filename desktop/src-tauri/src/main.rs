#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

#[cfg(any(target_os = "macos", target_os = "windows"))]
mod desktop_tray;
mod ipc;
mod lifecycle;
#[cfg(target_os = "macos")]
mod macos_dialog;
#[cfg(target_os = "windows")]
mod windows_dialog;

fn main() {
    tauri::Builder::default()
        .manage(ipc::Control::default())
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            #[cfg(target_os = "macos")]
            lifecycle::setup_menu(app)?;
            #[cfg(any(target_os = "macos", target_os = "windows"))]
            desktop_tray::setup(app.handle())?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            ipc::probe_report,
            ipc::desktop_snapshot,
            ipc::desktop_manage,
            lifecycle::desktop_exit,
            lifecycle::desktop_alert
        ])
        .on_window_event(lifecycle::on_window_event)
        .build(tauri::generate_context!())
        .expect("Desktop preview failed")
        .run(lifecycle::on_run_event);
}

#[cfg(test)]
mod registration_tests {
    #[test]
    fn fixed_commands_remain_registered_after_module_split() {
        let source = include_str!("main.rs");
        let handlers = source
            .split_once(".invoke_handler(tauri::generate_handler![")
            .unwrap()
            .1
            .split_once("])")
            .unwrap()
            .0;
        let commands: Vec<_> = handlers.split(',').map(str::trim).collect();
        assert_eq!(
            commands,
            [
                "ipc::probe_report",
                "ipc::desktop_snapshot",
                "ipc::desktop_manage",
                "lifecycle::desktop_exit",
                "lifecycle::desktop_alert",
            ]
        );
    }
}
