# 桌面图标（可直接替换）

本目录是图标资源目录。macOS 与 Windows 均使用「折芽 / Folded Seed」标识，分别维护各自的原图与平台格式。

| 文件 | 用途 | 替换要求 |
| --- | --- | --- |
| `icon-macos.png` | macOS 应用图标原图、Tauri 默认窗口图标 | 1024 × 1024，RGBA PNG，保留透明边距 |
| `icon.png` | Windows 及未覆盖平台的图标原图、Tauri 默认窗口图标 | 1024 × 1024，RGBA PNG，保留透明边距 |
| `icon.icns` | macOS Finder / Dock 应用图标 | 从 `icon-macos.png` 导出，或自行替换 ICNS |
| `icon.ico` | Windows EXE / 应用图标 | 从 `icon.png` 导出，包含 16、24、32、48、64、128、256 像素尺寸；尚未 Windows 实机验收 |
| `tray.png` | macOS 菜单栏 / 状态栏图标 | 44 × 44，RGBA PNG，透明背景、黑色图形；作为 2× 模板图标，系统自动适配明暗模式 |

macOS 通过 `tauri.macos.conf.json` 覆盖图标配置，不改变 Windows 的资源选择。替换 `icon-macos.png` 后，在仓库根目录运行（Python 需安装 Pillow）：

```sh
python3 -c "from PIL import Image; Image.open('apps/desktop/stage0/tauri/icons/icon-macos.png').save('apps/desktop/stage0/tauri/icons/icon.icns', format='ICNS')"
```

`export_icons.py` 分别从 `icon.png` 导出 Windows ICO、从 `icon-macos.png` 导出 macOS ICNS。在仓库根目录运行（Python 需安装 Pillow）：

```sh
python3 apps/desktop/stage0/tauri/icons/export_icons.py
```

Windows 沿用 `tauri.conf.json` 中的 PNG / ICO 配置。当前 Windows 原图复用 macOS「折芽」设计；后续可单独替换 `icon.png` 并重新导出。已检查 PNG 的 RGBA 格式、ICO 的全部尺寸及配置资源路径，Windows EXE、快捷方式和任务栏显示仍需在 Windows 实机重新构建后验收。

只改状态栏图标时，直接替换 `tray.png` 即可。图标在编译时嵌入，替换后需重新编译并重新打开应用。

Intel Mac 现有预览应用使用 `bash scripts/build_desktop.sh`。先正常退出测试应用再运行。脚本会编译，并把 `icon.icns` 复制到预览 `.app/Contents/Resources/`、设置 `CFBundleIconFile`。此脚本可从空产物目录创建预览应用，需先准备 Python 环境、Rust 和 Xcode；缺少构建依赖时会联网下载。后续 Tauri bundle 通过 `tauri.conf.json` 的 `bundle.icon` 使用这些文件。

脚本更新图标后会刷新应用包修改时间，并仅强制更新该应用的 Launch Services 注册，避免 Finder / Dock 保留原地重建前的图标记录；不重置系统的全局缓存。

页面不再显示“重启 Codex”和“退出应用”按钮；macOS 通过状态栏菜单执行，退出也可使用应用菜单或 Cmd+Q。重启确认弹窗和退出保护继续保留。Windows 的关闭与进程机制保持原实现，当前没有 macOS 状态栏菜单。
