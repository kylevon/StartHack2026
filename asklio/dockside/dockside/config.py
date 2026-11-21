"""Settings, read once from the environment (and the repo's .env files)."""
import os
from pathlib import Path

from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parents[1]  # asklio/dockside
REPO_DIR = APP_DIR.parents[1]

load_dotenv(REPO_DIR / ".env")
load_dotenv(REPO_DIR / ".env.local", override=True)  # untracked: API keys go here

DATA_DIR = Path(os.environ.get("DOCKSIDE_DATA_DIR", APP_DIR.parent / "data" / "soony-data")).resolve()
STATE_DIR = Path(os.environ.get("DOCKSIDE_STATE_DIR", APP_DIR / ".dockside")).resolve()
MODEL = os.environ.get("DOCKSIDE_MODEL", "anthropic:claude-opus-5-5")
POLL_SECONDS = float(os.environ.get("DOCKSIDE_POLL_SECONDS", "5"))
PORT = int(os.environ.get("DOCKSIDE_PORT", "8000"))
WEB_DIR = APP_DIR / "web"
COMPACT_TOKENS = int(os.environ.get("DOCKSIDE_COMPACT_TOKENS", "150000"))  # non-Claude models: summarise history past this size

# Optional plain-text description of whose documents these are and what matters to them.
_brief_path = Path(os.environ.get("DOCKSIDE_BRIEF", APP_DIR / "brief.md"))
BRIEF = _brief_path.read_text().strip() if _brief_path.is_file() else ""
