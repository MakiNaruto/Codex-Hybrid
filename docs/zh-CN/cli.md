# 命令与安装进阶

[English](../en/cli.md) · **简体中文**

[返回首页](../../README.zh-CN.md) · [文档导航](README.md)

## 安装补充

通过 Git 将仓库克隆到准备长期保留的目录。以下命令均在项目根目录执行。

| 系统 | 双击启动 | 终端启动 |
| --- | --- | --- |
| macOS | `scripts/start-macos.command` | `./scripts/codex-model-bridge.sh install` |
| Windows（PowerShell） | `scripts/start-windows.cmd` | `.\scripts\codex-model-bridge.cmd install` |

启动器会创建项目 `.venv`、安装依赖并进入中文配置向导，按提示填写模型信息即可。
Windows 建议安装 Python 时勾选 Python Launcher 或 Add Python to PATH。
如果暂时不填写，可在依赖安装完成后按 `Ctrl+C` 退出，之后重新运行 `install` 补充；首次初始化仍需有效模型配置，完成后才能启动服务和打开管理页。

默认数据目录统一为 `~/.codex-model-bridge/`，与 `~/.codex/` 同级，与源码位置无关。优先级：`--data-dir` → `CODEX_MODEL_BRIDGE_DATA_DIR` → 默认目录。自定义目录不自动记住，每次命令需使用相同参数或环境变量。不再生成或读取 `cli-config.json`；发现旧安装时会提示显式指定原目录，不自动搬迁。

向导会询问是否现在启动本机服务，但不会在安装时启用路由。需要接入 Codex 时，在管理页打开“客户端路由”开关；程序会更新目标 Codex 的 `config.toml`。之后请**完全退出并重新打开 Codex**。
Codex 用户目录默认是 `~/.codex`，可通过 `CODEX_HOME` 或首次初始化时的 `--codex-home` 指定；应选择客户端实际使用的目录。

## 常用命令

安装配置完成后，使用以下命令管理服务。下面以 macOS 为例；Windows 将 `./scripts/codex-model-bridge.sh` 换成 `.\scripts\codex-model-bridge.cmd`。

```sh
./scripts/codex-model-bridge.sh install         # 安装依赖、首次配置；已有初始化时保留配置并启动
./scripts/codex-model-bridge.sh start           # 启动服务
./scripts/codex-model-bridge.sh stop            # 停止服务
./scripts/codex-model-bridge.sh manage-url      # 获取管理页面地址
./scripts/codex-model-bridge.sh status          # 查看服务、配置来源与模型 key
./scripts/codex-model-bridge.sh refresh-models  # 从当前来源更新客户端模型列表
./scripts/codex-model-bridge.sh restart         # 重启服务，更新代码后执行
./scripts/codex-model-bridge.sh activate        # 将 Codex 接入本项目的本地路由服务
./scripts/codex-model-bridge.sh rollback        # 恢复初次安装时的备份配置
./scripts/codex-model-bridge.sh uninstall       # 停止服务并确认是否恢复 Codex 配置
```

`uninstall` 会先停止 Codex Model Bridge 本机服务，再询问是否将 Codex 配置恢复为安装前备份，并移除该服务写入的 `codex-model-bridge` provider 表。若检测到初始化后的配置改动，覆盖前还会再次要求输入 `yes` 确认。为便于重新安装，数据目录中的配置文件和凭据会保留。

默认直接打开 http://127.0.0.1:18891/manage/ 即可管理（自定义端口时替换端口）。
私密链接访问默认关闭；已有 `management_token` 也不会自动开启校验。
需要开启时执行 `./scripts/codex-model-bridge.sh manage-url --management-auth on`，获取带令牌的私密链接；开启后管理页面和管理操作均必须通过该链接访问，普通地址只显示访问受限提示。
执行 `./scripts/codex-model-bridge.sh manage-url --management-auth off` 可关闭校验。
指定 `--management-auth on|off` 时会自动重启服务使设置生效，并输出对应的管理链接；该参数必须跟 `on` 或 `off`。不带该参数时只获取当前链接。新安装默认关闭鉴权，可直接打开本机管理页。
开关保存在数据目录的 `settings.json` 中，普通重启会保留设置。

`activate` 会将 Codex 的模型提供方设为 `codex-model-bridge`，请求地址指向本项目的本地服务。
模型仍通过 Codex 原生模型列表选择，实际请求由本项目按模型 key 转发到对应供应商；官方模型请求也经过本地服务。

