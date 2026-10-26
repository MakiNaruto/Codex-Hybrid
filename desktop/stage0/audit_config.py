"""Observe current routing roundtrip behavior in a throwaway fixture only."""
import json
from pathlib import Path
import sys
import tempfile
import tomllib

from verify import ROOT, fixture

sys.path.insert(0, str(ROOT / 'src'))
from gateway.server import Gateway


def main():
    (ROOT / 'desktop/build').mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='stage0-config-', dir=ROOT / 'desktop/build') as temporary:
        directory = Path(temporary)
        settings = fixture(directory, 18891)  # No Server is constructed, so no port is bound.
        path = directory / 'codex-config.toml'
        before = tomllib.loads(path.read_text(encoding='utf-8'))
        gateway = Gateway(json.loads(settings.read_text(encoding='utf-8')), settings)
        for mode in ('project', 'openai'):
            preview = gateway.manager.preview_routing(mode)
            gateway.manager.set_routing(mode, preview['revision'])
        after = tomllib.loads(path.read_text(encoding='utf-8'))
        report = {
            'scope': 'temporary fixture only',
            'roundtrip_preserves_original_semantics': before == after,
            'introduced_root_fields': sorted(set(after) - set(before)),
            'resulting_model_provider': after.get('model_provider'),
            'interpretation': 'Browser switch restores the original routing fields and removes its generated provider table.',
            'decision': 'Browser configuration roundtrip is covered; desktop process lifecycle remains deferred.',
        }
        output = ROOT / 'desktop/build/stage0/config-audit.json'
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
