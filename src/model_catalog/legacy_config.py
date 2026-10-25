"""Configuration reader for existing single-provider runtime settings."""
from pathlib import Path
import urllib.parse

def load_config(path):
    values = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, sep, value = line.removeprefix('export ').partition('=')
        if not sep:
            raise ValueError('Invalid env file entry')
        value = value.strip()
        if value[:1] in {'"', "'"} and value[-1:] == value[:1]:
            value = value[1:-1]
        values[key.strip()] = value
    required = ['DEEPSEEK_API_KEY', 'DEEPSEEK_BASE_URL', 'DEEPSEEK_MODEL']
    if not all(values.get(key) for key in required):
        raise ValueError('Missing required DeepSeek configuration')
    base = values['DEEPSEEK_BASE_URL'].rstrip('/')
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme != 'https' or parsed.hostname != 'api.deepseek.com' or parsed.username or parsed.password:
        raise ValueError('This probe only allows the official HTTPS DeepSeek API')
    values['DEEPSEEK_BASE_URL'] = base
    return values


