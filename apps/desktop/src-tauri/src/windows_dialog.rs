//! Windows native confirmations; never reveal the hidden management window.
use windows_sys::Win32::{
    Foundation::HWND,
    UI::{
        Controls::{
            TaskDialogIndirect, TASKDIALOGCONFIG, TASKDIALOG_BUTTON, TDF_ALLOW_DIALOG_CANCELLATION,
            TDN_CREATED,
        },
        WindowsAndMessaging::SetForegroundWindow,
    },
};

fn wide(text: &str) -> Vec<u16> {
    text.encode_utf16().chain(Some(0)).collect()
}

fn choice_index(selected: i32, count: usize) -> usize {
    selected
        .checked_sub(100)
        .and_then(|id| usize::try_from(id).ok())
        .filter(|i| *i < count)
        .unwrap_or(0)
}

unsafe extern "system" fn activate(
    window: HWND,
    notification: u32,
    _: usize,
    _: isize,
    _: isize,
) -> i32 {
    if notification == TDN_CREATED as u32 {
        // An explicit tray action may finish its asynchronous preview in the background.
        unsafe { SetForegroundWindow(window) };
    }
    0
}

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
        || title.contains('\0')
        || detail.contains('\0')
        || buttons.iter().any(|b| b.len() > 128 || b.contains('\0'))
    {
        return Err("无效弹窗内容".into());
    }
    let (sender, mut receiver) = tauri::async_runtime::channel(1);
    app.run_on_main_thread(move || {
        let title = wide(&title);
        let detail = wide(&detail);
        let labels: Vec<_> = buttons.iter().map(|b| wide(b)).collect();
        // Avoid Windows' reserved common-button IDs (including IDCANCEL = 2).
        let buttons: Vec<_> = labels
            .iter()
            .enumerate()
            .map(|(i, label)| TASKDIALOG_BUTTON {
                nButtonID: 100 + i as i32,
                pszButtonText: label.as_ptr(),
            })
            .collect();
        let config = TASKDIALOGCONFIG {
            cbSize: std::mem::size_of::<TASKDIALOGCONFIG>() as u32,
            dwFlags: TDF_ALLOW_DIALOG_CANCELLATION,
            pszWindowTitle: title.as_ptr(),
            pszMainInstruction: title.as_ptr(),
            pszContent: detail.as_ptr(),
            cButtons: buttons.len() as u32,
            pButtons: buttons.as_ptr(),
            nDefaultButton: 100, // Return cancels; Escape/window close also map to cancel.
            pfCallback: Some(activate),
            ..Default::default()
        };
        let mut selected = 0;
        // All UTF-16 buffers and button entries outlive the modal call. Tauri's
        // default Windows manifest enables Common Controls v6 for TaskDialog.
        let result = unsafe {
            TaskDialogIndirect(
                &config,
                &mut selected,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
            )
        };
        let choice = if result < 0 {
            Err("无法显示系统弹窗".into())
        } else {
            Ok(choice_index(selected, buttons.len()))
        };
        let _ = sender.try_send(choice);
    })
    .map_err(|_| "无法显示系统弹窗")?;
    receiver.recv().await.ok_or("系统弹窗已关闭")?
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn close_escape_and_unknown_buttons_cancel() {
        for selected in [0, 2, 99, 103, i32::MIN] {
            assert_eq!(choice_index(selected, 3), 0);
        }
        assert_eq!(choice_index(100, 3), 0);
        assert_eq!(choice_index(101, 3), 1);
        assert_eq!(choice_index(102, 3), 2);
        assert_eq!(choice_index(102, 2), 0);
    }
}
