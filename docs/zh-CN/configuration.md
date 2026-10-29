# 配置说明

[English](../en/configuration.md) · **简体中文**

[返回首页](../../README.zh-CN.md) · [文档导航](README.md)

返回 [项目首页](../../README.zh-CN.md)。项目的 `config/` 提供配置示例，运行数据默认保存在 `~/.codex-hybrid/`：

- [models.example.yaml](../../config/models.example.yaml)：模型配置示例。
- [deepseek.example.env](../../config/deepseek.example.env)：环境文件示例，仅含占位值。

示例命名统一为 `<名称>.example.<扩展名>`。生成的配置、凭据与运行文件已排除版本控制。

## 数据目录

默认数据目录统一为 `~/.codex-hybrid/`，与 `~/.codex/` 同级，与源码位置无关。优先级：`--data-dir` → `CODEX_HYBRID_DATA_DIR` → 默认目录。自定义目录不自动记住，每次命令需使用相同参数或环境变量。不再生成或读取 `cli-config.json`；发现旧安装时会提示显式指定原目录，不自动搬迁。
向导完成后会打印带有所选目录的管理命令。相对路径按当前工作目录解析，建议使用绝对路径。
`--models-config` 仍可单独选择外部 YAML，省略时读取所选数据目录的 `models.yaml`。
管理页生成的托管配置保存到同一数据目录。

指定新目录不会自动导入旧目录，后续命令必须选择同一目录。旧版已初始化的实例仍需显式指定原数据目录，完成回滚、停止后再重新初始化。
`--codex-home` 仍独立选择 Codex 用户目录；启用时，其 `config.toml` 引用所选数据目录的
`models.json`。`CODEX_HYBRID_HOME`（兼容旧 `MODEL_ROUTER_HOME` / `CONNECTED_HOME`）仅用于发现旧安装，不再设置数据根目录。

迁移或重装前，在原位置使用原数据目录执行 `uninstall`，按提示确认回滚；本机数据和凭据会保留。新位置安装依赖后，
指定数据目录重新运行 `install`。不要直接复用另一台机器的状态、备份或虚拟环境，
其中包含本机绝对路径和服务状态。本次不提供自动迁移功能。

## 向导填写

在 `install` 中选择“1 = 手动填写 API”，填写以下信息：

| 字段 | 示例 / 含义 |
| --- | --- |
| API 前缀 | `https://api.deepseek.com`；是否包含 `/v1` 按供应商要求，不填 `/chat/completions` |
| 模型 ID | `deepseek-v4-flash`；须使用账号实际有权限的准确 ID |
| 显示名称 | `DeepSeek Flash`；显示在 Codex 模型列表中 |
| 协议 | 供应商支持的 Chat Completions 或 Responses |
| API Key | 输入不显示；保存在本机私有文件中 |

向导在所选数据目录生成 `setup-models.yaml` 和 `provider.env`，然后询问是否现在启动服务。安装过程不会自动启用路由；在管理页打开“客户端路由”开关后，才会更新 Codex 配置。服务启动后会在管理链接可用时打开管理页。Key 输入不显示，首次配置不会自动调用付费 API。

## CC Switch

### Responses 原生与兼容模式

管理页将协议标为“供应商接口协议”，并在手动配置和 CC Switch 厂商卡片中持续展示实际转发方式。选择 Chat Completions 时，本工具保留 Responses → Chat Completions 转换；部分工具类型、独立工具通知和推理历史可能降级或不受支持，连接测试通过不代表全部桌面功能兼容。该配置需要通过本工具接入，不能据此认定 Codex 可以直连 Chat Completions。

自行配置或 CC Switch 选择 Responses 后，默认保留原生协议结构；失败不会自动转为 Chat Completions。Chat Completions 继续走兼容转换。仅支持部分 Responses 特性的端点可能拒绝原生请求，此时应检查具体错误，再显式选择兼容模式。

独立 YAML 可在厂商层配置（管理页“高级参数”也提供这两个选项）：

