# 桌面图标（可直接替换）

本目录是图标资源目录，当前使用临时的 CH 标识。

| 文件 | 用途 | 替换要求 |
| --- | --- | --- |
| `icon.png` | 应用图标原图、Tauri 默认窗口图标 | 1024 × 1024，RGBA PNG，保留透明边距 |
| `icon.icns` | macOS Finder / Dock 应用图标 | 从原图导出，或自行替换 ICNS |
| `icon.ico` | Windows 应用图标 | 从原图导出，包含多尺寸；尚未 Windows 实机验收 |
| `tray.png` | macOS 菜单栏 / 状态栏图标 | 44 × 44，RGBA PNG，透明背景、黑色图形；作为 2× 模板图标，系统自动适配明暗模式 |

替换 `icon.png` 后，在仓库根目录运行（Python 需安装 Pillow）：

```sh
python3 desktop/stage0/tauri/icons/export_icons.py
```

只改状态栏图标时，直接替换 `tray.png` 即可。图标在编译时嵌入，替换后需重新编译并重新打开应用。

Intel Mac 现有预览应用使用根目录的 `bash rebuild.sh`：先正常退出测试应用再运行。脚本会编译，并把 `icon.icns` 复制到预览 `.app/Contents/Resources/`、设置 `CFBundleIconFile`。此脚本需要现有预览应用目录及构建环境，不是安装程序。后续 Tauri bundle 通过 `tauri.conf.json` 的 `bundle.icon` 使用这些文件。

页面不再显示“重启 Codex”和“退出应用”按钮；macOS 通过状态栏菜单执行，退出也可使用应用菜单或 Cmd+Q。重启确认弹窗和退出保护继续保留。Windows 的关闭与进程机制保持原实现，当前没有 macOS 状态栏菜单。
