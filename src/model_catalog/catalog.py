"""Validated provider configuration; published model listings never include credentials."""
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit


class ConfigError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def fail(code):
    raise ConfigError(code)


def mapping(value, allowed, required=()):
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        fail('CONFIG_MAPPING_REQUIRED')
    if set(value) - set(allowed):
        fail('CONFIG_UNKNOWN_FIELD')
    if set(required) - set(value):
        fail('CONFIG_MISSING_FIELD')
    return value


def string(value):
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        fail('CONFIG_INVALID_STRING')
    return value


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', value):
        fail('CONFIG_INVALID_IDENTIFIER')
    return value


def enabled(value):
    if type(value) is not bool:
        fail('CONFIG_INVALID_ENABLED')
    return value


def positive(value, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        fail('CONFIG_INVALID_LIMIT')
    return value


def optional_positive(value, maximum):
    return None if value is None else positive(value, maximum)


DEFAULT_CONTEXT_WINDOW = 131072
MAX_CONTEXT_WINDOW = 16777216
MAX_OUTPUT_TOKENS = 1048576


def read_yaml(path):
    try:
        import yaml
    except ImportError:
        fail('YAML_DEPENDENCY_MISSING')

    class Loader(yaml.SafeLoader):
        def compose_node(self, parent, index):
            if self.check_event(yaml.AliasEvent):
                fail('CONFIG_YAML_ALIASES_UNSUPPORTED')
            return super().compose_node(parent, index)

        def construct_mapping(self, node, deep=False):
            result = {}
            for key_node, value_node in node.value:
                key = self.construct_object(key_node, deep=deep)
                if not isinstance(key, str):
                    fail('CONFIG_KEYS_MUST_BE_STRINGS')
                if key in result:
                    fail('CONFIG_DUPLICATE_KEY')
                result[key] = self.construct_object(value_node, deep=deep)
            return result

    with Path(path).open('rb') as stream:
        data = stream.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        fail('CONFIG_TOO_LARGE')
    try:
        return yaml.load(data.decode('utf-8'), Loader=Loader)
    except (yaml.YAMLError, UnicodeError, RecursionError):
        # YAML exceptions often include source excerpts. Never propagate them.
        fail('CONFIG_INVALID_YAML')


# These fields belong to the bridge, not to vendor-specific parameters.
RESERVED_PARAMETERS = frozenset({
    'model', 'input', 'messages', 'tools', 'stream', 'n', 'max_tokens',
    'max_completion_tokens', 'max_output_tokens',
    'store', 'instructions',
    'api_key', 'base_url', 'headers', 'authorization',
})


def parameters(value):
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        fail('CONFIG_INVALID_PARAMETERS')
    if {k.lower() for k in value} & RESERVED_PARAMETERS:
        fail('CONFIG_RESERVED_PARAMETER')
    try:
        json.dumps(value, allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        fail('CONFIG_PARAMETERS_MUST_BE_JSON')
    return value


class Catalog:
    def __init__(self, path, data=None, *, source_identifiers=False):
        self.path = Path(path).resolve()
        raw = mapping(read_yaml(self.path) if data is None else data, {'version', 'default_model', 'providers'},
                      {'version', 'providers'})
        if type(raw['version']) is not int or raw['version'] != 1:
            fail('CONFIG_UNSUPPORTED_VERSION')
        providers = raw['providers']
        if not isinstance(providers, dict):
            fail('CONFIG_PROVIDERS_REQUIRED')
        self.providers, self.models = {}, {}
        for provider_id, spec in providers.items():
            (string if source_identifiers else identifier)(provider_id)
            mapping(spec, {'protocol', 'base_url', 'credentials', 'models', 'enabled',
                           'timeout_seconds', 'token_limit_field', 'parameters',
                           'responses_compatibility', 'history_migration'},
                    {'protocol', 'base_url', 'credentials', 'models'})
            if spec['protocol'] not in {'openai_chat_completions', 'openai_responses'}:
                fail('CONFIG_UNSUPPORTED_PROTOCOL')
            compatibility = spec.get('responses_compatibility', 'portable' if spec['protocol'] == 'openai_responses' else 'native')
            if compatibility not in ('native', 'portable'):
                fail('CONFIG_INVALID_RESPONSES_COMPATIBILITY')
            history_migration = enabled(spec.get('history_migration', False))
            if spec['protocol'] != 'openai_responses' and (
                    compatibility != 'native' or history_migration):
                fail('CONFIG_UNSUPPORTED_PROTOCOL_OPTIONS')
            base = string(spec['base_url']).rstrip('/')
            try:
                url = urlsplit(base)
                port = url.port
            except ValueError:
                fail('CONFIG_INVALID_BASE_URL')
            if (url.scheme != 'https' or not url.hostname or url.username is not None
                    or url.password is not None or url.query or url.fragment
                    or any(c.isspace() for c in base) or port == 0
                    or '\\' in base or base.endswith(('/chat/completions', '/responses'))):
                fail('CONFIG_INVALID_BASE_URL')
            credentials = mapping(spec['credentials'], {'api_key', 'api_key_env', 'env_file'})
            inline_key = None
            key_env = None
            env_file = None
            if 'api_key' in credentials:
                if set(credentials) != {'api_key'}:
                    fail('CONFIG_AMBIGUOUS_CREDENTIALS')
                inline_key = string(credentials['api_key'])
            else:
                if 'api_key_env' not in credentials:
                    fail('CONFIG_MISSING_FIELD')
                key_env = string(credentials['api_key_env'])
                if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key_env):
                    fail('CONFIG_INVALID_ENV_NAME')
                if 'env_file' in credentials:
                    env_file = (self.path.parent / Path(string(credentials['env_file'])).expanduser()).resolve()
            token_field = spec.get('token_limit_field', 'max_tokens')
            if not isinstance(token_field, str) or token_field not in {'max_tokens', 'max_completion_tokens'}:
                fail('CONFIG_INVALID_TOKEN_FIELD')
            suffix = '/responses' if spec['protocol'] == 'openai_responses' else '/chat/completions'
            provider = {'protocol': spec['protocol'], 'endpoint': base + suffix,
                'responses_compatibility': compatibility, 'history_migration': history_migration,
                'api_key': inline_key, 'api_key_env': key_env, 'env_file': env_file,
                'enabled': enabled(spec.get('enabled', True)),
                'timeout_seconds': positive(spec.get('timeout_seconds', 180), 3600),
                'token_limit_field': token_field, 'parameters': parameters(spec.get('parameters', {}))}
            self.providers[provider_id] = provider
            if not isinstance(spec['models'], dict) or not spec['models']:
                fail('CONFIG_MODELS_REQUIRED')
            for alias, model in spec['models'].items():
                (string if source_identifiers else identifier)(alias)
                mapping(model, {'model_id', 'display_name', 'max_output_tokens', 'context_window', 'enabled', 'parameters', 'responses_compatibility'},
                        {'model_id'})
                key = provider_id + '/' + alias
                if key in self.models:
                    fail('CONFIG_DUPLICATE_MODEL_KEY')
                model_enabled = enabled(model.get('enabled', True))
                model_compatibility = model.get('responses_compatibility', compatibility)
                if model_compatibility not in ('native', 'portable'):
                    fail('CONFIG_INVALID_RESPONSES_COMPATIBILITY')
                if provider['protocol'] != 'openai_responses' and model_compatibility != 'native':
                    fail('CONFIG_UNSUPPORTED_PROTOCOL_OPTIONS')
                output_limit = optional_positive(model.get('max_output_tokens'), MAX_OUTPUT_TOKENS)
                self.models[key] = {'key': key, 'provider': provider_id,
                    'protocol': provider['protocol'], 'model_id': string(model['model_id']),
                    'display_name': string(model.get('display_name', key)),
                    'enabled': provider['enabled'] and model_enabled,
                    'source_enabled': provider['enabled'] and model_enabled,
                    'responses_compatibility': model_compatibility,
                    'max_output_tokens': output_limit,
                    'output_limit_configured': output_limit is not None,
                    'context_window': positive(model.get('context_window', DEFAULT_CONTEXT_WINDOW),
                                               MAX_CONTEXT_WINDOW),
                    'parameters': {**provider['parameters'], **parameters(model.get('parameters', {}))}}
        self.default_model = raw.get('default_model')
        if self.default_model is not None:
            if not isinstance(self.default_model, str) or self.default_model not in self.models:
                fail('CONFIG_DEFAULT_MODEL_UNKNOWN')
            if not self.models[self.default_model]['enabled']:
                fail('CONFIG_DEFAULT_MODEL_DISABLED')

    def select(self, key=None):
        selected = self.default_model if key is None else key
        if selected is None:
            fail('MODEL_SELECTION_REQUIRED')
        if selected not in self.models:
            fail('MODEL_NOT_CONFIGURED')
        if not self.models[selected]['enabled']:
            fail('MODEL_DISABLED')
        model = self.models[selected]
        return model, {**self.providers[model['provider']],
                       'responses_compatibility': model['responses_compatibility']}

    def listing(self, include_disabled=False):
        # Credentials and paths never enter the public model directory.
        return [{key: model[key] for key in ('key', 'provider', 'protocol', 'model_id',
                  'display_name', 'enabled', 'max_output_tokens', 'output_limit_configured',
                  'context_window', 'source_enabled', 'responses_compatibility')} |
                {'default': model['key'] == self.default_model, 'validation': 'not_checked'}
                for model in self.models.values() if include_disabled or model['enabled']]


def resolve_api_key(provider):
    if callable(provider.get('key_resolver')):
        return string(provider['key_resolver']())
    if provider.get('api_key') is not None:
        return string(provider['api_key'])
    value = os.environ.get(provider['api_key_env'])
    if value:
        return string(value)
    if provider['env_file'] is not None:
        values = {}
        for line in provider['env_file'].read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            key, sep, value = line.removeprefix('export ').partition('=')
            if not sep:
                fail('CREDENTIALS_INVALID_ENV_FILE')
            value = value.strip()
            if value[:1] in {'"', "'"} and value[-1:] == value[:1]:
                value = value[1:-1]
            values[key.strip()] = value
        value = values.get(provider['api_key_env'])
        if value:
            return string(value)
    fail('CREDENTIALS_NOT_FOUND')
