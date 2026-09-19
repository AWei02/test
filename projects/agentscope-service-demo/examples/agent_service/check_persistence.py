"""Create/check a non-business marker across a real host shutdown.

Run --initialize once before shutdown; run without arguments after boot.
Never initialize again to verify an existing marker.
"""
import json
import subprocess
import sys
from datetime import datetime, timezone
from uuid import uuid4
from data_paths import DATA_ROOT

KEY = '__agentscope_persistence_check__'
MARKER = DATA_ROOT / 'checks' / 'persistence.json'


def redis(*args):
    return subprocess.check_output(
        ['docker', 'exec', 'agentscope-redis-demo', 'redis-cli', '--raw', *args],
        text=True).strip()


if __name__ == '__main__':
    if sys.argv[1:] == ['--initialize']:
        assert not MARKER.exists(), 'Marker already exists; run without --initialize'
        token = uuid4().hex
        assert redis('SET', KEY, token, 'NX') == 'OK'
        MARKER.parent.mkdir(parents=True, exist_ok=True)
        MARKER.write_text(json.dumps({'token': token,
            'created_at': datetime.now(timezone.utc).isoformat()}, indent=2))
        assert redis('SAVE') == 'OK'
    elif sys.argv[1:]:
        raise SystemExit('Use no arguments to check, or --initialize once before shutdown')
    payload = json.loads(MARKER.read_text())
    assert redis('GET', KEY) == payload['token'], 'Redis marker missing or different'
    print('PASS: disk and Redis markers match. Created: ' + payload['created_at'])