```yaml
protocol: openai_responses
responses_compatibility: native  # 默认；portable 显式启用原有历史与工具转换
history_migration: false        # true 仅移除可按完整内容重放的历史项 ID
```

`portable` 会归并系统指令、展开工具定义、将独立工具输出降级为 user 上下文，并将可读推理转为历史文本、移除不透明推理；它已包含历史项 ID 重放。`history_migration` 本身不会解密推理或还原纯 ID 引用。两个服务都使用 Responses，不代表加密状态与文件资源可以互用。

CC Switch 模式从所选 `model_providers.<厂商>` TOML 配置读取同名字段；本项目只读其数据库，不代写这些选项。未填写时使用 `native` 和 `false`。协议仍由 CC Switch 的 `meta.apiFormat` 优先于 `wire_api` 决定。Chat Completions 不接受 `portable` 或开启历史迁移这两个 Responses 专属设置。

旧版单厂商 `.env` 路由也默认走原生 Responses；需要 Portable 时请改用上述 YAML 或 CC Switch 配置。

### 目录与同步

每个 Codex 模型条目固定绑定 CC Switch 的厂商记录 ID 和确切模型 ID。`slug` 直接使用 `厂商记录ID/模型ID`，不哈希、不转义、不按斜杠拆分；绑定表单独保存 `provider_record_id`、`app_type` 和 `model_id`。显示名称仅用于展示。CC Switch 导入目录不设置默认模型，调用必须明确选择模型；仅提供模型列表而未配置默认模型也可导入。CC Switch 的 `config.model` 若存在，作为一个确切模型加入列表。

网关启动时读取一次 CC Switch，随后监听数据库所在目录中数据库及 `-wal` 文件的变化，合并连续事件并等待约 300 毫秒后同步；另保留每 30 秒兜底检查，监听不可用时自动退回定期检查。管理页关闭时也继续同步，页面刷新只读取后台缓存，不再触发数据库读取。页面显示实际同步时间，无变化的检查不会更新时间。模型目录、完整绑定表和源版本一起保存在 `settings.json` 的 `cc_snapshot` 中，客户端目录文件由该快照生成。同步整体替换当前 CC Switch 目录，删除项和旧绑定一起移除，官方模型保留。读取或校验失败时保留上一份快照并重试，不发布部分结果。删除全部受支持的厂商记录后，外部模型列表清空。

修改厂商名称、模型显示名称或 CC Switch 默认模型不会改变已有条目的模型身份；地址和凭据仍在每次请求时重新读取。删除模型或厂商记录后，旧选择会报错，不会自动改用其他模型。含凭据的原始配置不会写入绑定表。

升级代码并重启网关后会自动发布新目录，旧版本的 `cc_…/default` 和 `cc_…/model_…` 哈希标识不再接受。请重启 Codex，并在使用旧标识的会话中重新选择模型。后续目录变化会自动同步，但运行中的 Codex 可能仍缓存旧目录，管理页会提示手动重启；自动同步不等于客户端已加载新列表。

在向导中选择“2 = 本机 CC Switch”，确认数据库路径（默认 `~/.cc-switch/cc-switch.db`），随后确认启用。
只读取 OpenAI / Codex 第三方静态 API 配置，不回写数据库、不切换其他工具的当前厂商。
模型和 Key 请在 CC Switch 中修改；当前来源失败时不会回退另一份 Key。

## 手动 YAML

首次使用且尚未初始化时，复制示例并填写配置。以下使用默认目录；自定义目录时修改变量，并统一设置环境变量 `CODEX_HYBRID_DATA_DIR` 。所有命令在项目根目录执行。

```sh
# macOS / Linux
ROUTER_DATA_DIR="$HOME/.codex-hybrid"
mkdir -p "$ROUTER_DATA_DIR"
cp config/models.example.yaml "$ROUTER_DATA_DIR/models.yaml"
cp config/deepseek.example.env "$ROUTER_DATA_DIR/deepseek.env"
chmod 600 "$ROUTER_DATA_DIR/models.yaml" "$ROUTER_DATA_DIR/deepseek.env"
```

