"""Dispatch CLI command families with an explicit runtime directory."""
import json

from codex_integration import installation
from codex_integration.session_migration import cleanup_completed_records
from cli.commands import management, models, routing, service, sessions


def run(args, runtime):
    cleanup_completed_records(runtime)
    if args.action in ('reset-session-baseline', 'recover-sessions'):
        return sessions.run(args, runtime)
    args.models_config = args.models_config or runtime / 'models.yaml'
    if args.action == 'prepare':
        if not 1024 <= args.port <= 65535:
            raise ValueError('Invalid unprivileged port')
        source = {'type': args.source or 'yaml', 'path': str((
            args.cc_db if args.source == 'cc-switch' else args.models_config).expanduser().resolve())}
        return installation.prepare(args.port, args.codex_home, source, directory=runtime)
    if not (runtime / 'state.json').is_file():
        raise ValueError(f'No initialized router in {runtime}; run install or prepare with the same --data-dir')
    state = json.loads((runtime / 'state.json').read_text())
    settings = json.loads((runtime / 'settings.json').read_text(encoding='utf-8'))
    if args.action == 'uninstall':
        if routing.uninstall(args, runtime, state, settings) is not False:
            return
        return routing.run(args, runtime, state, settings, uninstalling=True)
    handlers = {'manage-url': management.run, 'refresh-models': models.run,
                'start': service.run, 'restart': service.run, 'stop': service.run, 'status': service.run,
                'activate': routing.run, 'rollback': routing.run}
    return handlers[args.action](args, runtime, state, settings)
