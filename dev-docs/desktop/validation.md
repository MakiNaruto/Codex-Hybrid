# 桌面验证

命令从仓库根目录执行，使用已安装项目依赖的目标架构 Python。验证报告是当前运行的证据，历史通过数量保留在原始记录中。

## 源码与冻结检查

```sh
.venv/bin/python -X utf8 desktop/validation/preflight.py
.venv/bin/python -X utf8 desktop/validation/verify.py --output desktop/build/stage0/source-results.json
.venv/bin/python desktop/tests/test_tray_lifecycle.py
```

Windows 使用 `.venv/Scripts/python.exe`。`preflight.py` 用于只读环境与进程盘点。验证夹具使用临时配置和模拟上游，需回环监听权限。`desktop/validation/audit_config.py` 的配置往返检查使用临时数据，执行前核查入口边界。

先按平台指南打包，再验证冻结程序。例如 Intel macOS。

```sh
.venv/bin/python -X utf8 desktop/validation/verify.py --executable desktop/dist/stage0/hybrid-stage0-probe-x86_64-apple-darwin --output desktop/build/stage0/frozen-results-macos-x86_64.json
```

Windows 冻结程序路径为 `desktop/dist/stage0/windows-x86_64/hybrid-stage0-probe.exe`，Cargo 检查需 MSVC x64 环境。平台构建脚本还执行产物内检查。冻结验证复制运行时资源、限制 Python 搜索环境，但宿主机仍安装 Python，干净机器验收需另外执行。

## 验收矩阵

| 层次 | 需记录的内容 |
| --- | --- |
| 源码 | 命令、源码版本、日期、通过和跳过项 |
| 平台模拟 | 模拟目标与宿主平台，涉及分支 |
| 原生构建 | 操作系统、架构、编译器和依赖版本 |
| 冻结运行 | sidecar、真实本地 worker、包内资源及退出清理 |
| 原生交互 | 托盘点选、焦点、隐藏、草稿和网关保留、取消、退出 |
| 安装实机 | 无 Python/Git/源码环境、更新保留数据、安全提示与恢复 |

Windows、Intel macOS 和 Apple Silicon 分开登记。真实 Codex 启停在专门测试会话执行，避免关闭承载开发任务的实例。连接测试使用模拟上游，实际产品连接测试会访问供应商并可能计费。

## 原始证据

- [阶段验证记录](../archive/desktop/stage0-validation.md)保留各轮 Intel 实测及限制。
- [开发交接](../archive/desktop/handoff-history.md)保留冻结 worker、原生窗口补充及 2026-11-05 Windows 增量。
- [页面对齐记录](../archive/desktop/web-desktop-alignment-history.md)保留平台共享与差异验证。

本轮迁移后已执行 Intel Cargo 编译与源码、冻结、应用内隔离验证，结果见[当前状态矩阵](status.md#本轮验证矩阵)。历史记录继续保留原日期与范围，日志可能已清理，可按当前入口重新生成。

## 数据与诊断检查

日志诊断按最近 24 小时、7 天、30 天或全部保留范围读取运行、错误、启动及轮转日志。旧日志采用文件修改时间并标记，界面按本地时区显示。运行与错误日志各限制 2 MiB 并保留三份旧文件，启动错误日志每次启动重建。轮转清理后的历史无法恢复。

诊断导出按字段白名单剔除 Key、认证头、令牌、聊天正文和工具参数，保留可定位的安全错误分类。验证导出内容与页面读取范围，避免原始配置/日志整体打包后依赖字符串替换。导出在本地，由用户自行分享。

## 阶段完成标准

| 阶段 | 验收能力 |
| --- | --- |
| 0 技术风险 | 目标无系统 Python 环境启动、资源与编码路径、正常识别/退出/启动、互斥、冲突与私有协议 |
| 1 管理与运行 | 空模型管理、显式接入才监听、端口冲突、重复实例、崩溃重试、控制进程异常、CLI 与数据兼容 |
| 2 路由与恢复 | 取消、未知状态、未运行开启/关闭差异、退出受阻、启动失败、配置冲突与异常关机残留 |
| 3 界面与托盘 | 无终端完成配置、测试、目录发布、接入、重启、故障恢复，统一预览与处理中反馈 |
| 4 安装与持续运行 | 分平台安装、升级、旧数据、多窗口、并发流式、工具/子任务、网络异常、持续运行和轮转 |

各阶段用当前源码重新执行并记录版本。早期计划里“忙碌检测”按后续决策解释为活动和客户端运行提示，任务状态探测已取消。

## 网页与 Rust 拆分回归

```sh
node --test tests/*.cjs
CARGO_HOME="$PWD/desktop/build/stage0/cargo-home" CARGO_TARGET_DIR="$PWD/desktop/build/stage0/tauri-target" cargo test --offline --locked --manifest-path desktop/src-tauri/Cargo.toml --features custom-protocol --bin hybrid-stage0-shell
```

Node 最终 94 项覆盖原行为与新增模块加载、实际脚本顺序的模拟 DOM 初始化和草稿/状态接口。Intel Rust 四项覆盖托盘状态、超时与固定命令注册。HTTP 静态脚本和只读 API 检查是服务入口验证，真实浏览器本轮因 Work 设置 disabled 未能执行，页面和托盘交互仍需实机验收。