```powershell
# Windows PowerShell
$RouterDataDir = Join-Path $HOME ".codex-hybrid"
New-Item -ItemType Directory -Force $RouterDataDir
Copy-Item config/models.example.yaml (Join-Path $RouterDataDir "models.yaml")
Copy-Item config/deepseek.example.env (Join-Path $RouterDataDir "deepseek.env")
```

编辑 `models.yaml` 中的 API 地址、协议和模型 ID，并在 `deepseek.env` 中填写 `DEEPSEEK_API_KEY`。示例的模型 key 为 `deepseek/flash`，即 YAML 的 `厂商标识/模型别名`，它与供应商模型 ID 是两个概念。

```sh
# macOS：准备 → 启动 → 接入 Codex
./scripts/codex-hybrid.sh prepare --source yaml
./scripts/codex-hybrid.sh start
./scripts/codex-hybrid.sh activate
```

```powershell
# Windows
.\scripts\codex-hybrid.cmd prepare --source yaml
.\scripts\codex-hybrid.cmd start
.\scripts\codex-hybrid.cmd activate
```

`prepare` 只适用于首次初始化。已有配置要切换 YAML，请按[命令与安装进阶](cli.md)执行 `refresh-models --source yaml --models-config /path/to/models.yaml`，不要重复 `prepare`。

## API Key 配置

先将 `config/models.example.yaml` 复制为 `<数据目录>/models.yaml`，修改厂商和模型信息。每个厂商的 `credentials` 选择以下一种方式。

直接写入 YAML（管理页保存新 Key 时也使用此方式）：

```yaml
credentials:
  api_key: "YOUR_API_KEY"
```

或者使用环境变量 / `.env` 文件：将 `config/deepseek.example.env` 复制为 `<数据目录>/deepseek.env`，填写 `DEEPSEEK_API_KEY=YOUR_API_KEY`，并在 YAML 中配置：

```yaml
credentials:
  api_key_env: DEEPSEEK_API_KEY
  env_file: ./deepseek.env
```

`env_file` 相对于 YAML 所在目录解析；省略该字段时只读取网关进程的环境变量。`.env` 不会被自动扫描，必须显式引用。其他厂商使用相同方式，更换变量名即可。

| 同时存在的情况 | 实际读取规则 |
| --- | --- |
| YAML 仅配置 `api_key`，磁盘上另有 `.env` 或环境变量 | 使用 YAML 的 Key，不读取另外的来源 |
| 同一个 credentials 同时配置 `api_key` 和 `api_key_env` / `env_file` | 拒绝加载，报 `CONFIG_AMBIGUOUS_CREDENTIALS`，必须选择一种 |
| 使用 `api_key_env`，进程环境变量和指定 `.env` 都有值 | 优先使用进程环境变量；未设置或为空时读取指定 `.env` |
| 所选来源没有有效 Key | 请求失败，不自动切换其他凭据来源 |

若网关已经运行，在另一个终端 export 环境变量不会更新既有网关进程的环境；需要重启网关。显式引用的 `.env` 在后续请求时重新读取。

管理页面输入的新 Key 默认保存在 `<数据目录>/managed-models.yaml` 的 `credentials.api_key`，替换该厂商原来的环境变量引用；留空则保留已有来源。保存后，当前来源切换为这份托管 YAML，原来的手动 YAML 保持不变；之后应修改当前来源文件，或在管理页继续编辑。页面不回显 Key。

实际配置位于所选数据目录，包含凭据的文件不要提交版本控制。手动创建的含 Key 文件建议设置为 `0600` 权限（Windows 使用目录 ACL）；管理页生成的文件自动设置私有权限。

## 管理页面

当前版本需要先通过向导或手动 YAML 完成初始化，不能从空管理页开始安装。默认直接打开
`http://127.0.0.1:18892/manage/` 即可管理（管理端口默认是转发端口加 1，可用 management_port 独立设置，以 manage-url 输出为准），也可运行以下命令获取地址：

