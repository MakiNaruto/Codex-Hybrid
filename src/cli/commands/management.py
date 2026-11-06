"""Authenticated management link operations."""
import json

from infrastructure.files import write_snapshot_bytes as private_write
from codex_integration import service_lifecycle as lifecycle


def run(args, runtime, state, settings):
    if args.management_auth is not None:
        lifecycle.stop_service(missing_ok=True, runtime=runtime)
        from codex_integration.locking import DirectoryLock
        with DirectoryLock(runtime):
            settings = json.loads((runtime / 'settings.json').read_text(encoding='utf-8'))
            settings['management_auth_required'] = args.management_auth == 'on'
            private_write(runtime / 'settings.json', json.dumps(settings))
        lifecycle.start_service(settings, runtime=runtime)
        # Gateway startup may have generated the management token.
        settings = json.loads((runtime / 'settings.json').read_text(encoding='utf-8'))
    lifecycle.health(settings)
    token = settings.get('management_token') if settings.get('management_auth_required', False) else ''
    if settings.get('management_auth_required', False) and not token:
        raise ValueError('Restart the gateway to enable its management page')
    from management.runtime import management_port
    print(json.dumps({'url': f'http://127.0.0.1:{management_port(settings)}/manage/{"#" + token if token else ""}'}))
    return
