"""Configuration-only management for the native gateway; no task runner or MCP."""
import copy
import hashlib
import hmac
import json
import tomllib
from pathlib import Path
import secrets
import threading
import time

import yaml

from model_catalog.sources import (
    Catalog, ConfigError,
    import_current_cc_record, load_source, merged_catalog, source_key,
)
from model_catalog.catalog import identifier, read_yaml, string
from codex_integration.configuration import uses_openai_auth
from infrastructure.files import write_private_text


def private_write(path, value):
    return write_private_text(path, value)


class Management:
    def __init__(self, gateway, settings_path, route, sse_events):
        self.gateway = gateway
        self.settings_path = Path(settings_path).resolve()
        self.directory = self.settings_path.parent
        self.route = route
        self.sse_events = sse_events
        from codex_integration.locking import ConfigurationLock
        self.lock = ConfigurationLock(self)
        from codex_integration.session_migration import cleanup_completed_records
        with self.lock:
            cleanup_completed_records(self.directory)
        self.revision_secret = secrets.token_bytes(32)
        self.sync_error = None
        from management.synchronization import CCSyncWatcher
        self._sync_watcher = CCSyncWatcher(self.gateway, self.lock, lambda: self.sync_cc())
        self.sync_stop = self._sync_watcher.stop_event
        self.cc_catalog = None
        self.last_synced_at = None
        self.routing_lock = threading.Lock()
        self.routing_operation = None
        self.desktop_records = None

    def cache_cc(self, catalog):
        self.cc_catalog = catalog
        self.last_synced_at = time.time()

    def sync_cc(self):
        """Replace the entire CC snapshot; a failed read never removes old entries."""
        with self.lock:
            settings = self.gateway.settings
            repaired = False
            try:
                codex_config = self.current_codex_config()
                official_models_enabled = (
                    uses_openai_auth(codex_config) if codex_config is not None
                    else settings.get('official_models_enabled', True)
                )
                official = self.official() if official_models_enabled else []
                try:
                    current = json.loads(Path(settings['catalog']).read_text(encoding='utf-8'))['models']
                    previous = [model for model in current if model['slug'] in settings['official_models']]
                except (OSError, ValueError, KeyError, TypeError):
                    previous = None
                stored_official_enabled = settings.get('official_models_enabled')
                if (official != previous
                        or (stored_official_enabled is not None
                            and stored_official_enabled != official_models_enabled)):
                    self.publish()
                    repaired = True
                    settings = self.gateway.settings
            except (OSError, ValueError, KeyError, TypeError):
                # Codex can be replacing its cache; retain the last complete directory.
                return False
            if settings['source']['type'] != 'cc-switch':
                self.sync_error = None
                return repaired
            try:
                external = load_source(settings)
                snapshot = settings.get('cc_snapshot', {})
                try:
                    directory = json.loads(Path(settings['catalog']).read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    directory = {}
                import_required = False
                if codex_config is not None:
                    preferences = copy.deepcopy(settings.get('model_preferences', {}).get(
                        source_key(settings['source']), {'added': [], 'compatibility': {}}))
                    import_required = import_current_cc_record(external, preferences, codex_config)
                if (snapshot.get('revision') == external.source_revision
                        and snapshot.get('bindings') == external.bindings
                        and settings['models'] == [model['slug'] for model in snapshot.get('models', [])]
                        and directory.get('models') == snapshot.get('models')
                        and not import_required):
                    self.sync_error = None
                    if self.cc_catalog is None:
                        self.cache_cc(external)
                    return repaired
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
        with self.lock:
            try:
                self.publish()
            except ConfigError as error:
                # Keep management available so the page can explain why the
                # authoritative Codex configuration cannot be imported.
                self.sync_error = error.code
        self.sync_cc()

        self._sync_watcher.start(interval)

    @property
    def sync_thread(self):
        return self._sync_watcher.thread

    @property
    def sync_mode(self):
        return self._sync_watcher.mode

    def stop_sync(self):
        self._sync_watcher.stop()

    def close(self):
        self.stop_sync()
        if self.desktop_records is not None:
            self.desktop_records.close()

    def routing_state(self):
        return self._routing_status()[0]

    def routing_interrupted(self):
        return self._routing_status()[1]

    def _routing_status(self):
        try:
            state = json.loads((self.directory/'state.json').read_text())
            config = tomllib.loads(Path(state['config_path']).read_text(encoding='utf-8'))
            if config.get('profile'):
                return 'unsupported', bool(state.get('activated'))
            provider = config.get('model_provider', 'openai')
            from codex_integration.configuration import PROVIDER
            if provider == PROVIDER:
                return 'project', False
            if provider == 'openai':
                return 'openai', bool(state.get('activated'))
            source = self.gateway.settings.get('source', {})
            catalog = self.cc_catalog
            if source.get('type') == 'cc-switch' and catalog is not None:
                try:
                    from model_catalog.cc_switch import match_current_record
                    match_current_record(catalog.inventory, config)
                except ConfigError:
                    pass
                else:
                    return 'external', bool(state.get('activated'))
            return 'unsupported', bool(state.get('activated'))
        except (OSError, ValueError, KeyError, TypeError):
            return 'unavailable', False

    def current_codex_config(self):
        try:
            state = json.loads((self.directory/'state.json').read_text())
        except FileNotFoundError:
            return None
        try:
            return tomllib.loads(Path(state['config_path']).read_text(encoding='utf-8'))
        except (OSError, ValueError, KeyError, TypeError):
            raise ConfigError('CLIENT_ROUTING_UNAVAILABLE') from None

    @staticmethod
    def external_codex_config(config):
        from management.use_cases.catalog import external_codex_config
        return external_codex_config(config)

    def routing_plan(self, mode):
        from codex_integration.routing import plan
        return plan(self.directory, self.gateway.settings, mode, self.revision_secret)

    def preview_routing(self, mode):
        with self.lock:
            if mode == 'project':
                from codex_integration.routing import validate_baseline
                validate_baseline(self.directory, self.gateway.settings)
                self.publish()
            *_, migration, revision = self.routing_plan(mode)
            process = self.process_state()
            from codex_integration import client as desktop_client
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
        from codex_integration.process_state import codex_process_state
        try:
            state = json.loads((self.directory/'state.json').read_text())
            home = Path(state['config_path']).parent
        except (OSError, ValueError, KeyError, TypeError):
            return {'status': 'unknown', 'process_count': 0, 'clients': {}, 'observed_at': None}
        return codex_process_state(home)

    def activity_state(self):
        activity = getattr(self.gateway, 'activity', None)
        result = activity.snapshot() if activity is not None else {
            'active_requests': None, 'observed_at': None,
            'gateway_status': 'unknown', 'codex_status': 'unknown'}
        runtime = getattr(self.gateway, 'runtime', None)
        if runtime is not None:
            result['forwarding'] = runtime.snapshot()
        result['routing_operation'] = self.routing_operation
        return result

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
        if type(desktop_action) is not bool or type(desktop_was_running) is not bool:
            raise ConfigError('INVALID_DESKTOP_ACTION')
        if type(confirm_activity) is not bool:
            raise ConfigError('INVALID_ACTIVITY_CONFIRMATION')
        # Serialize switches, including OS waits, without blocking configuration reads.
        if not self.routing_lock.acquire(blocking=False):
            raise ConfigError('INSTANCE_BUSY')
        self.routing_operation = {'mode': mode, 'phase': 'preparing'}
        try:
            return self._set_routing(mode, revision, confirm_activity, desktop_action,
                                     desktop_was_running, desktop_ticket)
        finally:
            self.routing_operation = None
            self.routing_lock.release()

    def _set_routing(self, mode, revision, confirm_activity, desktop_action,
                     desktop_was_running, desktop_ticket):
        from codex_integration import client as desktop_client
        with self.lock:
            before = self.routing_plan(mode)
            if not isinstance(revision, str) or not hmac.compare_digest(revision, before[-1]):
                raise ConfigError('CLIENT_CONFIG_CHANGED')
            if desktop_action:
                ticket = hmac.new(self.revision_secret,
                                  (revision + str(desktop_was_running)).encode(), hashlib.sha256).hexdigest()
                if not isinstance(desktop_ticket, str) or not hmac.compare_digest(ticket, desktop_ticket):
                    raise ConfigError('INVALID_DESKTOP_ACTION')
            runtime = getattr(self.gateway, 'runtime', None)
        if mode == 'project' and runtime is not None:
            runtime.start()
        with self.lock:
            # Reject config/index edits made during forwarding startup, before touching Codex.
            before = self.routing_plan(mode)
            if not hmac.compare_digest(revision, before[-1]):
                raise ConfigError('CLIENT_CONFIG_CHANGED')
        target, outcome, should_launch = None, 'manual', False
        desktop_error = None
        if desktop_action:
            self.routing_operation = {'mode': mode, 'phase': 'closing'}
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
        self.routing_operation = {'mode': mode, 'phase': 'applying'}
        with self.lock:
            # Closing can flush indexes. Accept those changes, but never external config edits.
            after = self.routing_plan(mode)
            if before[:5] != after[:5]:
                raise ConfigError('CLIENT_CONFIG_CHANGED')
            result = self._apply_routing(mode, after[-1], confirm_activity)
        if should_launch:
            self.routing_operation = {'mode': mode, 'phase': 'launching'}
            try:
                outcome = desktop_client.launch(target)
            except Exception:
                outcome = 'launch_unconfirmed'
        if mode == 'openai' and runtime is not None:
            with self.lock:
                try:
                    result['forwarding_retained'] = not runtime.stop_if_safe(self)
                except (OSError, ValueError):
                    result['forwarding_retained'] = True
        result['desktop_result'] = outcome
        result['desktop_error'] = desktop_error
        if desktop_action:
            if runtime is not None:
                records = runtime.records
            else:
                # Compatibility for a standalone Gateway management listener.
                # Routing serialization also protects this lazy initialization.
                if self.desktop_records is None:
                    from infrastructure.runtime_log import AsyncRecords
                    self.desktop_records = AsyncRecords(self.gateway.record)
                records = self.desktop_records
            records.emit({'time': time.time(), 'status': 'desktop_operation', 'phase': 'desktop_control',
                          'routing_mode': mode, 'desktop_result': outcome, 'desktop_error': desktop_error})
        return result

    def _apply_routing(self, mode, revision=None, confirm_activity=False):
        from codex_integration.routing import commit
        with self.lock:
            return commit(self.directory, self.gateway.settings, mode, self.revision_secret,
                          revision, confirm_activity)

    def official(self):
        settings = self.gateway.settings
        if isinstance(settings.get('official_catalog'), list):
            return settings['official_catalog']
        state_path = self.directory / 'state.json'
        if state_path.exists():
            from codex_integration.service import official_cache
            state = json.loads(state_path.read_text(encoding='utf-8'))
            return official_cache(Path(state['config_path']).parent, settings)
        models = settings.get('cc_snapshot', {}).get('models')
        if models is None:
            models = json.loads(Path(settings['catalog']).read_text(encoding='utf-8'))['models']
        return [model for model in models
                if model['slug'] in settings['official_models']]

    def publish(self, source=None, catalog=None, extra=None):
        from management.use_cases.catalog import prepare_publication, complete_publication, write_publication
        with self.lock:
            codex_config = self.current_codex_config()
            settings, external = prepare_publication(
                self.gateway.settings, codex_config, source, catalog, extra)
            merged, official = complete_publication(settings, external, self.official())
            write_publication(self.settings_path, settings, merged, official)
            self.gateway.settings = settings  # Replace one snapshot; never mutate an in-flight request.
            self.sync_error = None
            if settings['source']['type'] == 'cc-switch':
                self.cache_cc(external)
            else:
                self.cc_catalog = None
                self.last_synced_at = None
            return {'saved': True, 'restart_client_for_model_list': True}

    def model_labels(self):
        """Resolve logged model keys to the provider and name shown in the model list."""
        try:
            with self.lock:
                if self.gateway.settings['source']['type'] == 'cc-switch':
                    labels = {}
                    for entry in getattr(self.cc_catalog, 'inventory', None) or []:
                        for model in entry['models']:
                            labels[entry['provider_key'] + '/' + model['model_id']] = (
                                entry['name'], model.get('display_name') or model['model_id'])
                    return labels
                catalog = load_source(self.gateway.settings)
                return {key: (model['provider'], model['display_name'])
                        for key, model in catalog.models.items()}
        except (OSError, ValueError, KeyError, TypeError):
            return {}

    def view(self):
        with self.lock:
            settings = self.gateway.settings
            source = settings['source']
            cc_path = settings.get('cc_db_path', str(Path.home()/'.cc-switch/cc-switch.db'))
            mode = 'cc_switch' if source['type'] == 'cc-switch' else 'independent'
            routing_mode, routing_interrupted = self._routing_status()
            result = {'routing_mode': routing_mode, 'routing_interrupted': routing_interrupted,
                      'mode': mode, 'cc_db_path': source['path'] if mode == 'cc_switch' else cc_path,
                      'config': {'version': 1, 'providers': {}}, 'inventory': [], 'models': [],
                      'source_error': self.sync_error, 'sync_revision': None, 'catalog_pending': False,
                      'native_routing': True, 'official_model_count': len(settings['official_models']),
                      'credential_status': {}, 'source_id': source_key(source)}
            result['last_synced_at'] = self.last_synced_at
            result['sync_mode'] = self.sync_mode
            result['desktop_preferences'] = self.desktop_preferences()
            result['routing_operation'] = self.routing_operation
            runtime = getattr(self.gateway, 'runtime', None)
            result['forwarding'] = runtime.snapshot() if runtime is not None else {'status': 'running', 'error': None}
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
                official_models_enabled = settings.get('official_models_enabled', True)
                official_source = self.official()
                official = official_source if official_models_enabled else []
                result['catalog_pending'] = merged_catalog(
                    official_source, catalog,
                    include_official=official_models_enabled,
                ) != json.loads(
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

    def save_models(self, source_id, updates):
        """Hybrid-only membership/compatibility; never write to CC Switch."""
        with self.lock:
            settings = copy.deepcopy(self.gateway.settings)
            key = source_key(settings['source'])
            if source_id != key:
                raise ConfigError('MODEL_SOURCE_CHANGED')
            if not isinstance(updates, list) or not updates or len(updates) > 1000:
                raise ConfigError('INVALID_MODEL_PREFERENCES')
            catalog = load_source(settings)
            from management.use_cases.models import prepare_model_preferences
            preferences = prepare_model_preferences(settings, catalog, updates)
            return self.publish(extra={'model_preferences': preferences})

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
            from management.use_cases.providers import prepare_provider_document, prepare_provider_preferences
            raw, previous_models = prepare_provider_document(
                read_yaml(source_path), source_path, provider_id, spec, api_key, delete)
            target = self.directory/'managed-models.yaml'
            catalog = Catalog(target, data=raw)
            preferences = prepare_provider_preferences(
                settings, catalog, load_source(settings), provider_id,
                {} if delete else raw['providers'][provider_id]['models'], previous_models)
            official_models_enabled = settings.get('official_models_enabled', True)
            merged_catalog(self.official(), catalog, include_official=official_models_enabled)
            private_write(target, yaml.safe_dump(raw, allow_unicode=True, sort_keys=False))
            return self.publish({'type': 'yaml', 'path': str(target)}, catalog=catalog,
                                extra={'standalone_source': {'type': 'yaml', 'path': str(target)},
                                       'model_preferences': preferences})

    def test_connection(self, key):
        from management.use_cases.connection_test import test_connection
        return test_connection(self.gateway, self.route, self.sse_events, key)
