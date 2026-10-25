"""Windows bootstrap; keep secrets and user input out of shell command strings."""
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.version_info < (3, 11):
        sys.exit('Python 3.11+ is required. Install from python.org and enable the Python launcher.')
    python = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.is_file():
        venv.create(ROOT / '.venv', with_pip=True)
    check = subprocess.run([str(python), '-c', 'import yaml; import psutil'], capture_output=True)
    if check.returncode:
        subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(ROOT / 'requirements.txt')], check=True)
    args = sys.argv[1:]
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT / 'src'), str(ROOT), os.environ.get('PYTHONPATH', '')]))
    return subprocess.call([str(python), '-m', 'cli', *args], cwd=ROOT, env=env)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, subprocess.CalledProcessError):
        sys.exit('Setup failed. Check Python installation, network access and directory permissions, then retry.')
