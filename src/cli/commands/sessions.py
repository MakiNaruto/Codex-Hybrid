"""Explicit session recovery and baseline reset commands."""


def run(args, runtime):
    if args.action == 'reset-session-baseline':
        from codex_integration.session_migration import reset_baseline
        reset_baseline(args.codex_home.expanduser().resolve(), runtime)
        return print('基线已重置；下一次实际修改前将重新备份当前状态。')
    if args.action == 'recover-sessions':
        from codex_integration.session_migration import recover
        if not args.backup.resolve().is_relative_to((runtime / 'session-migrations').resolve()):
            raise ValueError('请指定本实例 session-migrations 下的备份目录。')
        recover(args.backup)
        return print('已恢复中断前的配置和会话。')