```sh
./scripts/codex-hybrid.sh manage-url
```

需要只允许通过私密链接访问时，在 `manage-url` 后附加开关：

```sh
./scripts/codex-hybrid.sh manage-url --management-auth on   # 开启并返回带令牌的链接
./scripts/codex-hybrid.sh manage-url --management-auth off  # 关闭校验
```

新安装默认关闭校验，`manage-url` 返回可直接打开的普通地址。指定 `--management-auth` 时必须跟 `on` 或 `off`，并会自动重启服务。开启后普通地址只显示访问受限提示，
管理页面和管理操作都必须通过返回的私密链接访问。开关保存在数据目录的 `settings.json`，
普通 `restart` 会保留设置；不带 `--management-auth` 时只获取当前地址，不改变设置。

安装成功后使用统一用户目录，自定义目录需持续显式指定；临时切换可附加 `--data-dir`，或设置 `CODEX_HYBRID_DATA_DIR`。Windows 使用 `.\scripts\codex-hybrid.cmd manage-url`。
在“独立管理”中添加厂商、填写 API、协议、Key 和模型，然后保存；在“CC Switch”中选择只读数据库来源。
Key 不回显；开启私密链接后链接带本机访问令牌，不要公开分享。

保存到管理页后，独立配置由 `managed-models.yaml` 接管，原手动 YAML 不会被覆盖。之后修改当前来源或继续在页面编辑。新增 / 删除模型后完全退出并重开 Codex；仅更新 Key / API 地址时下一轮请求生效。

## 手动接入 Codex

`prepare` 读取目标 Codex 目录的 `config.toml` 和 `models_cache.json`，在所选数据目录生成：

- `models.json`：保留官方模型，并追加启用的第三方模型。
- `original-config.toml`：原配置备份。
- `desktop-config.toml`：准备写入 Codex 的完整候选配置。
- `settings.json`、`state.json`：网关设置、目标配置路径与防覆盖校验。

`start` 启动后台网关；`activate` 检查网关就绪后，将候选配置写入目标 `config.toml`。`install` 将这些步骤串起来；不修改 Codex 应用程序或模型权重。

如果希望自己编辑，先完成 `prepare` 和 `start`，然后对照生成的 `desktop-config.toml` 修改实际的 Codex `config.toml`，无需再执行 `activate`。核心修改如下（占位值不能直接使用）：

```toml
# 顶层字段，必须放在所有 [表] 之前；已有同名字段应替换，不能重复添加。
model_provider = "codex-hybrid"
model_catalog_json = "/absolute/path/to/router-data/models.json"

[model_providers.codex-hybrid]
name = "Codex Hybrid"
base_url = "http://127.0.0.1:18891"
wire_api = "responses"
requires_openai_auth = true
supports_websockets = false
request_max_retries = 4
stream_max_retries = 5
stream_idle_timeout_ms = 300000
http_headers = { "X-Connected-Token" = "从生成的候选配置复制实际本地令牌" }
```

以上重试次数和 SSE 空闲超时与 Codex 文档默认值一致。HTTP 重试及流中断恢复由 Codex 处理，网关不自动重放失败的上游 POST。官方上游的 socket 超时为 300 秒，不是整轮对话的总时限；第三方厂商继续使用其 `timeout_seconds` 配置。


`model_provider` 选中网关；`base_url` 指向网关监听地址；`model_catalog_json` 指向生成的绝对路径；`X-Connected-Token` 必须与 `settings.json` 的 `local_token` 一致，不能使用供应商 Key。自定义端口时按候选配置填写。Windows 路径建议直接复制候选配置中的 TOML 转义形式。

推荐使用生成的完整候选配置和 `activate`，以保留备份与校验。自己编辑后，`status` 可能显示 `modified_since_prepare`，自动启用 / 回滚可能因防覆盖校验而拒绝；恢复时需人工对照备份合并。不要在配置已发生其他修改后直接覆盖整个文件。
