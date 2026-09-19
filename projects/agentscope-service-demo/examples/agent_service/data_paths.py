"""One persistent root for this deployment; independent of the working directory."""
import os
from pathlib import Path

DATA_ROOT = Path(os.environ.get("AGENTSCOPE_DATA_DIR", "/workspace/data/agentscope")).expanduser()
if not DATA_ROOT.is_absolute():
    raise ValueError("AGENTSCOPE_DATA_DIR must be an absolute path")
DATA_ROOT = DATA_ROOT.resolve()
PORTAL_FILE = DATA_ROOT / "portal" / "portal-data.json"
PROJECTS = DATA_ROOT / "projects"
SKILLS = DATA_ROOT / "skills"
SESSION_FILES = DATA_ROOT / "session-files"
WORKSPACES = DATA_ROOT / "workspaces"
QDRANT = DATA_ROOT / "qdrant"

for directory in (PORTAL_FILE.parent, PROJECTS, SKILLS, SESSION_FILES, WORKSPACES, QDRANT):
    directory.mkdir(parents=True, exist_ok=True)
