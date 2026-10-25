"""CLI diagnostics without dumping credentials, command arguments or config excerpts."""
import json
import subprocess
import sys
import tomllib


def report_error(error, context='操作失败'):
    import desktop.service as desktop

    print(f'{context} [{type(error).__name__}]', file=sys.stderr)
    if isinstance(error, subprocess.CalledProcessError):
        print(f'  子命令退出码：{error.returncode}；具体原因见上方子命令诊断。', file=sys.stderr)
    elif isinstance(error, json.JSONDecodeError):
        print(f'  JSON 格式错误：第 {error.lineno} 行，第 {error.colno} 列。', file=sys.stderr)
    elif isinstance(error, tomllib.TOMLDecodeError):
        print('  TOML 格式错误，请检查 Codex config.toml。', file=sys.stderr)
    elif isinstance(error, OSError):
        reason = getattr(error, "reason", None)
        if isinstance(reason, OSError):
            error = reason
        print(f'  系统错误：errno={error.errno}，{error.strerror or "系统操作失败"}', file=sys.stderr)
        if error.filename:
            print(f'  文件：{error.filename}', file=sys.stderr)
    elif isinstance(error, ValueError):
        # Project ValueErrors contain fixed messages or catalog error codes.
        # Parser subclasses can contain source excerpts and must stay hidden.
        from model_catalog.catalog import ConfigError
        if type(error) is ValueError or isinstance(error, ConfigError):
            print('  原因：' + str(error), file=sys.stderr)
    elif isinstance(error, StopIteration):
        print('  未找到所需条目，请检查模型和运行状态。', file=sys.stderr)
    print(f'  数据目录：{desktop.RUNTIME}', file=sys.stderr)
    for name in ('service.stderr', 'service.jsonl'):
        path = desktop.RUNTIME / name
        print(f'  日志：{path}' + ('' if path.exists() else '（尚未创建）'), file=sys.stderr)
