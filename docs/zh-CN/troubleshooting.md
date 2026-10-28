# 常见问题

[English](../en/troubleshooting.md) · **简体中文**

[返回首页](../../README.zh-CN.md) · [文档导航](README.md)

| 问题 | 处理方式 |
| --- | --- |
| 模型没有出现 | 在管理页更新客户端模型列表，完全退出并重开 Codex；确认目标 Codex 用户目录正确 |
| 所有模型都连不上 | 检查网关是否启动；启用期间官方模型也依赖网关 |
| 返回 401 | 更新当前 YAML、管理页或 CC Switch 来源的 Key；不会自动切换其他凭据来源 |
| 第三方模型调用了不存在的工具 | Responses API 会丢弃这次生成，并把错误反馈给同一模型重试，最多两次；仍失败时会报告 `GATEWAY_UNREGISTERED_TOOL`。命令执行失败由 Codex 官方执行器回传给模型处理；网络错误不会自动重放 |
| 安装失败 | 检查 Python 版本和网络后重试；macOS 可用 `CODEX_HYBRID_PYTHON` 指定解释器 |
| macOS 提示脚本权限错误 | 在项目根目录执行 `sh scripts/codex-hybrid.sh install` |
| 回滚发现配置有新修改 | 输入 `yes` 确认恢复初始化时的备份；当前配置会另存为数据目录中的 `pre-rollback-*.toml`。回车或非交互输入结束会取消；备份完整性校验失败仍拒绝恢复 |
| 卸载 | 执行 `./scripts/codex-hybrid.sh uninstall`；服务会先停止，之后确认恢复 Codex 配置并移除本地 provider 表。数据目录和凭据会保留 |
| 准备迁移或重装 | 先在原位置回滚、重启 Codex、停止服务，再安装依赖并使用所选数据目录重新初始化 |

第三方 Responses API 为避免执行被丢弃生成中的工具调用，会先缓存并校验整轮响应，
收到终止事件后再转发，因此首段输出会延迟；官方模型和 Chat Completions 保持流式转发。
最多两次重试表示最多三次上游请求，可能增加等待时间和用量。上游提前断流时丢弃缓存，
报告 `UPSTREAM_STREAM_ENDED_EARLY`，不会自动重放。

指定新目录不会自动导入旧配置。不要直接复用另一台机器的状态、备份或虚拟环境，
其中含有本机路径及服务状态。详见 [数据目录与迁移](configuration.md#数据目录)。
