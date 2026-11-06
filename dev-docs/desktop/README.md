# 桌面开发导航

本组指南于 2026-11-06 从历史增量中提取，源码入口已迁入 `src-tauri/`、`sidecar/`、`tools/`、`validation/` 和 `tests/`。`build/stage0`、`dist/stage0`、应用身份与原环境变量保留兼容。指南语言为简体中文。

| 主题 | 当前指南 | 保留的原始来源 |
| --- | --- | --- |
| 当前代码与平台边界 | [目录架构](../architecture/repository-layout.md)、[平台约定](../architecture/platform-boundaries.md) | [网页桌面对齐历史](../archive/desktop/web-desktop-alignment-history.md) |
| 开发环境与调试 | [日常开发](development.md) | [交接记录](../archive/desktop/handoff-history.md)、[工具说明](../archive/desktop/stage0-tools.md) |
| macOS 构建 | [macOS](build-macos.md) | [Intel 构建历史](../archive/desktop/build-macos-intel-history.md) |
| Windows 构建 | [Windows](build-windows.md) | [Windows 构建历史](../archive/desktop/build-windows-history.md) |
| 资源与分发 | [打包契约](packaging.md) | 两个平台构建历史 |
| IPC | [私有协议](private-protocol.md) | [协议历史](../archive/desktop/private-management-history.md) |
| 托盘、退出与恢复 | [生命周期](lifecycle.md) | [页面对齐记录](../archive/desktop/web-desktop-alignment-history.md)、协议历史 |
| 执行与证据 | [验证指南](validation.md) | [阶段验证记录](../archive/desktop/stage0-validation.md) |
| 当前缺口 | [状态与待验收项](status.md) | [产品计划](../archive/desktop/stage0-plan.md)、交接记录 |

原文保留日期、历史决策与未完成事项。原文存在被后续增量替代的描述，排查历史时按日期和平台阅读。本轮 Intel 构建与冻结检查范围见[当前验证矩阵](status.md#本轮验证矩阵)，窗口操作与其他平台验收分别列出。

历史原文已移入[桌面归档](../archive/desktop/README.md)，旧位置保留标题锚点和逐节跳转。当前产品决策见[开发约束](development.md#已确认的产品与开发约束)，未完成验收项见[状态](status.md)。
