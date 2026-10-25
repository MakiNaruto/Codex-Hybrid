"""Codex Model Bridge command line entry point."""
import subprocess
import sys


def main():
    wizard = len(sys.argv) == 1 or sys.argv[1] == 'install'
    if wizard and len(sys.argv) > 1:
        del sys.argv[1]
    try:
        if len(sys.argv) > 1 and sys.argv[1] == 'config':
            from desktop.preferences import configure
            return configure(sys.argv[2:])
        if wizard:
            from cli.setup_wizard import main as run
        else:
            from desktop.service import main as run
        return run()
    except (ValueError, OSError, StopIteration, subprocess.CalledProcessError) as error:
        from cli.diagnostics import report_error
        report_error(error, '安装未完成' if wizard else '命令执行失败')
        return 1
    except (KeyboardInterrupt, EOFError):
        print('Cancelled.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