安装完成后运行 `status`，`service_running` 应为 `true`，
`config_state` 应为 `activated`；重启 Codex 后，原生模型列表中应出现第三方模型。

## 实例配置

```sh
./scripts/codex-model-bridge.sh config
./scripts/codex-model-bridge.sh config --data-dir /path/to/data
```

`config` 只读查看所选实例，不再支持 `--set` 或 `--reset`。端口和鉴权设置保存在数据目录的 `settings.json`；Codex 目标沿用初始化时记录的路径。首次安装可用 `--port`、`--codex-home`，已有实例鉴权使用 `manage-url --management-auth on|off` 修改。

## 模型配置方式

### 1. 安装时填写，之后也可补充

在 `install` 向导中选择“1 = 手动填写 API”，按提示填写 API 前缀、准确模型 ID、显示名称、协议和 API Key。
暂时不填时可退出向导，之后重新运行 `install`。完成初始化后，可用 `manage-url` 获取管理页面链接并在浏览器打开，继续添加厂商、模型或修改 Key。
向导生成 `setup-models.yaml` 和 `provider.env`；具体字段见 [向导填写](configuration.md#向导填写)。

### 2. 读取 CC Switch 配置

在向导中选择“2 = 本机 CC Switch”，确认数据库路径，默认是 `~/.cc-switch/cc-switch.db`。
已有初始化也可在管理页切换到 CC Switch 来源。程序只读其中的 OpenAI / Codex 第三方静态 API 配置，
模型、API 地址和 Key 继续在 CC Switch 中维护。详见 [CC Switch](configuration.md#cc-switch)。

### 3. 手动修改 YAML

首次初始化前，将 `config/models.example.yaml` 复制为数据目录中的 `models.yaml`，按实际供应商修改：

| 字段 | 填写内容 |
| --- | --- |
| `providers.<厂商标识>.base_url` | API 前缀，是否包含 `/v1` 按供应商要求，不填 `/chat/completions` |
| `protocol` | Chat Completions 用 `openai_chat_completions`，Responses 用 `openai_responses` |
| `credentials` | 直接填写 `api_key`，或用 `api_key_env` 配合 `env_file` 引用 Key，二选一 |
| `models.<模型别名>.model_id` | 供应商实际支持的准确模型 ID |
| `models.<模型别名>.display_name` | Codex 模型列表中的显示名称 |
| `enabled` | 将需要使用的厂商、模型设为 `true`；示例中的占位条目默认禁用 |
| `default_model` | 默认模型 key，格式为 `厂商标识/模型别名`，例如 `deepseek/flash` |

沿用示例的凭据方式时，还需将 `config/deepseek.example.env` 复制为数据目录中的 `deepseek.env`，
填写 `DEEPSEEK_API_KEY`。`env_file` 相对于 YAML 所在目录解析。

```sh
# 仅首次初始化使用 prepare；Windows 替换启动器路径即可
./scripts/codex-model-bridge.sh prepare --source yaml
./scripts/codex-model-bridge.sh start
./scripts/codex-model-bridge.sh activate
```

随后完全退出并重开 Codex。已有初始化要切换 YAML，使用 `refresh-models --source yaml --models-config /path/to/models.yaml`，
再执行 `restart` 并重启 Codex，不要重复 `prepare`。
管理页保存配置后会改用 `managed-models.yaml`，之后应修改当前来源文件，可通过 `status` 查看。
完整示例与凭据说明见 [手动 YAML](configuration.md#手动-yaml) 和 [API Key 配置](configuration.md#api-key-配置)。

> [!NOTE]
> 首次配置不会自动调用付费 API。管理页的“测试连接”会发送一次真实请求并消耗供应商额度。

## 交给模型安装

```text
请按本仓库 README 为当前机器安装 Codex Model Bridge。
先检查 Python 3.11+、Codex 实际用户目录及其中 config.toml/models_cache.json，
确认路由器数据目录（参数、环境变量或向导选择；默认 config），
再检查该目录的 state.json；已有初始化时复用，不重复 prepare。后续命令使用同一目录。
使用项目启动器及 .venv。根据我指定的 YAML 或 CC Switch 来源配置；
缺少来源信息时先询问，不读取无关凭据，不把 Key 或管理令牌输出到聊天。
接入前说明要修改的 Codex config.toml 路径，保留备份及其他设置。
完成后检查服务状态，提醒我完全退出并重开 Codex，再按 README 验证模型。
真实连接测试会消耗额度，仅在我明确要求测试时执行。
报告实际执行结果和未验证项，不把预期输出当成实测结果。
```
