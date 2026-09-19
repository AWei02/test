"""Preserve the inspected service environment while deploying the project feature."""
import os, signal, subprocess, time
from pathlib import Path
pid=5960
repo=Path('/workspace/projects/agentscope-service-demo')
proc=Path('/proc')/str(pid)
assert (proc/'cwd').resolve()==repo/'examples/agent_service'
assert b'main.py' in (proc/'cmdline').read_bytes()
env=dict(x.decode().split('=',1) for x in (proc/'environ').read_bytes().split(b'\0') if b'=' in x)
os.kill(pid,signal.SIGTERM)
for _ in range(16):
    if not proc.exists():break
    time.sleep(.5)
if proc.exists():os.kill(pid,signal.SIGKILL)
with open('/tmp/agentscope-portal-server.log','ab',buffering=0) as log:
    p=subprocess.Popen([str(repo/'.venv/bin/python'),'main.py'],cwd=repo/'examples/agent_service',env=env,
        stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
print('Portal PID',p.pid)
