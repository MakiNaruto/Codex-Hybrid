# 开发注意事项

本文件适用于整个仓库。修改前先确认问题发生的平台，再确定共享代码与平台专用代码的修改范围。

## Windows 与 macOS 的修改边界

- Windows 与 macOS 的系统行为分别维护。单个平台的问题应在对应的平台分支或模块内修复；修改公共入口时，必须确认另一平台的行为仍符合其现有约定。
- 涉及代理、进程识别、桌面退出与启动、后台服务、安装脚本、路径和权限时，先分别检查两个平台的实现，不要仅凭当前开发机的行为统一实现。
- 只有需求明确适用于两个平台，且两个平台的实现依据都已确认时，才同步调整两边的行为。代码去重不能作为改变另一平台行为的理由。
- 平台分支应显式表达，并将操作系统 API 限定在对应分支或专用模块内。共享业务逻辑调用平台入口。
- 修改说明中写清适用平台和验证范围。模拟平台的单元测试通过，只能说明对应分支在模拟条件下通过；不能据此宣称已完成另一操作系统的实际验收。

## 上游代理的现有约定

入口为 `src/gateway/transport.py`，网关转发和管理页连接测试共用此入口。

| 行为 | Windows | macOS |
| --- | --- | --- |
| 代理来源 | 每次请求读取当前用户 Windows 系统 HTTP/HTTPS 代理 | 显式 `upstream_proxy` 优先；未设置时通过 Python `urllib.request.getproxies()` 读取环境与系统代理 |
| 环境变量 | `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 等不覆盖系统代理选择 | 保留 Python 的现有代理发现规则 |
| `upstream_proxy` | 不覆盖 Windows 系统选择 | 保留显式覆盖能力 |
| 绕过规则 | 使用 Windows 系统绕过规则，不读取继承的 `NO_PROXY` | 保留 Python 原有绕过规则 |
| 关闭系统代理 | 下一次请求走直连；能否访问由网络决定 | 按 macOS 当前代理发现逻辑处理，仍可能存在环境或显式代理 |
| 设置变化 | 每次请求重新读取，无需为代理切换重启服务 | 未使用显式代理时，每次请求重新发现代理 |

- Windows 的系统代理指手动 HTTP/HTTPS 代理配置；当前实现不解析 PAC 自动配置脚本。
- Clash TUN 等网络层转发由操作系统与代理软件控制，不能仅凭系统代理开关推断实际出口。
- 不要把 Windows 的“仅跟随系统代理”规则扩展到 macOS；也不要重新引入环境变量或显式代理对 Windows 系统选择的覆盖。
- 验证代理改动时，覆盖开启、地址切换、关闭后直连、绕过规则，以及环境变量与显式代理的优先级；同时保留另一平台的行为断言。相关测试为 `tests/test_gateway_transport.py`。
- 用户说明见 `docs/zh-CN/usage.md` 和 `docs/en/usage.md`。行为发生变化时同步更新对应平台的说明。

## 桌面与脚本入口

- 桌面公共入口：`src/desktop/client.py`。
- Windows：`src/desktop/windows_client.py`、`src/desktop/windows_processes.py`、`src/desktop/windows_restart_manager.py`；使用 Windows 进程与 Restart Manager 机制。
- macOS：`src/desktop/macos_client.py`；使用应用标识、Apple events 与 Launch Services 机制。
- 安装和服务脚本：分别检查 `scripts/` 中 Windows `.cmd` / PowerShell 与 macOS `.sh` 的实际入口。
- 平台行为与已验证边界另见 `desktop/docs/web-desktop-alignment.md`。
