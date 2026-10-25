<div align="center">

# Codex Model Bridge

[English](README.md) · **简体中文**

**在 Codex 原生模型列表中，统一使用官方订阅与第三方 API。**

主会话切换模型，也能让官方主 agent 调用第三方原生子 agent。<br>
通过本地管理页维护厂商、模型和 Key，支持复用 CC Switch 配置。

[快速开始](#快速开始) · [使用效果](#使用效果) · [常用命令](#常用命令) · [完整文档](docs/zh-CN/README.md)

</div>

## 使用效果

<table>
  <tr>
    <td align="center" valign="middle">
      <img src="docs/images/codex-model-picker.png" width="520" alt="在 Codex 原生列表中选择第三方模型，并收到 Hello World 回复">
    </td>
    <td align="center" valign="middle">
      <img src="docs/images/management.png" width="290" alt="Codex Model Bridge 本地管理页：客户端路由、配置来源与厂商模型管理">
    </td>
  </tr>
  <tr>
    <td align="center"><sub>在原生模型列表中选择第三方模型并收到回复</sub></td>
    <td align="center"><sub>在一页内管理路由、来源、厂商与模型</sub></td>
  </tr>
</table>

| 你想做什么 | 如何使用 |
| --- | --- |
| 在 Codex 中使用第三方模型 | 添加模型 → 重启 Codex → 在原生模型列表中选择 |
| 官方模型与第三方模型协作 | 官方主 agent 创建指定模型的原生子 agent |
| 复用已有配置 | 选择 CC Switch 来源，只读同步，继续在 CC Switch 中维护 |

## 快速开始

### 1. 准备环境

- **macOS / Windows**，安装 **Python 3.11+**。
- 安装并登录 **Codex 桌面客户端**，完成过一次聊天。
- 准备第三方模型的 **API 地址、模型 ID、Key**，或已有的 **CC Switch** 配置。

### 2. 下载并启动

使用 Git 将仓库克隆到准备长期保留的目录：

```sh
git clone https://github.com/MakiNaruto/CodexModelBridge.git codex-model-bridge
cd codex-model-bridge
```

在项目根目录运行对应命令，或双击启动文件：

| 系统 | 终端命令 | 双击启动 |
| --- | --- | --- |
| macOS | `sh scripts/codex-model-bridge.sh install` | `scripts/start-macos.command` |
| Windows（PowerShell） | `.\scripts\codex-model-bridge.cmd install` | `scripts/start-windows.cmd` |

启动器自动创建 `.venv`、安装依赖并打开中文向导。首次安装需要联网下载依赖。

### 3. 按向导配置，重启 Codex

1. 选择 **手动填写 API** 或 **本机 CC Switch**，按提示完成配置。
2. 按提示选择是否现在启动本机服务；安装不会自动启用客户端路由。
3. 服务启动后，在管理页点击“客户端路由”开关启用路由，然后**完全退出并重新打开 Codex**。

打开开关时，程序会备份并更新 Codex 的 `config.toml`：将 `model_provider` 设为 `codex-model-bridge`，并写入本地模型目录和网关连接配置。关闭开关会将 `model_provider` 切回 `openai`，并移除本地模型目录设置，同时保留 `codex-model-bridge` provider 表，方便之后重新打开。本地服务仍会运行。

默认数据保存在 `~/.codex-model-bridge/`，后续可在[本地管理页](http://127.0.0.1:18891/manage/)添加厂商、模型或修改 Key。自定义端口或启用私密链接时，用 `manage-url` 获取地址。

> 启用路由后，官方与第三方模型都依赖本地服务；重启电脑后请先运行 `start`。自定义数据目录、Codex 路径及手动 YAML 配置见[安装进阶](docs/zh-CN/cli.md)。

### 4. 发出第一条消息

选择第三方模型，新建聊天并发送：

```text
只回复：Hello World
```

预期收到 `Hello World`。这能初步确认模型可用；工具调用与原生子 agent 的验证步骤见[使用指南](docs/zh-CN/usage.md)。

管理页也可点击 **测试连接** 发送一次基础请求。聊天和连接测试都会使用相应供应商额度；首次配置不会自动调用付费 API。

## 常用命令

以下以 macOS 为例；Windows 将 `./scripts/codex-model-bridge.sh` 换成 `.\scripts\codex-model-bridge.cmd`。

```sh
./scripts/codex-model-bridge.sh start           # 启动服务
./scripts/codex-model-bridge.sh stop            # 停止服务
./scripts/codex-model-bridge.sh status          # 查看服务状态与模型 key
./scripts/codex-model-bridge.sh manage-url      # 获取管理页面地址
./scripts/codex-model-bridge.sh refresh-models  # 更新客户端模型列表，随后重启 Codex
./scripts/codex-model-bridge.sh restart         # 更新代码后重启服务
./scripts/codex-model-bridge.sh rollback        # 恢复接入前备份
./scripts/codex-model-bridge.sh uninstall       # 停止服务并交互确认恢复 Codex 配置
```

新增或删除模型后，更新客户端模型列表并重启 Codex；仅修改 Key 或 API 地址时，下一轮请求生效。

## 继续探索

| 文档 | 内容 |
| --- | --- |
| [配置指南](docs/zh-CN/configuration.md) | API Key、YAML、CC Switch、数据目录与迁移 |
| [命令与安装进阶](docs/zh-CN/cli.md) | 全部常用命令、默认值、私密链接、自定义路径 |
| [使用与验证](docs/zh-CN/usage.md) | 连接测试、主会话、原生子 agent 示例与验证边界 |
| [常见问题](docs/zh-CN/troubleshooting.md) | 模型未出现、401、安装失败、回滚 |
| [工作原理](docs/zh-CN/architecture.md) | 请求路由与凭据边界 |
