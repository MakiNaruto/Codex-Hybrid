# 网页实现与桌面方案对齐

对齐日期：2026-10-28。依据为管理页 `src/management/web/`、管理业务层及 `src/desktop/`，不是阶段 0 静态探针页面。本文记录可复用的现有行为；桌面完整目标以[实施计划](plan.md)为准。代码与自动化覆盖不等于真实 Codex、真实厂商或双平台安装验收。

## 已实现规则与文档修正

| 主题 | 当前实现及后续复用规则 | 证据（仓库根目录相对路径） |
| --- | --- | --- |
| 首次使用 | 可跳过模型配置，进入空管理页；凭据可读取不代表连接成功，不自动发送测试 | `src/cli/setup_wizard.py`、`src/management/web/app.js`；`tests/test_web_workflow.py` |
| 厂商与模型 | 搜索、启用筛选、模型 key 复制、超时编辑、连接测试耗时；测试使用保存后的配置；Key/API 下一轮请求生效，模型目录更新需重启客户端 | `src/management/service.py`、`src/management/web/app.js`；`tests/test_web_workflow.py` |
| 草稿与来源 | 草稿只存在页面内存，刷新、离开、切换来源前提醒；保存其他厂商保留草稿。独立管理与 CC Switch 只读同步保留各自数据，不回写 CC Switch 数据库 | `src/management/web/app.js`、`src/model_catalog/sources.py`；`tests/test_web_source.cjs`、`tests/test_web_workflow.py` |
| 切换确认 | 开关每次预览并确认；进程运行或检测未知为提示，确认后可继续；预览版本绑定配置与索引，提交时复核；取消不写配置或补索引 | `src/management/service.py`、`src/management/web/app.js`；`tests/test_management_routing.py` |
| 配置恢复 | 开启保存可信基线；关闭只恢复所管理的路由字段，保留字段原先不存在的状态、无关修改及根级 model。不支持 profile 或其他 provider；缺少可信基线或托管字段冲突停止写入 | `src/management/routing.py`；`tests/test_management_routing.py` |
| 桌面操作偏好 | 开启、关闭分别存入 `desktop-actions.json`，默认 ask，询问默认不勾选，可设 auto 或 never；自动选项仍需本次切换确认 | `src/management/service.py`、`src/management/web/app.js`；`tests/test_desktop_client.py` |
| 操作顺序与失败 | 选择重启时先尝试正常退出，再重新规划索引并复核配置；退出失败仍尝试切换；配置失败不启动。配置成功后仅启动一次，开启可启动未运行的应用，关闭不启动未运行的应用 | `src/management/service.py`；`tests/test_desktop_client.py` |
| Windows | 识别 Store 桌面安装；通过 Restart Manager 按 PID 与创建时间验证目标及影响范围，后台正常退出；不模拟按键，不强杀。退出请求成功后最多再等待 12 秒；启动最多等待 20 秒确认窗口 | `src/desktop/windows_client.py`、`src/desktop/windows_restart_manager.py`；`tests/test_windows_client.py`、`tests/test_windows_restart_manager.py` |
| macOS | 标准目录及 Spotlight 查找并验证 Codex.app，Apple events 请求正常退出，Launch Services 启动；权限拒绝或超时提示手动处理。启动只确认主进程出现 | `src/desktop/macos_client.py`；`tests/test_macos_client.py` |
| 自动操作范围 | 仅本机可识别且状态可读的默认 Codex 数据目录对应桌面应用；自定义 CODEX_HOME、未知状态或未识别安装走手动处理。CLI/VS Code 自行重启；不计划提供应用路径选择界面 | `src/desktop/client.py`、两个平台后端、`src/management/web/app.js` |
| 状态反馈 | 接入开关表示磁盘配置；分别报告桌面操作结果，不验证客户端加载、不维护待重启或手动确认加载状态 | `src/management/web/app.js`、`src/management/service.py` |
| 活动观测 | 每秒读取官方和第三方网关未结束请求及流，不含管理页连接测试；仅内存保存。按桌面/CLI/VS Code 展示进程，权限不足显示未知；仅检测客户端进程是否运行，不探测任务状态，零请求不代表空闲 | `src/gateway/activity.py`、`src/desktop/process_state.py`；`tests/test_gateway_activity.py`、`tests/test_process_state.py` |
| 日志诊断 | 分类显示最近 24 小时、7 天、30 天或全部保留日志；扫描运行、错误、启动日志及保留的轮转文件，替代旧的末尾 128 KiB / 20 条规则；旧日志时间采用修改时间并标注，页面用本地时区显示 | `src/management/diagnostics.py`、`src/management/web/app.js`；`tests/test_management_diagnostics.py` |
| 隐私与保留 | 运行及错误日志各 2 MiB、3 份旧文件；启动错误文件每次启动重建。JSON 诊断按白名单生成，不导出原始消息、配置或日志，不自动上传；轮转清理后的历史无法恢复 | `src/gateway/runtime_log.py`、`src/management/diagnostics.py`；`tests/test_runtime_log.py`、`tests/test_management_diagnostics.py` |

