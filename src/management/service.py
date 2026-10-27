"""Configuration-only management for the native gateway; no task runner or MCP."""
import copy
import hashlib
import hmac
import json
import os
import tomllib
from pathlib import Path
import secrets
import threading
import time
import urllib.request

import yaml

from model_catalog.sources import Catalog, ConfigError, load_source, merged_catalog, update_cc_snapshot
from model_catalog.catalog import identifier, read_yaml, string


def private_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.' + secrets.token_hex(8) + '.tmp')
    try:
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8', newline='') as out:
            out.write(value)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class Management:
    def __init__(self, gateway, settings_path, route, sse_events):
        self.gateway = gateway
        self.settings_path = Path(settings_path).resolve()
        self.directory = self.settings_path.parent
        self.route = route
        self.sse_events = sse_events
        self.lock = threading.RLock()
        self.revision_secret = secrets.token_bytes(32)
        self.sync_error = None
        self.sync_stop = threading.Event()
        self.sync_thread = None
        self.cc_catalog = None
        self.last_synced_at = None
        self.sync_mode = 'periodic'

    def cache_cc(self, catalog):
        self.cc_catalog = catalog
        self.last_synced_at = time.time()

    def sync_cc(self):
        """Replace the entire CC snapshot; a failed read never removes old entries."""
        with self.lock:
            settings = self.gateway.settings
            if settings['source']['type'] != 'cc-switch':
                self.sync_error = None
                return False
            try:
                external = load_source(settings)
                snapshot = settings.get('cc_snapshot', {})
                try:
                    directory = json.loads(Path(settings['catalog']).read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    directory = {}
                if (snapshot.get('revision') == external.source_revision
                        and snapshot.get('bindings') == external.bindings
                        and settings['models'] == [model['slug'] for model in snapshot.get('models', [])]
                        and directory.get('models') == snapshot.get('models')):
                    self.sync_error = None
                    if self.cc_catalog is None:
                        self.cache_cc(external)
                    return False
                self.publish(catalog=external)
                self.sync_error = None
                return True
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.sync_error = error.code if isinstance(error, ConfigError) else 'CC_SYNC_FAILED'
                return False

    def start_sync(self, interval=30):
        if self.sync_thread is not None and self.sync_thread.is_alive():
            return
        self.sync_stop.clear()
        self.sync_cc()

        def watch():
            from management.cc_watch import CCWatch
            watcher = None
            watched_path = None
            next_check = time.monotonic() + interval
            try:
                while not self.sync_stop.wait(min(0.1, interval)):
                    with self.lock:
                        source = self.gateway.settings['source']
                        path = source['path'] if source['type'] == 'cc-switch' else None
                    due = time.monotonic() >= next_check
                    if path != watched_path or (path and watcher is None and due):
                        if watcher is not None:
                            watcher.stop()
                        watcher = None
                        watched_path = path
                        self.sync_mode = 'periodic'
                        if path:
                            candidate = CCWatch(path)
                            try:
                                candidate.start()
                            except (ImportError, OSError, RuntimeError):
                                pass  # Keep the periodic safety net if notifications are unavailable.
                            else:
                                watcher = candidate
                                self.sync_mode = 'watch'
                        due = True  # Reconcile changes between startup/source switch and registration.
                    if due or (watcher is not None and watcher.ready()):
                        self.sync_cc()
                        next_check = time.monotonic() + interval
            finally:
                if watcher is not None:
                    watcher.stop()
                self.sync_mode = 'periodic'

        self.sync_thread = threading.Thread(target=watch, name='cc-switch-sync', daemon=True)
        self.sync_thread.start()

    def stop_sync(self):
        self.sync_stop.set()
        if self.sync_thread is not None:
            self.sync_thread.join(timeout=5)

    def routing_state(self):
        try:
            state = json.loads((self.directory/'state.json').read_text())
            config = tomllib.loads(Path(state['config_path']).read_text(encoding='utf-8'))
            if config.get('profile'):
                return 'unsupported'
            provider = config.get('model_provider', 'openai')
            from desktop.service import PROVIDER
            return 'project' if provider == PROVIDER else 'openai' if provider == 'openai' else 'unsupported'
        except (OSError, ValueError, KeyError):
            return 'unavailable'

    def routing_plan(self, mode):
        from management.routing import prepare
        state, path, current, baseline, result = prepare(self.directory, self.gateway.settings, mode)
        from desktop.session_migration import plan
        provider = 'codex-hybrid' if mode == 'project' else 'openai'
        migration = plan(path.parent, self.gateway.settings, provider, best_effort=True)
        revision = hmac.new(self.revision_secret,
            json.dumps([mode, str(path), state, current, baseline, result, migration['revision']]).encode(),
            hashlib.sha256).hexdigest()
        return state, path, current, baseline, result, migration, revision

    def preview_routing(self, mode):
        with self.lock:
            *_, migration, revision = self.routing_plan(mode)
            from desktop.process_state import codex_process_state
            process = codex_process_state(migration['home'])
            from desktop import client as desktop_client
            target = desktop_client.discover(migration['home'])
            desktop = {'available': bool(target), 'running': False, 'status': 'unavailable'}
            if target:
                try:
                    desktop.update(running=bool(desktop_client.processes(target)), status='known')
                except Exception:
                    desktop['status'] = 'unknown'
            ticket = hmac.new(self.revision_secret,
                              (revision + str(desktop['running'])).encode(), hashlib.sha256).hexdigest()
            return {'mode': mode, 'revision': revision, 'desktop': desktop, 'desktop_ticket': ticket,
                    'session_count': migration['count'], 'model_change_count': migration['model_change_count'],
                    'index_repair_count': len(migration['unindexed']) or migration['index_repair_count'],
                    'missing_rollouts': migration['missing_rollouts'],
                    'warnings': migration['warnings'],
                    'changes': [f"迁移 {migration['count']} 个本机会话索引",
                                f"需由 Codex 补齐 {len(migration['unindexed'])} 个索引；缺少历史文件的已有索引 {migration['missing_rollouts']} 条"],
                    'restart_client': True, 'activity': self.activity_state(), 'codex_process': process}

    def process_state(self):
        from desktop.process_state import codex_process_state
        try:
            state = json.loads((self.directory/'state.json').read_text())
            home = Path(state['config_path']).parent
        except (OSError, ValueError, KeyError, TypeError):
            return {'status': 'unknown', 'process_count': 0, 'clients': {}, 'observed_at': None}
        return codex_process_state(home)

    def activity_state(self):
        activity = getattr(self.gateway, 'activity', None)
        return activity.snapshot() if activity is not None else {
            'active_requests': None, 'observed_at': None,
            'gateway_status': 'unknown', 'codex_status': 'unknown'}

    def desktop_preferences(self):
        try:
            saved = json.loads((self.directory/'desktop-actions.json').read_text())
        except (OSError, ValueError):
            saved = {}
        return {mode: saved.get(mode, 'ask') if saved.get(mode) in {'ask', 'auto', 'never'} else 'ask'
                for mode in ('project', 'openai')}

    def save_desktop_preferences(self, mode, value):
        if mode not in {'project', 'openai'} or value not in {'ask', 'auto', 'never'}:
            raise ConfigError('INVALID_DESKTOP_PREFERENCE')
        with self.lock:
            preferences = self.desktop_preferences()
            preferences[mode] = value
            private_write(self.directory/'desktop-actions.json', json.dumps(preferences))
            return {'saved': True, 'desktop_preferences': preferences}

    def set_routing(self, mode, revision=None, confirm_activity=False, desktop_action=False,
                    desktop_was_running=False, desktop_ticket=None):
        from desktop import client as desktop_client
        if type(desktop_action) is not bool or type(desktop_was_running) is not bool:
            raise ConfigError('INVALID_DESKTOP_ACTION')
        if type(confirm_activity) is not bool:
            raise ConfigError('INVALID_ACTIVITY_CONFIRMATION')
        with self.lock:
            before = self.routing_plan(mode)
            if not isinstance(revision, str) or not hmac.compare_digest(revision, before[-1]):
                raise ConfigError('CLIENT_CONFIG_CHANGED')
            target, outcome, should_launch = None, 'manual', False
            desktop_error = None
            if desktop_action:
                ticket = hmac.new(self.revision_secret,
                                  (revision + str(desktop_was_running)).encode(), hashlib.sha256).hexdigest()
                if not isinstance(desktop_ticket, str) or not hmac.compare_digest(ticket, desktop_ticket):
                    raise ConfigError('INVALID_DESKTOP_ACTION')
                try:
                    target = desktop_client.discover(before[-2]['home'])
                    if target is None:
                        outcome = 'unavailable'
                    else:
                        running = bool(desktop_client.processes(target))
                        if running and not desktop_was_running:
                            outcome = 'state_changed'
                        elif running:
                            closed = desktop_client.close(target)
                            should_launch = bool(closed)
                            desktop_error = getattr(closed, 'reason', None) or None
                            outcome = 'closed' if should_launch else 'close_failed'
                        else:
                            should_launch = mode == 'project'
                            outcome = 'manual' if should_launch else 'not_running'
                except desktop_client.DesktopControlError as error:
                    outcome, should_launch = 'close_failed', False
                    desktop_error = str(error)
                except Exception:
                    outcome, should_launch = 'unknown', False
            # Closing may flush sessions. Replan those indexes, but never accept external config edits.
            after = self.routing_plan(mode)
            if before[:5] != after[:5]:
                raise ConfigError('CLIENT_CONFIG_CHANGED')
            result = self._apply_routing(mode, after[-1], confirm_activity)
            if should_launch:
                try:
                    outcome = desktop_client.launch(target)
                except Exception:
                    outcome = 'launch_unconfirmed'
            result['desktop_result'] = outcome
            result['desktop_error'] = desktop_error
            record = getattr(self.gateway, 'record', None)
            if record and desktop_action:
                try:
                    record({'status': 'desktop_operation', 'phase': 'desktop_control',
                            'routing_mode': mode, 'desktop_result': outcome, 'desktop_error': desktop_error})
                except OSError:
                    pass  # Logging failure must not turn an applied switch into an API failure.
            return result

    def _apply_routing(self, mode, revision=None, confirm_activity=False):
        with self.lock:
            if type(confirm_activity) is not bool:
                raise ConfigError('INVALID_ACTIVITY_CONFIRMATION')
            from desktop.service import digest
            controls = {self.directory/name: ((self.directory/name).read_bytes()
                        if (self.directory/name).exists() else None)
                        for name in ('state.json', 'original-config.toml', 'desktop-config.toml')}
            state, path, current, baseline, result, migration, expected = self.routing_plan(mode)
            if not isinstance(revision, str) or not hmac.compare_digest(revision, expected):
                raise ConfigError('CLIENT_CONFIG_CHANGED')
            if path.read_bytes().decode('utf-8') != current:
                raise ConfigError('CLIENT_CONFIG_CHANGED')
            from desktop.session_migration import apply, log_warnings
            updates = {}

            def update(file, value):
                file = Path(file)
                updates[file] = (controls[file], value.encode())

            # Routing config, recovery metadata and thread indexes form one recoverable operation.
            if mode == 'project':
                update(self.directory/'original-config.toml', baseline)
                state['original_sha256'] = digest(baseline.encode())
                update(self.directory/'desktop-config.toml', result)
                state['candidate_sha256'] = digest(result.encode())
            else:
                update(self.directory/'original-config.toml', result)
                state['original_sha256'] = digest(result.encode())
            state['activated'] = mode == 'project'
            update(self.directory/'state.json', json.dumps(state))
            updates[path] = (current.encode(), result.encode())
            warning_log = log_warnings(migration, self.directory)
            backup = apply(migration, self.directory, updates,
                           allow_running=confirm_activity)
            return {'saved': True, 'routing_mode': mode, 'restart_client': True,
                    'session_count': migration['count'], 'model_change_count': migration['model_change_count'],
                    'index_repair_count': len(migration['unindexed']) or migration['index_repair_count'],
                    'session_backup': backup, 'warnings': migration['warnings'],
                    'warning_log': warning_log}

    def official(self):
        settings = self.gateway.settings
        models = settings.get('cc_snapshot', {}).get('models')
        if models is None:
            models = json.loads(Path(settings['catalog']).read_text(encoding='utf-8'))['models']
        return [model for model in models
                if model['slug'] in settings['official_models']]

    def publish(self, source=None, catalog=None, extra=None):
        with self.lock:
            settings = copy.deepcopy(self.gateway.settings)
            if source is not None:
                settings['source'] = source
            if extra:
                settings.update(extra)
            external = catalog if catalog is not None else load_source(settings)
            merged = merged_catalog(self.official(), external)
            settings['models'] = [m['slug'] for m in merged['models']]
            update_cc_snapshot(settings, merged, external)
            keys = [key for key, value in external.models.items() if value['enabled']]
            if keys:
                settings['deepseek_model'] = keys[0]  # Historical smoke alias only.
            else:
                settings.pop('deepseek_model', None)
            catalog_path = Path(settings['catalog'])
            previous_catalog = (catalog_path.read_text(encoding='utf-8') if catalog_path.exists()
                                else json.dumps({'models': self.official()}, ensure_ascii=False))
            private_write(catalog_path, json.dumps(merged, ensure_ascii=False))
            try:
                # The directory and its explicit bindings share one durable snapshot.
                private_write(self.settings_path, json.dumps(settings, ensure_ascii=False))
            except OSError:
                private_write(catalog_path, previous_catalog)
                raise
            self.gateway.settings = settings  # Replace one snapshot; never mutate an in-flight request.
            self.sync_error = None
            if settings['source']['type'] == 'cc-switch':
                self.cache_cc(external)
            else:
                self.cc_catalog = None
                self.last_synced_at = None
            return {'saved': True, 'restart_client_for_model_list': True}

    def view(self):
        with self.lock:
            settings = self.gateway.settings
            source = settings['source']
            cc_path = settings.get('cc_db_path', str(Path.home()/'.cc-switch/cc-switch.db'))
            mode = 'cc_switch' if source['type'] == 'cc-switch' else 'independent'
            result = {'routing_mode': self.routing_state(), 'mode': mode, 'cc_db_path': source['path'] if mode == 'cc_switch' else cc_path,
                      'config': {'version': 1, 'providers': {}}, 'inventory': [], 'models': [],
                      'source_error': self.sync_error, 'sync_revision': None, 'catalog_pending': False,
                      'native_routing': True, 'official_model_count': len(settings['official_models']),
                      'credential_status': {}}
            result['last_synced_at'] = self.last_synced_at
            result['sync_mode'] = self.sync_mode
            result['desktop_preferences'] = self.desktop_preferences()
            if mode == 'cc_switch':
                catalog = self.cc_catalog
                if catalog is not None:
                    result['models'] = catalog.listing(True)
                    result['inventory'] = [{k: v for k, v in entry.items() if not k.startswith('_')}
                                           for entry in catalog.inventory]
                    result['credential_status'] = {key: 'available' for key in catalog.providers}
                    result['sync_revision'] = hmac.new(self.revision_secret,
                        catalog.source_revision.encode(), hashlib.sha256).hexdigest()
                return result
            try:
                catalog = load_source(settings)
                result['models'] = catalog.listing(True)
                from model_catalog.catalog import resolve_api_key
                for provider_id, provider in catalog.providers.items():
                    try:
                        resolve_api_key(provider)
                        result['credential_status'][provider_id] = 'available'
                    except (OSError, ValueError, TypeError):
                        result['credential_status'][provider_id] = 'missing'
                result['config'] = read_yaml(source['path'])
                for provider in result['config']['providers'].values():
                    provider['credentials'].pop('api_key', None)
                result['catalog_pending'] = merged_catalog(self.official(), catalog) != json.loads(
                    Path(settings['catalog']).read_text(encoding='utf-8'))
            except Exception as error:
                result['source_error'] = error.code if isinstance(error, ConfigError) else 'SOURCE_UNAVAILABLE'
            return result

    def set_source(self, mode, cc_db_path=None):
        with self.lock:
            settings = self.gateway.settings
            if mode not in {'independent', 'cc_switch'}:
                raise ConfigError('INVALID_SOURCE_MODE')
            current = settings['source']
            if mode == 'independent' and current['type'] == 'yaml':
                return {'saved': False, 'unchanged': True}
            db = None
            if mode == 'cc_switch':
                db = (cc_db_path or (current['path'] if current['type'] == 'cc-switch' else None)
                      or settings.get('cc_db_path') or str(Path.home()/'.cc-switch/cc-switch.db'))
                db = str(Path(string(db)).expanduser().resolve())
                if current['type'] == 'cc-switch' and Path(current['path']).resolve() == Path(db):
                    return {'saved': False, 'unchanged': True}
            standalone = settings.get('standalone_source')
            if current['type'] == 'yaml':
                standalone = current
            if standalone is None:
                standalone = {'type': 'yaml', 'path': str(self.directory / 'models.yaml')}
            if mode == 'independent':
                path = Path(standalone['path'])
                if not path.exists() and path.resolve() == (self.directory/'models.yaml').resolve():
                    managed = self.directory/'managed-models.yaml'
                    if managed.exists():
                        standalone = {'type': 'yaml', 'path': str(managed)}
                    else:
                        private_write(path, yaml.safe_dump({'version': 1, 'providers': {}}, sort_keys=False))
                return self.publish(standalone, extra={'standalone_source': standalone})
            return self.publish({'type': 'cc-switch', 'path': db}, extra={
                'cc_db_path': db, 'standalone_source': standalone})

    def save_provider(self, provider_id, spec=None, api_key=None, delete=False):
        identifier(provider_id)
        if type(delete) is not bool:
            raise ConfigError('INVALID_DELETE_FLAG')
        if api_key is not None and not isinstance(api_key, str):
            raise ConfigError('INVALID_API_KEY')
        with self.lock:
            settings = self.gateway.settings
            if settings['source']['type'] != 'yaml':
                raise ConfigError('CC_MODE_IS_READ_ONLY')
            source_path = Path(settings['source']['path'])
            raw = copy.deepcopy(read_yaml(source_path))
            if delete:
                if provider_id not in raw['providers']:
                    raise ConfigError('PROVIDER_NOT_FOUND')
                del raw['providers'][provider_id]
            else:
                if not isinstance(spec, dict):
                    raise ConfigError('INVALID_PROVIDER_SPEC')
                spec = copy.deepcopy(spec)
                old = raw['providers'].get(provider_id, {})
                env_name = ('CONNECTED_' + provider_id.upper().replace('-', '_').replace('.', '_') + '_'
                            + hashlib.sha256(provider_id.encode()).hexdigest()[:8].upper() + '_KEY')
                spec['credentials'] = old.get('credentials', {'api_key_env': env_name})
                if api_key:
                    string(api_key)
                    spec['credentials'] = {'api_key': api_key}
                raw['providers'][provider_id] = spec
            if raw.get('default_model'):
                provider, alias = raw['default_model'].split('/', 1)
                entry = raw['providers'].get(provider, {})
                if (not entry.get('enabled', True) or alias not in entry.get('models', {})
                        or not entry['models'][alias].get('enabled', True)):
                    raw.pop('default_model', None)
            for provider in raw['providers'].values():
                credentials = provider['credentials']
                if 'env_file' in credentials:
                    credentials['env_file'] = str((source_path.parent/Path(credentials['env_file']).expanduser()).resolve())
            target = self.directory/'managed-models.yaml'
            catalog = Catalog(target, data=raw)
            merged_catalog(self.official(), catalog)  # Validate publication before writing Key/config.
            private_write(target, yaml.safe_dump(raw, allow_unicode=True, sort_keys=False))
            return self.publish({'type': 'yaml', 'path': str(target)}, catalog=catalog,
                                extra={'standalone_source': {'type': 'yaml', 'path': str(target)}})

    def test_connection(self, key):
        began = time.monotonic()
        settings = self.gateway.settings
        if key in settings['official_models']:
            raise ConfigError('EXTERNAL_MODEL_REQUIRED')
        catalog = load_source(settings)
        if settings['source']['type'] == 'cc-switch':
            settings = copy.deepcopy(settings)
            # Test the selected live configuration without publishing a partial directory.
            settings['cc_snapshot'] = {'bindings': catalog.bindings}
        model, _ = catalog.select(key)
        if key not in settings['models']:
            # A one-off connection test may precede publishing a newly discovered CC model.
            settings = dict(settings, models=[*settings['models'], key])
        body = {'model': key, 'stream': True, 'max_output_tokens': min(model['max_output_tokens'] or 8192, 8192),
                'input': [{'role': 'user', 'content': [{'type': 'input_text', 'text': 'Reply with exactly hello and nothing else.'}]}]}
        if not self.gateway.slots.acquire(blocking=False):
            raise ConfigError('CONCURRENCY_LIMIT')
        try:
            url, payload, headers, adapt = self.route(body, {'Authorization': 'Bearer local-management-only'}, settings)
            request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
            with self.gateway.opener.open(request, timeout=60) as response:
                for event in self.sse_events(response):
                    events = adapt(event)
                    if not isinstance(events, list):
                        events = [] if events is None else [events]
                    for item in events:
                        if item.get('type') == 'response.incomplete':
                            reason = item.get('response', {}).get('incomplete_details', {}).get('reason')
                            raise ConfigError('UPSTREAM_OUTPUT_BUDGET_EXHAUSTED' if reason == 'max_output_tokens'
                                              else 'UPSTREAM_INCOMPLETE')
                        if item.get('type') == 'response.completed':
                            # Do not return arbitrary upstream content or errors to the browser.
                            return {'status': 'completed', 'model_key': key, 'model_id': model['model_id'],
                                    'elapsed_ms': round((time.monotonic() - began) * 1000)}
            raise ConfigError('UPSTREAM_STREAM_ENDED_EARLY')
        finally:
            self.gateway.slots.release()
