"""Destructive reset of this deployment only; requires explicit confirmation."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path('/workspace/data/agentscope')
SERVICE = Path('/workspace/projects/agentscope-service-demo/examples/agent_service')


def run(*args):
    return subprocess.check_output(args, text=True).strip()


if __name__ == '__main__':
    if sys.argv[1:] != ['--confirm-permanent-delete']:
        raise SystemExit('Requires --confirm-permanent-delete; stop Python service first.')
    assert ROOT.is_dir() and not ROOT.is_symlink() and ROOT.resolve() == ROOT
    assert Path(__file__).resolve().parent == SERVICE
    assert not run('ss', '-ltnH', 'sport = :8000'), 'Backend must be stopped'
    expected = {'backups', 'portal', 'projects', 'skills', 'session-files',
                'workspaces', 'blobs', 'qdrant', 'redis', 'logs', 'checks'}
    assert {p.name for p in ROOT.iterdir()} <= expected, 'Unexpected data paths; inspect first'
    info = json.loads(run('docker', 'inspect', 'agentscope-redis-demo'))[0]
    assert any(m['Source'] == str(ROOT / 'redis') and m['Destination'] == '/data'
               for m in info['Mounts'])
    run('docker', 'compose', '-f', str(SERVICE / 'compose.storage.yaml'), 'down')
    # Root privileges are confined to the explicit mounted data directory.
    # find only selects its immediate children; rm does not follow symlinks.
    run('docker', 'run', '--rm', '--user', '0:0', '--network', 'none',
        '--mount', f'type=bind,source={ROOT},target=/reset',
        '--entrypoint', 'sh', 'redis:7', '-c',
        'find /reset -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +')
    assert not list(ROOT.iterdir()), 'Reset incomplete'
    from portal import load
    data = load()
    assert len(data['users']) == 1 and not data['grants']
    for name in ('redis', 'logs'):
        (ROOT / name).mkdir(exist_ok=True)
    run('docker', 'compose', '-f', str(SERVICE / 'compose.storage.yaml'), 'up', '-d')
    print('Reset complete. Only default administrator and built-in roles initialized.')