## 会话索引属于切换业务的一部分

先前桌面方案只写路由配置事务，需同时纳入现有索引规则：

- 只处理所选 Codex 数据目录的本机会话索引，包括归档和子会话；不改 `.jsonl` / `.jsonl.zst` 历史、历史模型或分页缓存。
- 开启将索引线路改为 `codex-hybrid`，保留模型；关闭改为 `openai`，官方模型保留，第三方模型替换为目录中首个可用官方模型。官方身份按 `official_models` 判断，未设置的模型仍不设置；再次开启不自动恢复被替换的第三方模型。
- 接入配置不选择或覆盖根级 `model`，不存在可指定的迁移默认模型。缺少官方名单或必要回退模型时停止。
- 预览不启动辅助进程。确认后仅在缺少索引时调用独立 Codex app-server 的 `thread/read` 补齐元数据；不 resume、不生成，使用临时认证存储并阻止 HTTP 联网。这与观察桌面真实任务状态是两种能力，不能相互替代。
- 网页对结构不兼容、路径不安全、会话 ID 冲突或无法识别无索引元数据等指定错误，警告后跳过全部索引迁移，仍应用配置；不做部分迁移。CLI 保持严格。官方模型校验、索引补齐、预览校验、备份及实际写入错误不降级。
- 配置、恢复元数据和索引构成可恢复事务；备份位于 `session-migrations/<ID>/`，不自动清理。普通写入失败回滚，中断状态阻止后续切换；恢复仍须退出 Codex，通过现有 CLI 操作，不计划提供网页迁移恢复向导。
- 索引补齐可能先更新 Codex 元数据库；后续失败不删除已经补齐的索引。迁移警告显示在预览和结果，并在确认应用时尝试写入轮转警告日志；取消不写日志。

证据：`src/desktop/session_migration.py`、`src/desktop/codex_index.py`、`tests/test_session_migration.py`、`tests/test_codex_index.py`。完整操作和恢复边界见[会话迁移](../../docs/zh-CN/session-migration.md)。

## 与桌面目标的边界

本次用户已确认桌面开关沿用 demo 的可选启动/重启与失败规则，替代原方案“必须重启成功才算切换完成”。不因桌面退出失败回滚已成功的配置，也不把配置成功当作客户端已加载。

