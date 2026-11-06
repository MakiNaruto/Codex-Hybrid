"""Authenticated official model discovery and atomic local directory refresh."""
from contextlib import nullcontext
import json
from pathlib import Path
import urllib.error
import urllib.request

from gateway.routing import MAX_BODY, official_headers
from infrastructure.files import write_private_text as private_write
from infrastructure.locking import DirectoryLock
from model_catalog.sources import load_source, merged_catalog, update_cc_snapshot

OPENAI_MODELS_URL = 'https://chatgpt.com/backend-api/codex/models'


def authenticated_official_catalog(headers, settings, opener, query=''):
    """Fetch the account-scoped catalog with Codex auth; return None if unavailable."""
    if not headers.get('Authorization', '').startswith('Bearer '):
        return None
    # Keep Codex's version/capability query on the fixed official endpoint.
    url = OPENAI_MODELS_URL + ('?' + query if query else '')
    request = urllib.request.Request(url,
        headers=official_headers(headers, settings, 'application/json'))
    try:
        with opener.open(request, timeout=15) as response:
            data = json.loads(response.read(MAX_BODY))
        models = data.get('models') if isinstance(data, dict) else None
        if not isinstance(models, list) or any(
                not isinstance(model, dict) or not isinstance(model.get('slug'), str)
                for model in models):
            return None
        return models
    except (OSError, ValueError, urllib.error.URLError):
        return None


def refresh_official_directory(owner, headers, query=''):
    settings = owner.settings
    if settings.get('official_models_enabled') is False:
        return None
    official = authenticated_official_catalog(headers, settings, owner.opener, query)
    if official is None:
        return None
    settings_path = getattr(owner, 'settings_path', None)
    # Fetch outside the lock, then merge with the latest committed settings.
    # Management and forwarding run in different processes.
    with DirectoryLock(Path(settings_path).parent) if settings_path else nullcontext():
        if settings_path:
            settings = json.loads(Path(settings_path).read_text(encoding='utf-8'))
        else:
            settings = owner.settings
        # A catalog response can be capability/version filtered. Absence is not
        # a revocation: retain official entries already advertised by Codex.
        # The upstream responses endpoint remains the authority on entitlement.
        known = {model['slug']: model for model in settings.get('official_catalog', [])}
        if settings_path:
            state_path = Path(settings_path).parent / 'state.json'
            try:
                state = json.loads(state_path.read_text(encoding='utf-8'))
                from codex_integration.service import official_cache
                for model in official_cache(Path(state['config_path']).parent, settings):
                    known[model['slug']] = model
            except (OSError, ValueError, KeyError, TypeError):
                pass
        known.update((model['slug'], model) for model in official)
        official = list(known.values())
        updated = dict(settings, official_catalog=official,
                       official_models=[model['slug'] for model in official])
        if 'source' in settings:
            external = load_source(settings)
            directory = merged_catalog(official, external)
            update_cc_snapshot(updated, directory, external)
        else:
            directory = {'models': official}
        updated['models'] = [model['slug'] for model in directory['models']]
        if settings_path:
            catalog_path = Path(updated['catalog'])
            previous = catalog_path.read_bytes() if catalog_path.exists() else None
            private_write(catalog_path, json.dumps(directory, ensure_ascii=False))
            try:
                private_write(Path(settings_path), json.dumps(updated, ensure_ascii=False))
            except OSError:
                if previous is None:
                    catalog_path.unlink(missing_ok=True)
                else:
                    private_write(catalog_path, previous.decode('utf-8'))
                raise
        owner.settings = updated
    return directory


def cached_directory(settings):
    """Return only a complete directory matching the current routing allowlist."""
    models = settings.get('cc_snapshot', {}).get('models')
    if models is None:
        try:
            models = json.loads(Path(settings['catalog']).read_text(encoding='utf-8'))['models']
        except (OSError, ValueError, KeyError, TypeError):
            return None
    if (not isinstance(models, list) or not models or any(
            not isinstance(model, dict) or not isinstance(model.get('slug'), str)
            for model in models)):
        return None
    if [model['slug'] for model in models] != settings['models']:
        return None
    return {'models': models}
