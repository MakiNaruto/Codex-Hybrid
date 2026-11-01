//! AppKit alerts run on the main thread; controller requests stay asynchronous.
use objc2::MainThreadMarker;
use objc2_app_kit::{NSAlert, NSAlertFirstButtonReturn, NSAlertStyle};
use objc2_foundation::NSString;

pub async fn show(
    app: &tauri::AppHandle,
    title: String,
    detail: String,
    buttons: Vec<String>,
) -> Result<usize, String> {
    if title.len() > 256
        || detail.len() > 16384
        || buttons.is_empty()
        || buttons.len() > 3
        || buttons.iter().any(|b| b.len() > 128)
    {
        return Err("无效弹窗内容".into());
    }
    let (sender, mut receiver) = tauri::async_runtime::channel(1);
    app.run_on_main_thread(move || {
        let mtm = MainThreadMarker::new().expect("AppKit requires the main thread");
        let alert = NSAlert::new(mtm);
        alert.setMessageText(&NSString::from_str(&title));
        alert.setInformativeText(&NSString::from_str(&detail));
        alert.setAlertStyle(NSAlertStyle::Informational);
        for (index, title) in buttons.iter().enumerate() {
            let button = alert.addButtonWithTitle(&NSString::from_str(title));
            // Return/Escape cancel by default; restarting always needs an explicit choice.
            if index == 0 && buttons.len() > 1 {
                button.setKeyEquivalent(&NSString::from_str("\u{1b}"));
            }
        }
        let response = alert.runModal() - NSAlertFirstButtonReturn;
        let choice = usize::try_from(response)
            .ok()
            .filter(|i| *i < buttons.len())
            .unwrap_or(0);
        let _ = sender.try_send(choice);
    })
    .map_err(|_| "无法显示系统弹窗")?;
    receiver.recv().await.ok_or_else(|| "系统弹窗已关闭".into())
}