2026-10-28 后续实现：管理与转发已分成独立监听，通过不依赖 Gateway 实例的 ManagementContext 复用配置和连接测试；增加服务所有权、操作及 CLI 控制锁，并保护同一 Codex 目录的迁移。用户已确认放弃任务状态探测，相关试验实现及页面提示已移除；检测到 Codex 桌面运行状态即满足此项目标，权限不足仍显示未知。详见[当前使用说明](../../docs/zh-CN/usage.md#独立管理服务与实例互斥)。

以下仍为桌面目标，不能标记已完成：Tauri 双平台打包、无 Python 环境运行、私有控制协议、双平台锁实机验收、托盘，以及桌面关闭窗口、退出与异常恢复的生命周期实机验收。目前网页管理已监督独立网关子进程并支持异常退出后的恢复入口，尚无 Tauri 私有桌面控制协议。

关闭接入后网页继续运行管理服务；转发仅在无活动请求且进程检测为未运行时停止，否则保留。桌面版未来停止网关或退出应用时，仍需确认运行中的客户端不会继续依赖旧网关；无法确认时保留服务及恢复入口。停服条件与具体交互留待桌面阶段验证，不推翻本次已确认的可选桌面操作规则。

阶段 0 的 Windows 探针结果保留历史语境；新增 macOS 后端、索引事务和自动化测试不能代替 Tauri 编译、双平台打包实机或真实 Codex 正常重启验收。

2026-10-28 范围调整：冲突字段展示与可视化修复、网页迁移恢复向导、手动选择并记住应用位置已从后续计划移除；现有冲突拦截、迁移事务及 CLI 恢复保留。网关故障处理方案随后已确认并实现于网页业务层，规则见下节。

## 网页网关故障恢复（2026-10-28）

- 管理进程与网关子进程隔离；管理进程监督自己创建的子进程，通过私有进程管道接收就绪与日志事件，共享仅内存的活动计数。转发监听不提供管理接口。
- 仅网关进程意外退出触发自动重启，等待 1、3、10 秒，最多 3 次；连续运行满 60 秒后发生的新崩溃重新计算额度。启动失败（包括端口占用、配置错误）停止重试；主动停止、上游请求错误和健康检查超时不触发自动重启。
- 页面展示恢复中、重试次数和预计时间；失败后可手动重试或经原有确认流程恢复原生配置。不重放中断请求，不自动重启 Codex。
- 管理服务重新启动时，已有接入配置进入等待恢复，不自动启动网关；用户选择恢复接入或恢复原生配置。迁移中断仍通过现有 CLI 恢复，不增加备份恢复向导。
- 父进程退出使私有管道关闭，子进程退出；网关下一轮请求读取已提交的配置，保留配置热更新。
- 自动化覆盖网关崩溃重启、重试耗尽、主动停止、父进程退出、重启后的恢复入口、端口冲突及配置更新。双平台安装与打包实机验收仍未完成。

## 2026-10-29 可靠性修复

- macOS 使用 kqueue 监听 CC Switch，修复 FSEvents 合并 WAL 写入通知导致实时同步测试超时的问题；保留通知失败时的定期同步，不把 SHM 读取当作配置更新。
- 网关启动期间发布独立状态快照，状态查询不等待生命周期锁；路由开启与手动恢复不在创建子进程时持有配置锁，提交前重新校验版本。
- 就绪等待 10 秒、CLI 控制等待 15 秒，避免慢启动时 CLI 提前误报失败。
- 页面与白名单诊断提供固定启动故障类别，不展示原始异常消息。
- 本轮 Python 全量 252 项测试通过（2 项平台相关跳过），网页逻辑测试 17 项通过。本机浏览器控制被设置禁用，未完成真实浏览器验证；Windows/macOS 真实 Codex 正常重启及双平台安装验收仍待专门测试。


## 2026-10-29 桌面操作与日志阻塞修复

- 桌面退出、安装发现及启动等待移出配置锁；路由切换单独互斥，其他页面重复或反向提交返回 `INSTANCE_BUSY`。退出后重新核对配置并规划会话索引，外部配置变化仍停止写入和启动。
- 状态及活动接口增加 `routing_operation`：空闲为 `null`，进行中为 `{mode, phase}`；`phase` 为 `preparing`、`closing`、`applying` 或 `launching`。页面在切换期间每秒查询活动接口，单次查询未完成时不叠加请求，并显示阶段；已完成后的迟到响应不回写进度。
- 网关日志发送与父进程日志落盘均通过有界后台队列，每侧 256 条、单条最多 16 KiB；满队列丢弃新记录，并统计已知写入失败。`forwarding.log_dropped_records` 随管理服务累计，不随子进程重启清零；页面和诊断可查看。每轮监督最多读取 64 条，退出排空最多等待 0.2 秒，避免日志拖住监督、停服和请求线程。
- 回归覆盖退出/启动等待时状态可读、并发切换拒绝、配置失败后释放互斥、磁盘写入阻塞时崩溃恢复和停止、真实 IPC 管道积压下 450 次错误请求不堆积线程，以及网页进度和日志丢弃提示。未对真实 Codex 执行退出/启动；本机浏览器控制仍被 Work 设置禁用，真实浏览器与双平台生命周期验收仍未完成。

验证结果：当前工作区 Python 全量 273 项（271 通过、2 项平台相关跳过），网页逻辑 23 项通过，JavaScript 语法、Python 编译及 diff 空白检查通过。升级后需重启管理服务生效；本轮未操作实际运行中的服务或 Codex。
