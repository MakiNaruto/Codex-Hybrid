# 桌面化方案与验证

本目录集中保存 Codex Hybrid 桌面化的计划、验证记录、原型及本地构建产物。当前处于阶段 0，尚未完成双平台验证或进入生产桌面功能开发。

- [实施计划](docs/plan.md)：已确认的产品范围、生命周期、实施阶段和验收标准。
- [网页与桌面对齐](docs/web-desktop-alignment.md)：当前 demo 规则、代码证据及桌面未完成边界。
- [阶段 0 验证记录](docs/stage0-validation.md)：实测结果、已发现问题与尚未验证的能力。
- [阶段 0 工具说明](stage0/README.md)：Python 探针、Windows/macOS 复现命令与 Tauri 最小窗口。

```text
desktop/
├─ docs/          方案与验证记录
├─ stage0/        隔离验证脚本、Tauri 骨架和验证页面
├─ build/         本地工具依赖、缓存和结构化验证结果（忽略提交）
└─ dist/          打包验证产物（忽略提交）
```

命令示例默认从仓库根目录执行。验证脚本仍复用根目录 `src/` 下的现有业务代码；不会复制一套业务内核到本目录。
