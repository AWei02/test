"""One-time migration for the existing VM. Stop the backend before running.

Copies and hashes files before moving originals to backups and installing aliases.
Never loads an old Redis volume. Requires the current Redis database to be empty.
"""
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

SOURCE = Path(__file__).resolve().parent
TARGET = Path('/workspace/data/agentscope')
MAPPING = {
    'portal-data.json': 'portal/portal-data.json',
    'project-data': 'projects',
    'skill-packages': 'skills',
    'skill-workspaces': 'session-files',
    'workspaces': 'workspaces',
    'blobs': 'blobs',
}


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def manifest(path):
    files = [path] if path.is_file() else sorted(path.rglob('*'))
    return {str(p.relative_to(path)) if p != path else '.':
            ('link:' + str(p.readlink()) if p.is_symlink()
             else hashlib.sha256(p.read_bytes()).hexdigest())
            for p in files if p.is_symlink() or p.is_file()}


def main():
    assert SOURCE == Path('/workspace/projects/agentscope-service-demo/examples/agent_service')
    assert not TARGET.exists(), 'Target already exists; inspect before retrying'
    listeners = run('ss', '-ltnH', 'sport = :8000')
    assert not listeners, 'Stop the backend first'
    assert run('docker', 'exec', 'agentscope-redis-demo', 'redis-cli', 'DBSIZE') == '0'
    assert not run('docker', 'exec', 'agentscope-redis-demo', 'redis-cli', 'INFO', 'keyspace').replace('# Keyspace', '').strip(), 'Nonempty Redis database found'
    for name in MAPPING:
        source = SOURCE / name
        assert source.exists() and not source.is_symlink(), source
    TARGET.mkdir(parents=True, mode=0o700)
    backup = TARGET / 'backups' / ('migration-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    backup.mkdir(parents=True, mode=0o700)
    hashes = {}
    for name, destination in MAPPING.items():
        source, dest = SOURCE / name, TARGET / destination
        dest.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, dest, symlinks=True)
        else:
            shutil.copy2(source, dest)
        hashes[name] = manifest(source)
        assert hashes[name] == manifest(dest), f'Copy verification failed: {name}'
    (backup / 'sha256-manifest.json').write_text(json.dumps(hashes, indent=2))

    # History buckets are keyed by the resolved absolute file-directory name.
    pairs = [(p, TARGET / 'projects' / p.parent.name / 'files')
             for p in (SOURCE / 'project-data').glob('*/files') if p.is_dir()]
    pairs += [(p, TARGET / 'session-files' / p.name)
              for p in (SOURCE / 'skill-workspaces').iterdir() if p.is_dir()]
    rekeyed = 0
    for old, new in pairs:
        history = TARGET / 'projects' / 'history'
        old_bucket = history / hashlib.sha256(str(old.resolve()).encode()).hexdigest()
        new_bucket = history / hashlib.sha256(str(new.resolve()).encode()).hexdigest()
        if old_bucket.exists():
            assert not new_bucket.exists()
            old_bucket.rename(new_bucket)
            rekeyed += 1
    for name, destination in MAPPING.items():
        source = SOURCE / name
        # Exact known children only. Originals remain recoverable in backups.
        assert source.parent == SOURCE and (backup / name).parent == backup
        assert manifest(source) == hashes[name], 'Source changed during migration'
        source.rename(backup / name)
        source.symlink_to(TARGET / destination, target_is_directory=(backup / name).is_dir())
    for name in ('redis', 'qdrant', 'logs'):
        (TARGET / name).mkdir(exist_ok=True)

    # Snapshot the current empty instance, not yesterday's orphaned volume.
    run('docker', 'exec', 'agentscope-redis-demo', 'redis-cli', 'SAVE')
    run('docker', 'cp', 'agentscope-redis-demo:/data/dump.rdb', str(backup / 'current-empty-redis.rdb'))
    assert run('docker', 'exec', 'agentscope-redis-demo', 'redis-cli', 'DBSIZE') == '0'
    assert not run('docker', 'exec', 'agentscope-redis-demo', 'redis-cli', 'INFO', 'keyspace').replace('# Keyspace', '').strip()
    run('docker', 'stop', 'agentscope-redis-demo')  # Old --rm container removes itself.
    run('docker', 'compose', '-f', str(SOURCE / 'compose.storage.yaml'), 'up', '-d')
    print(json.dumps({'data_root': str(TARGET), 'backup': str(backup),
                      'verified_files': sum(map(len, hashes.values())),
                      'history_buckets_rekeyed': rekeyed}))


if __name__ == '__main__':
    main()
