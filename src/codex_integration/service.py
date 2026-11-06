#!/usr/bin/env python3
"""Public local-service API and CLI runtime selection."""
import subprocess

from infrastructure.files import write_snapshot_bytes
from codex_integration.configuration import (
    PROVIDER, digest, candidate_config, is_bridge_provider,
    remove_bridge_provider_table, retain_config_model,
)
from codex_integration.paths import (
    ROOT, RUNTIME, data_directory, environment_value, check_legacy_installation,
)
from codex_integration import installation
from codex_integration.installation import official_cache
from codex_integration import service_lifecycle as lifecycle
from codex_integration.service_lifecycle import health, ensure_forwarding_ready
from cli.commands.parser import ACTIONS, common_arguments, build_parser


def private_write(path, data):
    return write_snapshot_bytes(path, data)


def prepare(port, codex_home, source=None, *, directory=None, management_auth_required=False):
    runtime = directory if directory is not None else RUNTIME
    return installation.prepare(port, codex_home, source, directory=runtime,
                                management_auth_required=management_auth_required)


def start_service(settings):
    return lifecycle.start_service(settings, runtime=RUNTIME)


def stop_service(missing_ok=False):
    return lifecycle.stop_service(missing_ok, runtime=RUNTIME)


def owned_gateway_processes():
    return lifecycle.owned_gateway_processes(runtime=RUNTIME)


def stop_windows_process(pid, missing_ok=False):
    return lifecycle.stop_windows_process(pid, missing_ok, runtime=RUNTIME)


def migrate_routing(config_path, settings, state, data, activating, expected_current=None):
    from cli.commands.routing import migrate_routing as migrate
    return migrate(config_path, settings, state, data, activating, expected_current, runtime=RUNTIME)


def main():
    global RUNTIME
    args = build_parser().parse_args()
    if args.data_dir is not None or environment_value('DATA_DIR'):
        RUNTIME = data_directory(args.data_dir)
    check_legacy_installation(RUNTIME, explicit=args.data_dir is not None or bool(environment_value('DATA_DIR')))
    from codex_integration.locking import DirectoryLock
    mutation = args.action in {'prepare', 'refresh-models', 'activate', 'rollback', 'recover-sessions', 'reset-session-baseline'}
    with DirectoryLock(RUNTIME, 'operation.lock' if mutation else 'control.lock'):
        return run_action(args)


def run_action(args):
    from cli.commands import run
    return run(args, RUNTIME)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, StopIteration, subprocess.CalledProcessError) as error:
        from cli.diagnostics import report_error
        report_error(error, '服务命令执行失败')
        raise SystemExit(1)
